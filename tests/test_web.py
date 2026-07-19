import io
import json
import socket
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from dpi_eval.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(tmp_path / "runs"))


def _fixture_pair() -> tuple[bytes, bytes]:
    gt = (FIXTURES / "text" / "page_0.gt.txt").read_bytes()
    ocr = (FIXTURES / "text" / "page_0.txt").read_bytes()
    return gt, ocr


def test_form_page_renders(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "webkitdirectory" in resp.text


def test_tracer_one_page_graded_through_web_path(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/runs/run-001"

    results = client.get("/runs/run-001")
    assert results.status_code == 200
    assert "page_0" in results.text

    summary = client.get("/files/run-001/reports/summary.html")
    assert summary.status_code == 200

    saved = json.loads(
        (tmp_path / "runs" / "run-001" / "result.json").read_text(encoding="utf-8")
    )
    assert saved["succeeded"] == ["page_0"]
    assert saved["exit_code"] == 0


def test_gt_folder_without_gt_txt_is_rejected(tmp_path):
    client = make_client(tmp_path)
    _, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.txt", b"not a gt file", "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
    )
    assert resp.status_code == 400
    assert ".gt.txt" in resp.text
    assert not list((tmp_path / "runs").glob("run-*"))  # nothing ran


def test_empty_ocr_selection_is_rejected(tmp_path):
    client = make_client(tmp_path)
    gt, _ = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[("gt_files", ("page_0.gt.txt", gt, "text/plain"))],
    )
    assert resp.status_code == 400
    assert "OCR folder" in resp.text


def test_basename_collision_is_rejected_naming_both_paths(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("ocr_files", ("issue-1/page_0.txt", ocr, "text/plain")),
            ("ocr_files", ("issue-2/page_0.txt", ocr, "text/plain")),
        ],
    )
    assert resp.status_code == 400
    assert "issue-1/page_0.txt" in resp.text
    assert "issue-2/page_0.txt" in resp.text
    assert not list((tmp_path / "runs").glob("run-*"))


def test_collision_message_names_both_relative_paths(tmp_path):
    """F8: the collision detail must carry the RELATIVE PATHS of the
    colliding files, not the same bare basename twice — otherwise a
    student can't tell which two files to rename."""
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("ocr_files", ("a/page_0.txt", ocr, "text/plain")),
            ("ocr_files", ("b/page_0.txt", ocr, "text/plain")),
        ],
    )
    assert resp.status_code == 400
    assert "a/page_0.txt" in resp.text
    assert "b/page_0.txt" in resp.text


def test_hidden_files_are_ignored_not_collided(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("gt_files", (".DS_Store", b"junk", "application/octet-stream")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
            ("ocr_files", ("a/.DS_Store", b"junk", "application/octet-stream")),
            ("ocr_files", ("b/.DS_Store", b"junk", "application/octet-stream")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    run_dir = tmp_path / "runs" / "run-001"
    assert not (run_dir / "gt" / ".DS_Store").exists()
    assert not (run_dir / "ocr" / ".DS_Store").exists()


def test_partial_failure_shows_banner_and_names_pages(tmp_path):
    """Display-contract test: render a run whose engine verdict recorded
    one failed and one skipped page. The run dir is written directly
    because no upload payload can deterministically fail dinglehopper
    0.11.0 — it falls back to plain-text grading for unrecognized XML
    (verified 2026-07-17). Engine-level failure behavior is covered in
    tests/test_batch.py via the directory trick, which uploads cannot
    reproduce."""
    client = make_client(tmp_path)
    run_dir = tmp_path / "runs" / "run-001"
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "succeeded": ["page_0"],
                "failed": ["page_1"],
                "missing": ["page_9"],
                "exit_code": 1,
            }
        ),
        encoding="utf-8",
    )
    page = client.get("/runs/run-001").text
    assert "Too many pages failed" in page
    assert "page_1" in page  # failed, named
    assert "could not read" in page  # failure reason in plain language
    assert "page_9" in page  # missing OCR, named
    assert "no file with the same name" in page  # skip reason
    assert '/runs/run-001/reports/page_0' in page
    assert '/runs/run-001/reports/summary' in page


def test_zero_pair_upload_is_rejected_before_grading(tmp_path):
    """F14: when discover_pairs would find zero pairs, /grade 400s with
    the specific unmatched names before any grading happens, instead of
    redirecting into a zero-success results banner."""
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_9.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "page_9" in resp.text  # GT with no matching OCR
    assert "page_0" in resp.text  # OCR with no matching GT


