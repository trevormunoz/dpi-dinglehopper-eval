import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from dpi_eval.web import create_app


@pytest.fixture
def session_with_gt(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "tok")
    folder = tmp_path / "masters"
    folder.mkdir()
    Image.new("RGB", (10, 10)).save(folder / "page_0.png")
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "page_0.txt").write_text("hello world\n")
    client = TestClient(create_app(tmp_path))
    response = client.post("/transcribe/sessions", data={
        "token": "tok", "source_type": "local", "folder": str(folder),
        "mode": "corrected", "collection": "coll",
        "draft_folder": str(drafts)})
    sid = response.text.split('data-session-id="', 1)[1].split('"', 1)[0]
    client.post(f"/transcribe/sessions/{sid}/confirm",
                data={"token": "tok", "pages": ["0"]})
    client.post(f"/transcribe/sessions/{sid}/pages/0", data={
        "token": "tok", "action": "save", "text": "hello world",
        "elapsed": "1", "active": "1", "nonce": "n"})
    return client, sid


def test_grade_preview_upload_then_confirm_redirects_to_run(session_with_gt):
    client, sid = session_with_gt
    preview = client.post(
        f"/transcribe/sessions/{sid}/grade/preview",
        data={"token": "tok", "ocr_folder": ""},
        files=[("ocr_files", ("page_0.txt", b"hello world\n"))])
    assert preview.status_code == 200
    assert "page_0.txt" in preview.text  # alignment table shows the match
    confirm = client.post(f"/transcribe/sessions/{sid}/grade/confirm",
                          data={"token": "tok"}, follow_redirects=False)
    assert confirm.status_code == 303
    assert confirm.headers["location"].startswith("/runs/run-")
    results = client.get(confirm.headers["location"])
    assert results.status_code == 200


def test_clone_creates_other_arm_with_same_selection(session_with_gt):
    client, sid = session_with_gt
    response = client.post(f"/transcribe/sessions/{sid}/clone", data={"token": "tok"},
                           follow_redirects=False)
    assert response.status_code == 303
    new_sid = response.headers["location"].rsplit("/", 1)[-1]
    page = client.get(f"/transcribe/sessions/{new_sid}")
    assert "from_scratch" in page.text  # opposite arm


def test_export_downloads_zip(session_with_gt):
    client, sid = session_with_gt
    response = client.post(f"/transcribe/sessions/{sid}/export", data={"token": "tok"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert any(name.endswith("transcriptions.json") for name in zf.namelist())
