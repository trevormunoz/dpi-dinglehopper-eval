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


def test_rejected_override_keeps_the_staging_its_error_tells_you_to_fix(
        session_with_gt, tmp_path):
    """R2-S3: `clear_staging` sat in a bare `finally`, so every error path out
    of `stage_for_grade` deleted the staged OCR upload. The 400 says the
    override "is not a plain filename from the staged OCR upload" — and the
    upload it names had just been erased, so retrying said "Upload or pick the
    OCR folder first (preview step)." and the student had to re-pick the whole
    folder. sessions.py:450-453 states the rule for the same shape of check:
    reject before destroying staging that was already there.

    Staging is cleared on the success path only, once the graded copies are
    safely in the run directory."""
    from dpi_eval import sessions as sess

    client, sid = session_with_gt
    preview = client.post(
        f"/transcribe/sessions/{sid}/grade/preview",
        data={"token": "tok", "ocr_folder": ""},
        files=[("ocr_files", ("page_0.txt", b"hello world\n"))])
    assert preview.status_code == 200
    staging = sess.session_dir(sess.transcriptions_root(tmp_path), sid) / "staging"
    assert (staging / "ocr" / "page_0.txt").is_file()

    rejected = client.post(f"/transcribe/sessions/{sid}/grade/confirm",
                           data={"token": "tok",
                                 "override_page_0": "../../secret.txt"})
    assert rejected.status_code == 400
    assert "not a plain filename" in rejected.text
    # The upload the error message points at survives, so the fix is one form
    # field away rather than a whole re-pick.
    assert (staging / "ocr" / "page_0.txt").is_file()

    retry = client.post(f"/transcribe/sessions/{sid}/grade/confirm",
                        data={"token": "tok"}, follow_redirects=False)
    assert retry.status_code == 303, retry.text
    assert retry.headers["location"].startswith("/runs/run-")
    # Success is the moment staging stops being needed: the graded gt/ocr
    # copies now live in the run directory.
    assert not staging.exists()


def test_clone_creates_other_arm_with_same_selection(session_with_gt):
    client, sid = session_with_gt
    response = client.post(f"/transcribe/sessions/{sid}/clone", data={"token": "tok"},
                           follow_redirects=False)
    assert response.status_code == 303
    new_sid = response.headers["location"].rsplit("/", 1)[-1]
    page = client.get(f"/transcribe/sessions/{new_sid}")
    assert "from_scratch" in page.text  # opposite arm


def _from_scratch_session(tmp_path, client, name="masters2"):
    folder = tmp_path / name
    folder.mkdir()
    Image.new("RGB", (10, 10)).save(folder / "page_0.png")
    response = client.post("/transcribe/sessions", data={
        "token": "tok", "source_type": "local", "folder": str(folder),
        "mode": "from_scratch", "collection": "coll"})
    sid = response.text.split('data-session-id="', 1)[1].split('"', 1)[0]
    client.post(f"/transcribe/sessions/{sid}/confirm",
                data={"token": "tok", "pages": ["0"]})
    return sid


def test_clone_into_corrected_arm_with_a_chosen_draft_folder(session_with_gt, tmp_path):
    """S6: the pilot compares typing from scratch against correcting a draft,
    so the clone button has to work in both directions. from_scratch →
    corrected always 400'd 'Correction mode needs a draft folder.' because no
    draft folder was ever supplied — a from-scratch session has none."""
    client, _ = session_with_gt
    sid = _from_scratch_session(tmp_path, client)
    drafts = tmp_path / "clone-drafts"
    drafts.mkdir()
    (drafts / "page_0.txt").write_text("machine draft\n")

    response = client.post(f"/transcribe/sessions/{sid}/clone",
                           data={"token": "tok", "draft_folder": str(drafts)},
                           follow_redirects=False)
    assert response.status_code == 303
    new_sid = response.headers["location"].rsplit("/", 1)[-1]
    page = client.get(f"/transcribe/sessions/{new_sid}")
    assert "mode: corrected" in page.text
    # The drafts really are wired up: the editor shows the draft text.
    editor = client.get(f"/transcribe/sessions/{new_sid}/pages/0")
    assert "machine draft" in editor.text


def test_clone_into_corrected_arm_without_a_draft_folder_explains_why(
        session_with_gt, tmp_path):
    client, _ = session_with_gt
    sid = _from_scratch_session(tmp_path, client, name="masters3")
    response = client.post(f"/transcribe/sessions/{sid}/clone",
                           data={"token": "tok"})
    assert response.status_code == 400
    assert "draft" in response.text.lower()


def test_grade_preview_rejects_folder_and_uploads_together(session_with_gt, tmp_path):
    """S4: ocr_folder silently won and the uploads were discarded, with no
    way for the student to see which input was used."""
    client, sid = session_with_gt
    folder = tmp_path / "ocr-from-folder"
    folder.mkdir()
    (folder / "page_0.txt").write_text("from the folder\n")
    response = client.post(
        f"/transcribe/sessions/{sid}/grade/preview",
        data={"token": "tok", "ocr_folder": str(folder)},
        files=[("ocr_files", ("page_0.txt", b"from the upload\n"))])
    assert response.status_code == 400
    assert "folder" in response.text and "upload" in response.text


def test_grade_preview_unreadable_file_is_a_friendly_error(session_with_gt, tmp_path):
    """S20: _enumerate_dir ran outside the try, so one unreadable file
    anywhere under the picked folder produced a 500 traceback."""
    client, sid = session_with_gt
    folder = tmp_path / "ocr-unreadable"
    folder.mkdir()
    blocked = folder / "page_0.txt"
    blocked.write_text("hello world\n")
    blocked.chmod(0o000)
    try:
        response = client.post(
            f"/transcribe/sessions/{sid}/grade/preview",
            data={"token": "tok", "ocr_folder": str(folder)})
    finally:
        blocked.chmod(0o644)
    assert response.status_code == 400
    assert "Could not read" in response.text


def test_export_downloads_zip(session_with_gt):
    client, sid = session_with_gt
    response = client.post(f"/transcribe/sessions/{sid}/export", data={"token": "tok"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert any(name.endswith("transcriptions.json") for name in zf.namelist())
