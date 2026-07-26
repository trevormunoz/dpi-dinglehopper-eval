import json
import threading
import zipfile
from pathlib import Path

import pytest

from dpi_eval import sessions
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


def test_stage_for_grade_rejects_traversing_override(iiif_session, tmp_path):
    """PAR C1. `.exists()` + a suffix check constrain WHAT a file is named,
    never WHERE it lives, so `../../../secret.txt` satisfied both and its
    contents were copied into the graded set and rendered into the report."""
    root, sid = iiif_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="a")
    stage_ocr(root, sid, [("page_0.txt", b"x")])
    secret = root.parent / "secret.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")
    # staging/ocr is three levels below the session root
    escape = "../../../../secret.txt"
    assert (root / sid / "staging" / "ocr" / escape).exists(), "fixture must escape"
    with pytest.raises(SessionError):
        stage_for_grade(root, sid, {"p0000-page-0": escape})


def test_stage_for_grade_rejects_absolute_override(iiif_session, tmp_path):
    """PAR C1. pathlib join with an absolute right-hand side discards the
    left, so no `..` is needed to leave the staging directory."""
    root, sid = iiif_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="a")
    stage_ocr(root, sid, [("page_0.txt", b"x")])
    secret = tmp_path / "absolute-secret.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")
    with pytest.raises(SessionError):
        stage_for_grade(root, sid, {"p0000-page-0": str(secret)})


def test_stage_for_grade_rejects_override_pointing_at_ground_truth(iiif_session):
    """PAR C1. Staging the GT as its own OCR manufactures a 0% error rate
    from a form field — a research-integrity failure, not just a file read."""
    root, sid = iiif_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="a")
    stage_ocr(root, sid, [("page_0.txt", b"x")])
    with pytest.raises(SessionError):
        stage_for_grade(root, sid, {"p0000-page-0": "../../gt/p0000-page-0.gt.txt"})


def test_stage_ocr_rejects_colliding_basenames(iiif_session):
    """PAR S5. Callers pass paths relative to the picked folder, so
    `batch-a/page_0.txt` and `batch-b/page_0.txt` both flattened to
    `page_0.txt`; one silently won and was graded against the other's
    ground truth. `_grade_pipeline` already refuses this shape."""
    root, sid = iiif_session
    stage_ocr(root, sid, [("page_0.txt", b"first pass")])
    survivor = session_dir(root, sid) / "staging" / "ocr" / "page_0.txt"
    with pytest.raises(SessionError) as excinfo:
        stage_ocr(root, sid, [
            ("batch-a/page_0.txt", b"a"), ("batch-b/page_0.txt", b"b")])
    message = excinfo.value.message
    assert "batch-a/page_0.txt" in message and "batch-b/page_0.txt" in message
    # Rejected before any write: earlier staging is not destroyed.
    assert survivor.read_bytes() == b"first pass"


@pytest.mark.parametrize("hostile", [".", "..", "/"])
def test_stage_ocr_rejects_a_name_with_no_basename(iiif_session, hostile):
    """PAR R2-S6. `Path(".").name` is `""`, which is not caught by the
    hidden-file skip (`"".startswith(".")` is False), so `(ocr_dir / "")`
    resolved to the directory and write_bytes raised IsADirectoryError —
    a 500, after clear_staging had already destroyed the real upload."""
    root, sid = iiif_session
    stage_ocr(root, sid, [("page_0.txt", b"first pass")])
    survivor = session_dir(root, sid) / "staging" / "ocr" / "page_0.txt"
    with pytest.raises(SessionError) as excinfo:
        stage_ocr(root, sid, [(hostile, b"x")])
    assert "no usable filename" in excinfo.value.message
    # Rejected before any write, like the collision check next to it.
    assert survivor.read_bytes() == b"first pass"


def _probe_lock(root, session_id, timeout=3.0):
    """Try to take the session lock from a *fresh* thread. The lock is
    re-entrant per thread, so probing on the thread under test would
    always succeed and prove nothing."""
    outcome = []

    def run():
        try:
            with sessions.session_lock(root, session_id):
                outcome.append("acquired")
        except SessionError:
            outcome.append("denied")

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():  # pragma: no cover - would mean the lock hangs
        return "hung"
    return outcome[0]


def _probing_reconcile(root, session_id, seen):
    """reconcile() is the first thing stage_for_grade and export_session
    call, so it is where the lock either is or is not already held."""
    def reconcile(*_args, **_kwargs):
        seen.append(_probe_lock(root, session_id))
        return []
    return reconcile


