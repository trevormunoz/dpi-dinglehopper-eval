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


def test_concurrent_mutations_do_not_lose_an_update(active_session):
    """PAR S15. Every mutator did load -> mutate whole dict -> save, and
    the routes are `def`, so FastAPI runs them in a threadpool: two real
    in-flight requests interleaved and the loser's whole record —
    including `seconds_elapsed`/`seconds_active`, the pilot's actual
    measurement — was silently discarded.

    The interleave is forced from the reader side: a hook fires inside
    the saving thread right after it loads and waits for the main thread
    to finish a `set_flag` on the other page. Unlocked, the waiter always
    resumes and clobbers the flag. Locked, the main thread cannot even
    load until the save completes, so the hook's wait times out (that is
    the point: the interleave becomes unreachable) and both writes
    survive. The 2s bound is generous relative to two local JSON writes,
    so the pre-fix failure is deterministic; the post-fix pass costs
    2 seconds of waiting.
    """
    import threading
    from dpi_eval import sessions as sessions_mod

    loaded = threading.Event()
    real_load = sessions_mod.load_session
    saver = threading.current_thread()
    errors: list[BaseException] = []

    def hooked_load(root_, sid_):
        session = real_load(root_, sid_)
        if threading.current_thread() is saver and not loaded.is_set():
            loaded.set()
            other_done.wait(timeout=2.0)
        return session

    other_done = threading.Event()
    root, sid = active_session

    def do_save():
        nonlocal saver
        saver = threading.current_thread()
        try:
            save_page(root, sid, 0, "typed\n", elapsed=30, active=20, nonce="n1")
        except BaseException as exc:  # surfaced in the main thread below
            errors.append(exc)
        finally:
            loaded.set()

    thread = threading.Thread(target=do_save)
    import unittest.mock as mock
    with mock.patch.object(sessions_mod, "load_session", hooked_load):
        thread.start()
        assert loaded.wait(timeout=5.0), "saving thread never loaded"
        set_flag(root, sid, 1, True, "unsure about ligature")
        other_done.set()
        thread.join(timeout=15.0)
    assert not thread.is_alive()
    assert not errors, errors

    final = load_session(root, sid)
    assert page_by_index(final, 0)["seconds_elapsed"] == 30, "timing was lost"
    assert page_by_index(final, 1)["flagged"] is True, "flag was lost"


def test_version_mismatch_makes_session_read_only(active_session):
    root, sid = active_session
    session = load_session(root, sid)
    session["conventions_version"] = "0-old"
    from dpi_eval.sessions import save_session
    save_session(root, session)
    with pytest.raises(SessionError):
        save_page(root, sid, 0, "x\n", elapsed=1, active=1, nonce="n")
