import json
import zipfile
from pathlib import Path

import pytest

from dpi_eval.iiif import CanvasRecord
from dpi_eval.sessions import (
    SessionError, confirm_session, create_iiif_session, export_session,
    load_session, mark_no_text, save_page, session_dir, stage_for_grade,
    stage_ocr, transcriptions_root,
)


@pytest.fixture
def iiif_session(tmp_path):
    root = transcriptions_root(tmp_path)
    records = [
        CanvasRecord(f"https://x/c/{i}", f"Page {i}",
                     f"https://x/i/{i}/full/max/0/default.jpg", None)
        for i in range(3)
    ]
    session = create_iiif_session(root, "https://x/m", records, "from_scratch", "diamondback")
    confirm_session(root, session["id"], [0, 1, 2])
    return root, session["id"]


def test_stage_ocr_aligns_by_index_and_persists(iiif_session):
    root, sid = iiif_session
    files = [(f"page_{i}.hocr", b"<div class='ocr_page'>x</div>") for i in range(3)]
    result = stage_ocr(root, sid, files)
    assert result["matched"]["p0000-page-0"] == "page_0.hocr"
    saved = json.loads((session_dir(root, sid) / "staging" / "alignment.json").read_text())
    assert saved["matched"] == result["matched"]


def test_stage_for_grade_filters_to_saved_and_normalizes_ext(iiif_session):
    root, sid = iiif_session
    save_page(root, sid, 0, "text zero\n", elapsed=1, active=1, nonce="a")
    save_page(root, sid, 1, "text one\n", elapsed=1, active=1, nonce="b")
    mark_no_text(root, sid, 2, "blank")
    # Crash orphan: GT on disk for the no_text page — must NOT be staged.
    orphan = session_dir(root, sid) / "gt" / "p0002-page-2.gt.txt"
    stage_ocr(root, sid, [(f"page_{i}.hocr", b"x") for i in range(3)])
    orphan.write_text("orphan\n")
    with pytest.raises(SessionError):  # needs-attention blocks grading
        stage_for_grade(root, sid, {})
    orphan.unlink()
    gt_dir, ocr_dir = stage_for_grade(root, sid, {})
    assert sorted(p.name for p in gt_dir.iterdir()) == [
        "p0000-page-0.gt.txt", "p0001-page-1.gt.txt"]
    assert sorted(p.name for p in ocr_dir.iterdir()) == [
        "p0000-page-0.hocr", "p0001-page-1.hocr"]


def test_stage_for_grade_applies_manual_overrides(iiif_session):
    root, sid = iiif_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="a")
    stage_ocr(root, sid, [("vendor-weird-name.xml", b"<x/>")])
    gt_dir, ocr_dir = stage_for_grade(root, sid, {"p0000-page-0": "vendor-weird-name.xml"})
    assert (ocr_dir / "p0000-page-0.xml").exists()


def test_stage_for_grade_requires_a_saved_page(iiif_session):
    root, sid = iiif_session
    stage_ocr(root, sid, [("page_0.hocr", b"x")])
    with pytest.raises(SessionError):
        stage_for_grade(root, sid, {})


def test_export_bundle_layout_and_sidecar(iiif_session):
    root, sid = iiif_session
    save_page(root, sid, 0, "kept\n", elapsed=9, active=5, nonce="a")
    mark_no_text(root, sid, 1, "illegible")
    zip_path = export_session(root, sid)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert f"diamondback/{sid}/gt/p0000-page-0.gt.txt" in names
        sidecar = json.loads(zf.read(f"diamondback/{sid}/transcriptions.json"))
    rows = {r["stem"]: r for r in sidecar["pages"]}
    assert rows["p0000-page-0"]["status"] == "saved"
    assert rows["p0000-page-0"]["arm"] == "from_scratch"
    assert rows["p0001-page-1"]["no_text_reason"] == "illegible"
    assert rows["p0002-page-2"]["status"] == "pending"  # every selected page
    assert sidecar["conventions_version"] == load_session(root, sid)["conventions_version"]


def test_stage_for_grade_rejects_dangling_override(iiif_session):
    root, sid = iiif_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="a")
    stage_ocr(root, sid, [("page_0.hocr", b"x")])
    with pytest.raises(SessionError):
        stage_for_grade(root, sid, {"p0000-page-0": "no-such-file.xml"})


def test_export_flattens_hostile_collection_label(tmp_path):
    root = transcriptions_root(tmp_path)
    records = [CanvasRecord(
        "https://x/c/0", "Page 0", "https://x/i/0/full/max/0/default.jpg", None)]
    session = create_iiif_session(root, "https://x/m", records, "from_scratch", "../evil/name")
    confirm_session(root, session["id"], [0])
    save_page(root, session["id"], 0, "x\n", elapsed=1, active=1, nonce="n")
    zip_path = export_session(root, session["id"])
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert names
    for name in names:
        assert ".." not in name and not name.startswith("/")
        assert name.startswith("evil-name/")