def test_stage_ocr_holds_the_session_lock(iiif_session, monkeypatch):
    """PAR R2-S4. staging/ decides which OCR file grades which page, so it
    needs the same serialization session.json got."""
    root, sid = iiif_session
    monkeypatch.setattr(sessions, "LOCK_TIMEOUT", 0.2)
    real_align = sessions.align
    seen = []

    def probing_align(*args, **kwargs):
        seen.append(_probe_lock(root, sid))
        return real_align(*args, **kwargs)

    monkeypatch.setattr(sessions, "align", probing_align)
    stage_ocr(root, sid, [("page_0.hocr", b"x")])
    assert seen == ["denied"]


def test_stage_for_grade_holds_the_session_lock(iiif_session, monkeypatch):
    """PAR R2-S4."""
    root, sid = iiif_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="a")
    stage_ocr(root, sid, [("page_0.hocr", b"x")])
    monkeypatch.setattr(sessions, "LOCK_TIMEOUT", 0.2)
    seen = []
    monkeypatch.setattr(sessions, "reconcile", _probing_reconcile(root, sid, seen))
    stage_for_grade(root, sid, {})
    assert seen == ["denied"]


def test_export_session_holds_the_session_lock(iiif_session, monkeypatch):
    """PAR R2-S4. export rmtrees and rebuilds export/ the same way."""
    root, sid = iiif_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="a")
    monkeypatch.setattr(sessions, "LOCK_TIMEOUT", 0.2)
    seen = []
    monkeypatch.setattr(sessions, "reconcile", _probing_reconcile(root, sid, seen))
    export_session(root, sid)
    assert seen == ["denied"]


def test_concurrent_stage_ocr_keeps_alignment_and_staged_files_in_step(
        iiif_session, monkeypatch):
    """PAR R2-S4. One request's clear_staging could land between another's
    write and its align(), so the alignment table on screen described files
    that were no longer staged — a student would confirm a grade against
    OCR that is not there."""
    root, sid = iiif_session
    entered = threading.Event()
    release = threading.Event()
    real_align = sessions.align
    calls = []

    def gated_align(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            release.wait(5)
        return real_align(*args, **kwargs)

    monkeypatch.setattr(sessions, "align", gated_align)
    errors = []

    def stage(name, data):
        try:
            stage_ocr(root, sid, [(name, data)])
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            errors.append(repr(exc))

    first = threading.Thread(target=stage, args=("page_0.hocr", b"first"))
    first.start()
    assert entered.wait(5), "first stage_ocr never reached align()"
    second = threading.Thread(target=stage, args=("page_1.hocr", b"second"))
    second.start()
    # Unserialised, `second` runs to completion inside this window and
    # clears the files `first` is still aligning.
    second.join(0.5)
    release.set()
    first.join(5)
    second.join(5)

    staging = session_dir(root, sid) / "staging"
    staged = {p.name for p in (staging / "ocr").iterdir()}
    matched = json.loads((staging / "alignment.json").read_text())["matched"]
    assert not errors, errors
    assert set(matched.values()) <= staged, (
        f"alignment names {sorted(matched.values())} but staging holds "
        f"{sorted(staged)}")


def test_clear_staging_leaves_staging_alone_while_a_writer_holds_the_lock(
        iiif_session, monkeypatch):
    """PAR R2-S4. An unserialised clear deleted the OCR another request had
    just staged and was still aligning. Cleanup skips rather than raises:
    it runs after a grade run has finished, nothing waits on it, and the
    next preview re-stages under the lock."""
    root, sid = iiif_session
    stage_ocr(root, sid, [("page_0.hocr", b"first pass")])
    staged = session_dir(root, sid) / "staging" / "ocr" / "page_0.hocr"
    monkeypatch.setattr(sessions, "LOCK_TIMEOUT", 0.2)
    holding = threading.Event()
    finish = threading.Event()

    def holder():
        with sessions.session_lock(root, sid):
            holding.set()
            finish.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert holding.wait(5)
    try:
        sessions.clear_staging(root, sid)  # cleanup, so it must not raise
    finally:
        finish.set()
        thread.join(5)
    assert staged.read_bytes() == b"first pass"


def test_stage_ocr_refuses_a_staging_directory_it_could_not_clear(
        iiif_session, monkeypatch):
    """PAR R2-S4. clear_staging swallows rmtree failures (ignore_errors),
    so the following mkdir(parents=True) escaped as a bare FileExistsError
    — an unhandled OSError, i.e. a 500. exist_ok would be the wrong fix:
    the previous upload's files would survive and align() would report OCR
    the student did not pick."""
    root, sid = iiif_session
    stage_ocr(root, sid, [("page_0.hocr", b"first pass")])
    monkeypatch.setattr(sessions.shutil, "rmtree", lambda *a, **k: None)
    with pytest.raises(SessionError) as excinfo:
        stage_ocr(root, sid, [("page_1.hocr", b"second pass")])
    assert "staging" in excinfo.value.message
    ocr_dir = session_dir(root, sid) / "staging" / "ocr"
    assert {p.name for p in ocr_dir.iterdir()} == {"page_0.hocr"}


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
