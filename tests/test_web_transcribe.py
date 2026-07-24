from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dpi_eval.web import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "tok")
    return TestClient(create_app(tmp_path)), tmp_path


@pytest.fixture
def image_folder(tmp_path):
    folder = tmp_path / "masters"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"x")
    (folder / "b.png").write_bytes(b"x")
    return folder


def _create(client, folder, token="tok"):
    return client.post("/transcribe/sessions", data={
        "token": token, "source_type": "local", "folder": str(folder),
        "mode": "from_scratch", "collection": "test-coll"})


def test_transcribe_home_lists_sessions(client):
    c, _ = client
    response = c.get("/transcribe")
    assert response.status_code == 200
    assert "Transcribe" in response.text


def test_create_requires_token(client, image_folder):
    c, _ = client
    assert _create(c, image_folder, token="wrong").status_code == 403


def test_create_renders_selection_then_confirm_activates(client, image_folder):
    c, _ = client
    response = _create(c, image_folder)
    assert response.status_code == 200
    assert 'name="pages"' in response.text  # selection checkboxes
    sid = response.text.split('data-session-id="', 1)[1].split('"', 1)[0]
    confirm = c.post(f"/transcribe/sessions/{sid}/confirm",
                     data={"token": "tok", "pages": ["0", "1"]},
                     follow_redirects=False)
    assert confirm.status_code == 303
    assert confirm.headers["location"] == f"/transcribe/sessions/{sid}"
    summary = c.get(f"/transcribe/sessions/{sid}")
    assert "Page" in summary.text and "a" in summary.text


def test_create_rejects_bad_folder(client, tmp_path):
    c, _ = client
    response = _create(c, tmp_path / "nope")
    assert response.status_code == 400
