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
