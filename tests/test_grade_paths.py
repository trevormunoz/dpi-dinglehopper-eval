"""Tests for POST /grade-paths (spec amendment 2026-07-18) and the
app-wide Host-header guard.

Pinned cross-component contracts (docs/superpowers/plans/2026-07-17-dpi-eval-desktop.md,
Task 9b): JSON body {"gt_dir", "ocr_dir"}, header X-DPI-Eval-Token must
equal env var DPI_EVAL_TOKEN (absent env => always 403), 200 {"run_url":
"/runs/run-NNN"}, validation/read failures 400 {"error": str}, Host
guard rejects any Host not matching the bound host:port.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dpi_eval.pairing import discover_pairs
from dpi_eval.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def make_client(tmp_path, **kwargs) -> TestClient:
    return TestClient(create_app(tmp_path / "runs", **kwargs))


def _fixture_dirs(tmp_path):
    """Copy the text fixture pair into a fresh gt/ and ocr/ tree."""
    gt_dir = tmp_path / "gt_src"
    ocr_dir = tmp_path / "ocr_src"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    (gt_dir / "page_0.gt.txt").write_bytes(
        (FIXTURES / "text" / "page_0.gt.txt").read_bytes()
    )
    (ocr_dir / "page_0.txt").write_bytes(
        (FIXTURES / "text" / "page_0.txt").read_bytes()
    )
    return gt_dir, ocr_dir


def test_grade_paths_403_when_token_env_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("DPI_EVAL_TOKEN", raising=False)
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "anything"},
    )
    assert resp.status_code == 403


def test_grade_paths_403_on_wrong_token(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "wrong-token"},
    )
    assert resp.status_code == 403


def test_grade_paths_403_when_token_header_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    resp = client.post(
        "/grade-paths", json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)}
    )
    assert resp.status_code == 403


def test_grade_paths_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_url"] == "/runs/run-001"

    results = client.get(body["run_url"])
    assert results.status_code == 200
    assert "page_0" in results.text


def test_grade_paths_nonexistent_dir_is_400(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    _, ocr_dir = _fixture_dirs(tmp_path)
    missing = tmp_path / "does-not-exist"
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(missing), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 400
    assert str(missing) in resp.json()["error"]
    assert not list((tmp_path / "runs").glob("run-*"))


def test_grade_paths_file_instead_of_dir_is_400(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    _, ocr_dir = _fixture_dirs(tmp_path)
    a_file = tmp_path / "not-a-dir.txt"
    a_file.write_text("nope")
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(a_file), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 400
    assert str(a_file) in resp.json()["error"]


def test_grade_paths_dotfiles_are_dropped_not_collided(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    (gt_dir / ".DS_Store").write_bytes(b"junk")
    sub = ocr_dir / "sub"
    sub.mkdir()
    (sub / ".DS_Store").write_bytes(b"junk")
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 200
    run_dir = tmp_path / "runs" / "run-001"
    assert not (run_dir / "gt" / ".DS_Store").exists()
    assert not (run_dir / "ocr" / ".DS_Store").exists()
    assert not (run_dir / "ocr" / "sub").exists()


def test_grade_paths_collision_through_subdirs_is_400(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    issue1 = ocr_dir / "issue-1"
    issue2 = ocr_dir / "issue-2"
    issue1.mkdir()
    issue2.mkdir()
    (issue1 / "page_0.txt").write_bytes(b"a")
    (issue2 / "page_0.txt").write_bytes(b"b")
    # remove the top-level ocr file so the only OCR files are the collision pair
    (ocr_dir / "page_0.txt").unlink()
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "issue-1" in body["error"]
    assert "issue-2" in body["error"]
    assert not list((tmp_path / "runs").glob("run-*"))


def test_grade_paths_no_gt_txt_is_400_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    (gt_dir / "page_0.gt.txt").rename(gt_dir / "page_0.txt")
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 400
    assert ".gt.txt" in resp.json()["error"]


def test_grade_paths_empty_ocr_is_400_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    (ocr_dir / "page_0.txt").unlink()
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 400
    assert "OCR folder" in resp.json()["error"]


def test_grade_paths_read_error_mid_enumeration_is_400_no_partial_grade(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    unreadable = ocr_dir / "unreadable.txt"
    unreadable.write_bytes(b"secret")
    unreadable.chmod(0o000)
    try:
        if os.access(unreadable, os.R_OK):
            pytest.skip("running as root or on a platform that ignores chmod 000")
        resp = client.post(
            "/grade-paths",
            json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
            headers={"X-DPI-Eval-Token": "correct-token"},
        )
        assert resp.status_code == 400
        assert not list((tmp_path / "runs").glob("run-*"))
    finally:
        unreadable.chmod(0o644)


def test_grade_paths_zero_pair_is_400_naming_unmatched_files(tmp_path, monkeypatch):
    """F14: the engine's own pairing.py matcher is used as the test
    oracle here — discover_pairs on these two dirs must itself report
    zero pairs, or this test would be asserting a fiction."""
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    (gt_dir / "page_0.gt.txt").rename(gt_dir / "page_1.gt.txt")
    (ocr_dir / "page_0.txt").rename(ocr_dir / "page_2.txt")

    pairs, missing = discover_pairs(gt_dir, ocr_dir)
    assert pairs == []
    assert missing == ["page_1"]

    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 400
    error = resp.json()["error"]
    assert "page_1" in error  # GT with no matching OCR
    assert "page_2" in error  # OCR with no matching GT


def test_grade_paths_partial_pairing_mismatch_still_grades(tmp_path, monkeypatch):
    """F14's flip side over JSON: a partial mismatch must not trip the
    zero-pair pre-check — existing grade-and-report behavior applies."""
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    (gt_dir / "page_1.gt.txt").write_bytes(
        (FIXTURES / "text" / "page_0.gt.txt").read_bytes()
    )
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 200
    results = client.get(resp.json()["run_url"])
    assert "page_0" in results.text


def test_grade_paths_collision_message_names_relative_paths(tmp_path, monkeypatch):
    """F8 over JSON: collision details must name the relative paths, not
    the same bare basename twice."""
    monkeypatch.setenv("DPI_EVAL_TOKEN", "correct-token")
    client = make_client(tmp_path)
    gt_dir, ocr_dir = _fixture_dirs(tmp_path)
    a = ocr_dir / "a"
    b = ocr_dir / "b"
    a.mkdir()
    b.mkdir()
    (a / "page_0.txt").write_bytes(b"a")
    (b / "page_0.txt").write_bytes(b"b")
    (ocr_dir / "page_0.txt").unlink()
    resp = client.post(
        "/grade-paths",
        json={"gt_dir": str(gt_dir), "ocr_dir": str(ocr_dir)},
        headers={"X-DPI-Eval-Token": "correct-token"},
    )
    assert resp.status_code == 400
    error = resp.json()["error"]
    assert "a/page_0.txt" in error
    assert "b/page_0.txt" in error


def test_rglob_symlink_semantics_files_through_dirs_not_followed(tmp_path):
    """Pins the rglob behavior _enumerate_dir relies on: symlinked files
    are read through; symlinked directories are not descended into."""
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    (root / "sub").mkdir(parents=True)
    outside.mkdir()
    (root / "sub" / "real.txt").write_text("real")
    (outside / "hidden.txt").write_text("should not appear")
    (root / "linked_dir").symlink_to(outside, target_is_directory=True)
    (root / "linked_file.txt").symlink_to(root / "sub" / "real.txt")

    entries = {str(p.relative_to(root)) for p in root.rglob("*") if not p.is_dir()}
    assert "sub/real.txt" in entries
    assert "linked_file.txt" in entries  # symlinked file read through
    assert "linked_dir/hidden.txt" not in entries  # symlinked dir not followed


def test_wrong_host_header_is_rejected(tmp_path):
    client = make_client(tmp_path, expected_hosts={"127.0.0.1:9"})
    resp = client.get("/")
    assert resp.status_code == 403


def test_matching_host_header_is_accepted(tmp_path):
    # TestClient's default Host header is "testserver" with no port.
    client = make_client(tmp_path, expected_hosts={"testserver"})
    resp = client.get("/")
    assert resp.status_code == 200


def test_no_expected_hosts_means_no_host_check(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
