from pathlib import Path

import pytest
from PIL import Image

from dpi_eval.conventions import CONVENTIONS_VERSION
from dpi_eval.iiif import CanvasRecord
from dpi_eval.sessions import (
    SessionError, confirm_session, create_iiif_session, create_local_session,
    detect_draft_format, list_sessions, load_session, transcriptions_root,
)


@pytest.fixture
def root(tmp_path):
    return transcriptions_root(tmp_path)


@pytest.fixture
def image_folder(tmp_path):
    folder = tmp_path / "masters"
    folder.mkdir()
    for name in ("scan-B.tif", "scan-A.jp2", "notes.md", ".DS_Store"):
        (folder / name).write_bytes(b"x")
    return folder


def test_create_local_session_enumerates_images_sorted_draft_state(root, image_folder):
    session = create_local_session(root, image_folder, "from_scratch", "", None)
    assert session["state"] == "draft"
    assert session["mode"] == "from_scratch"
    assert session["conventions_version"] == CONVENTIONS_VERSION
    assert [p["stem"] for p in session["pages"]] == ["scan-A", "scan-B"]
    assert session["pages"][0]["status"] == "pending"
    assert session["pages"][0]["source_index"] == 0


def test_confirm_prunes_to_selection_and_activates(root, image_folder):
    session = create_local_session(root, image_folder, "from_scratch", "diamondback", None)
    confirmed = confirm_session(root, session["id"], [1])
    assert confirmed["state"] == "active"
    assert [p["stem"] for p in confirmed["pages"]] == ["scan-B"]
    reloaded = load_session(root, session["id"])
    assert reloaded["state"] == "active"
    assert reloaded["collection"] == "diamondback"


def test_create_iiif_session_uses_canvas_records(root):
    records = [
        CanvasRecord("https://x/c/0", "Masthead", "https://x/i/0/full/max/0/default.jpg", "https://x/i/0"),
        CanvasRecord("https://x/c/1", "日本語", "https://x/i/1/full/max/0/default.jpg", None),
    ]
    session = create_iiif_session(root, "https://x/m/1", records, "from_scratch", "")
    stems = [p["stem"] for p in session["pages"]]
    assert stems == ["p0000-masthead", "p0001"]
    assert session["pages"][0]["image_url"] == "https://x/i/0/full/max/0/default.jpg"
    assert session["pages"][0]["canvas_id"] == "https://x/c/0"


def test_list_sessions_newest_first(root, image_folder):
    a = create_local_session(root, image_folder, "from_scratch", "", None)
    b = create_local_session(root, image_folder, "corrected", "", image_folder)
    listed = [s["id"] for s in list_sessions(root)]
    assert set(listed) == {a["id"], b["id"]}


def test_detect_draft_format(tmp_path):
    hocr = tmp_path / "a.hocr"
    hocr.write_text('<html><body><div class="ocr_page">x</div></body></html>')
    alto = tmp_path / "b.xml"
    alto.write_text('<?xml version="1.0"?><alto xmlns="x"></alto>')
    page = tmp_path / "c.xml"
    page.write_text('<?xml version="1.0"?><PcGts xmlns="y"></PcGts>')
    txt = tmp_path / "d.txt"
    txt.write_text("plain text")
    assert detect_draft_format(hocr) == "hocr"
    assert detect_draft_format(alto) == "rejected"
    assert detect_draft_format(page) == "rejected"
    assert detect_draft_format(txt) == "txt"


def test_corrected_mode_with_alto_drafts_rejected(root, image_folder, tmp_path):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "scan-A.xml").write_text('<?xml version="1.0"?><alto></alto>')
    with pytest.raises(SessionError):
        create_local_session(root, image_folder, "corrected", "", drafts)


def test_local_session_rejects_colliding_stems(root, tmp_path):
    folder = tmp_path / "dup"
    folder.mkdir()
    (folder / "page1.jpg").write_bytes(b"x")
    (folder / "page1.tif").write_bytes(b"x")
    with pytest.raises(SessionError):
        create_local_session(root, folder, "from_scratch", "", None)


def test_list_sessions_order_is_newest_first(root, image_folder, monkeypatch):
    from dpi_eval import sessions as sessions_mod

    ids = iter(["s-20260101-000000-aaaa", "s-20260102-000000-bbbb"])
    monkeypatch.setattr(sessions_mod, "new_session_id", lambda: next(ids))
    older = create_local_session(root, image_folder, "from_scratch", "", None)
    newer = create_local_session(root, image_folder, "from_scratch", "", None)
    listed = [s["id"] for s in list_sessions(root)]
    assert listed == [newer["id"], older["id"]]
