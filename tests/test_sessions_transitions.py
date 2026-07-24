import json
from pathlib import Path

import pytest

from dpi_eval.sessions import (
    SessionError, create_local_session, confirm_session, gt_path,
    load_session, mark_no_text, page_by_index, reconcile, resolve_attention,
    save_page, session_dir, set_flag, transcriptions_root,
)


@pytest.fixture
def active_session(tmp_path):
    folder = tmp_path / "masters"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        (folder / name).write_bytes(b"x")
    root = transcriptions_root(tmp_path)
    session = create_local_session(root, folder, "from_scratch", "", None)
    confirm_session(root, session["id"], [0, 1])
    return root, session["id"]


def test_save_page_writes_normalized_gt_and_accumulates_timing(active_session):
    root, sid = active_session
    session, changes = save_page(root, sid, 0, "Line one   \nLine two",
                                 elapsed=30, active=20, nonce="n1")
    page = page_by_index(session, 0)
    assert page["status"] == "saved"
    assert changes == 2  # trailing spaces + missing final newline
    assert gt_path(root, session, page).read_text(encoding="utf-8") == "Line one\nLine two\n"
    session, _ = save_page(root, sid, 0, "Line one\nLine two\n",
                           elapsed=15, active=10, nonce="n2")
    page = page_by_index(session, 0)
    assert page["seconds_elapsed"] == 45   # accumulated, never replaced
    assert page["seconds_active"] == 30


def test_retried_nonce_does_not_double_count(active_session):
    root, sid = active_session
    save_page(root, sid, 0, "x\n", elapsed=30, active=20, nonce="n1")
    session, _ = save_page(root, sid, 0, "x\n", elapsed=30, active=20, nonce="n1")
    assert page_by_index(session, 0)["seconds_elapsed"] == 30


def test_no_text_requires_reason_and_deletes_gt(active_session):
    root, sid = active_session
    session, _ = save_page(root, sid, 0, "typed then retracted\n",
                           elapsed=5, active=5, nonce="n1")
    path = gt_path(root, session, page_by_index(session, 0))
    assert path.exists()
    session = mark_no_text(root, sid, 0, "image_only")
    page = page_by_index(session, 0)
    assert page["status"] == "no_text"
    assert page["no_text_reason"] == "image_only"
    assert not path.exists()  # stale GT never survives a retraction
    with pytest.raises(SessionError):
        mark_no_text(root, sid, 1, "because")


def test_flag_is_orthogonal_to_status(active_session):
    root, sid = active_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="n")
    session = set_flag(root, sid, 0, True, "unsure about ligature")
    page = page_by_index(session, 0)
    assert page["status"] == "saved" and page["flagged"] is True


def test_reconcile_finds_orphan_and_missing_gt(active_session):
    root, sid = active_session
    session, _ = save_page(root, sid, 0, "kept\n", elapsed=1, active=1, nonce="n")
    # Crash sim 1: GT written for a page whose record still says pending.
    orphan = session_dir(root, sid) / "gt" / "b.gt.txt"
    orphan.write_text("orphan\n", encoding="utf-8")
    # Crash sim 2: saved page whose GT file vanished.
    gt_path(root, session, page_by_index(session, 0)).unlink()
    problems = {(p["stem"], p["problem"]) for p in reconcile(root, load_session(root, sid))}
    assert problems == {("b", "orphan_gt"), ("a", "missing_gt")}


def test_resolve_attention_adopt_and_discard(active_session):
    root, sid = active_session
    orphan = session_dir(root, sid) / "gt" / "b.gt.txt"
    orphan.write_text("orphan\n", encoding="utf-8")
    session = resolve_attention(root, sid, 1, "adopt")
    assert page_by_index(session, 1)["status"] == "saved"
    session = resolve_attention(root, sid, 1, "discard")
    assert page_by_index(session, 1)["status"] == "pending"
    assert not orphan.exists()


def test_version_mismatch_makes_session_read_only(active_session):
    root, sid = active_session
    session = load_session(root, sid)
    session["conventions_version"] = "0-old"
    from dpi_eval.sessions import save_session
    save_session(root, session)
    with pytest.raises(SessionError):
        save_page(root, sid, 0, "x\n", elapsed=1, active=1, nonce="n")