def test_partial_pairing_mismatch_still_grades_matched_pages(tmp_path):
    """F14's flip side: a partial mismatch (some names pair, some don't)
    must NOT trip the zero-pair pre-check — the existing grade-and-report
    behavior (missing pages named on the results page) still applies."""
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("gt_files", ("page_1.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    page = client.get(resp.headers["location"]).text
    assert "page_0" in page


def test_results_show_scores_wer_first_with_caveat(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    page = client.get(resp.headers["location"]).text
    assert "Word error rate" in page
    assert "Raw character error rate" in page
    # WER leads: its first mention precedes CER's first mention
    assert page.index("Word error rate") < page.index("Raw character error rate")
    assert "%" in page
    assert "upper bound" in page  # findings §7 caveat
    assert "left column is the ground truth" in page
    assert "Based on 1 graded page" in page
    assert '<th scope="col">' in page
    assert '<th scope="row">' in page
    assert "<main>" in page


def test_form_page_carries_instructions_and_shutdown_note(tmp_path):
    client = make_client(tmp_path)
    text = client.get("/").text
    assert ".gt.txt" in text
    assert "Close this window" in text
    assert "never leave this computer" in text
    # Task 7.1: the served form is the progressive variant (F6/F17/F9),
    # and the terminal sentence stays gated for the desktop hide (F3).
    assert "Choose two folders, then grade." in text
    assert "1. Ground-truth folder" in text
    assert ">Grade this batch</button>" in text
    assert 'id="footer-terminal-note"' in text


def test_zip_download_contains_reports(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    resp = client.get("/runs/run-001/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(archive.namelist())
    assert {"summary.json", "summary.html", "page_0.json", "page_0.html"} <= names


def test_zip_download_unknown_run_is_404(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/runs/run-999/download").status_code == 404
    assert client.get("/runs/../etc/download").status_code == 404


def test_zip_download_without_reports_is_404(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    # GT stem matches nothing → zero pairs → engine never creates reports/
    client.post(
        "/grade",
        files=[
            ("gt_files", ("page_9.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    assert client.get("/runs/run-001/download").status_code == 404


def test_wrapped_report_serves_generated_html_in_shell(tmp_path):
    client = make_client(tmp_path)
    run = tmp_path / "runs" / "run-001"
    (run / "reports").mkdir(parents=True)
    (run / "result.json").write_text(
        '{"succeeded": ["page_0"], "failed": [], "missing": [], "exit_code": 0}'
    )
    (run / "reports" / "page_0.html").write_text(
        "<html><body><table class='diff'>DIFFCONTENT</table></body></html>"
    )
    resp = client.get("/runs/run-001/reports/page_0")
    assert resp.status_code == 200
    assert "DIFFCONTENT" in resp.text  # generated content survives
    assert 'href="/runs/run-001"' in resp.text  # back-link in our shell
    assert "--color-ink" in resp.text  # our stylesheet wraps it


def test_wrapped_report_transforms_real_fixture_and_leaves_it_on_disk(tmp_path):
    # F20: serve-time transform, exercised against a real generated
    # report (not fabricated HTML) — proves the disk file is untouched.
    client = make_client(tmp_path)
    run = tmp_path / "runs" / "run-001"
    (run / "reports").mkdir(parents=True)
    (run / "result.json").write_text(
        '{"succeeded": ["page_0"], "failed": [], "missing": [], "exit_code": 0}'
    )
    fixture_html = (FIXTURES / "reports" / "page_0.html").read_text(
        encoding="utf-8"
    )
    report_path = run / "reports" / "page_0.html"
    report_path.write_text(fixture_html, encoding="utf-8")

    resp = client.get("/runs/run-001/reports/page_0")
    assert resp.status_code == 200
    assert "<script" not in resp.text
    assert "jquery" not in resp.text
    assert "Character error rate (CER): 3.5%" in resp.text
    assert "Word error rate (WER): 12.5%" in resp.text
    assert "<p>CER: 0.0345</p>" not in resp.text
    assert "Ground truth" in resp.text
    assert ">OCR<" in resp.text
    assert "CER counts character-level differences" in resp.text
    assert 'href="/runs/run-001"' in resp.text  # shell back-link survives

    # The report file on disk is never modified — transform is in-memory
    # only; the zip download still ships the raw original.
    assert report_path.read_text(encoding="utf-8") == fixture_html


def test_wrapped_report_rejects_bad_names(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/runs/run-001/reports/../secret").status_code in (400, 404)
    assert client.get("/runs/nope/reports/page_0").status_code == 404


def test_pick_port_falls_back_when_preferred_taken():
    from dpi_eval.web import _pick_port

    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        busy = blocker.getsockname()[1]
        chosen = _pick_port(preferred=busy)
        assert chosen != busy


def test_pick_port_prefers_free_port():
    from dpi_eval.web import _pick_port

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    assert _pick_port(preferred=free) == free


def test_main_no_browser_skips_browser_timer(tmp_path, monkeypatch):
    import dpi_eval.web as web

    monkeypatch.setattr(web.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(web.uvicorn, "run", lambda *a, **k: None)

    def forbidden_timer(*a, **k):
        raise AssertionError("browser timer created despite --no-browser")

    monkeypatch.setattr(web.threading, "Timer", forbidden_timer)
    assert web.main(["--no-browser"]) == 0


def test_main_default_still_opens_browser(tmp_path, monkeypatch):
    import dpi_eval.web as web

    created = {}

    class FakeTimer:
        def __init__(self, delay, fn, args=None):
            created["timer"] = True

        def start(self):
            created["started"] = True

    monkeypatch.setattr(web.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(web.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(web.threading, "Timer", FakeTimer)
    assert web.main([]) == 0
    assert created == {"timer": True, "started": True}


def test_next_run_dir_retries_on_collision(tmp_path, monkeypatch):
    from dpi_eval.web import _next_run_dir

    base = tmp_path / "runs"
    base.mkdir()
    real_mkdir = Path.mkdir
    state = {"stolen": False}

    def racing_mkdir(self, *args, **kwargs):
        if not state["stolen"] and self.name == "run-001":
            state["stolen"] = True
            real_mkdir(self, *args, **kwargs)  # a rival grader claims run-001
            raise FileExistsError(str(self))
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", racing_mkdir)
    run_dir = _next_run_dir(base)
    assert run_dir.name == "run-002"
    assert run_dir.is_dir()
