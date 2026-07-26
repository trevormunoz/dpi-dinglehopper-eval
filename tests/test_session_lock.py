"""Direct tests for session_lock (PAR R2-S5).

The lock was added to fix a data-loss finding and had no direct tests: a
grep for `session_lock` across tests/ returned nothing, so re-entrancy,
exception safety, contention and the stale break were all unverified.

Threads, not sleeps: every test drives the interleaving with Events and a
shortened LOCK_TIMEOUT so the outcome is a decision, not a timing lottery.
"""

import os
import threading
import time

import pytest

from dpi_eval import sessions

SID = "s-20260726-120000-abcd"


@pytest.fixture
def root(tmp_path):
    return sessions.transcriptions_root(tmp_path)


@pytest.fixture
def lock_path(root):
    return sessions.session_dir(root, SID) / "session.lock"


@pytest.fixture(autouse=True)
def fast_timeout(monkeypatch):
    """A contention probe should decide in milliseconds. The production
    10s wait is what the student experiences, not what the test asserts."""
    monkeypatch.setattr(sessions, "LOCK_TIMEOUT", 0.2)


def _probe(root, session_id, timeout=3.0):
    """Try to take the lock from a *fresh* thread and report what happened.

    The lock is re-entrant per thread, so a probe on the thread under test
    would always succeed and prove nothing.
    """
    outcome = []

    def run():
        try:
            with sessions.session_lock(root, session_id):
                outcome.append("acquired")
        except sessions.SessionError as exc:
            outcome.append(f"denied: {exc.message}")

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():  # pragma: no cover - would mean the lock hangs
        return "hung"
    return outcome[0]


def test_reentrant_within_one_thread_and_released_once(root, lock_path):
    """A mutator that calls another locked helper must not self-deadlock,
    and the inner exit must not release the outer holder's lock."""
    with sessions.session_lock(root, SID):
        outer = lock_path.read_bytes()
        with sessions.session_lock(root, SID):
            assert lock_path.exists()
        assert lock_path.exists()
        assert lock_path.read_bytes() == outer
    assert not lock_path.exists()


def test_lock_is_released_when_the_body_raises(root, lock_path):
    with pytest.raises(ZeroDivisionError):
        with sessions.session_lock(root, SID):
            1 / 0
    assert not lock_path.exists()
    assert _probe(root, SID) == "acquired"


def test_a_second_thread_is_denied_while_the_lock_is_held(root):
    """Contention is answered with the friendly SessionError, not a
    silent second entry into the critical section."""
    with sessions.session_lock(root, SID):
        outcome = _probe(root, SID)
    assert outcome.startswith("denied: ")
    assert "still in progress" in outcome


def test_a_foreign_lock_left_by_a_crash_is_broken(root, lock_path):
    """Crash recovery: a lock file written by some other process, older
    than LOCK_STALE_AFTER, must not wedge the session forever."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("99999-deadbeef stale", encoding="utf-8")
    old = time.time() - (sessions.LOCK_STALE_AFTER + 60)
    os.utime(lock_path, (old, old))
    assert _probe(root, SID) == "acquired"


def test_this_process_lock_is_never_broken_however_old_it_looks(root, lock_path):
    """R2-S5. A waiter that breaks a live holder's lock cannot tell that
    holder it lost the lock, so both end up in the critical section — the
    lost update the lock exists to prevent. Staleness is judged from
    st_mtime (wall clock) while the wait deadline is monotonic, so a
    laptop sleep or an NTP step is enough to make a millisecond-old lock
    look a minute stale; os.utime stands in for that jump.
    """
    holding = threading.Event()
    finish = threading.Event()
    outcome = []

    def holder():
        try:
            with sessions.session_lock(root, SID):
                old = time.time() - (sessions.LOCK_STALE_AFTER + 60)
                os.utime(lock_path, (old, old))
                holding.set()
                finish.wait(5)
            outcome.append("clean")
        except sessions.SessionError as exc:
            outcome.append(f"lost: {exc.message}")

    thread = threading.Thread(target=holder)
    thread.start()
    assert holding.wait(5)
    probe = _probe(root, SID)
    finish.set()
    thread.join(5)
    assert probe.startswith("denied: "), "a live holder's lock was broken"
    assert outcome == ["clean"], "the holder should still own its lock"


def test_release_leaves_a_lock_file_it_no_longer_owns(root, lock_path):
    """R2-S5. If a waiter does break in, the original holder's exit used
    to unlink the *breaker's* lock file, admitting a third caller
    mid-write. The holder must verify it still owns the file, and say so
    when it does not — a save that raced is not a save we report as fine.
    """
    with pytest.raises(sessions.SessionError) as excinfo:
        with sessions.session_lock(root, SID):
            lock_path.unlink()
            lock_path.write_text("99999-deadbeef breaker", encoding="utf-8")
    assert lock_path.exists(), "released someone else's lock file"
    assert lock_path.read_text(encoding="utf-8").endswith("breaker")
    assert "at the same time" in excinfo.value.message


def test_a_body_error_is_not_masked_by_a_lost_lock(root, lock_path):
    """Precedence: the student's real error (empty transcription, bad
    override) must reach them, not a lock-bookkeeping message layered
    over it."""
    with pytest.raises(ZeroDivisionError):
        with sessions.session_lock(root, SID):
            lock_path.unlink()
            lock_path.write_text("99999-deadbeef breaker", encoding="utf-8")
            1 / 0
