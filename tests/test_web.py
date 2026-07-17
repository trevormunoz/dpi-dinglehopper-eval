import json
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
    assert '/files/run-001/reports/page_0.html' in page
    assert '/files/run-001/reports/summary.html' in page


def test_nothing_graded_shows_banner(tmp_path):
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
    assert resp.status_code == 303
    page = client.get(resp.headers["location"]).text
    assert "Nothing was graded" in page


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
