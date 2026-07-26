from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from dpi_eval.web import create_app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "tok")
    folder = tmp_path / "masters"
    folder.mkdir()
    Image.new("RGB", (60, 40)).save(folder / "a.tif")
    Image.new("RGB", (60, 40)).save(folder / "b.tif")
    client = TestClient(create_app(tmp_path))
    response = client.post("/transcribe/sessions", data={
        "token": "tok", "source_type": "local", "folder": str(folder),
        "mode": "from_scratch", "collection": ""})
    sid = response.text.split('data-session-id="', 1)[1].split('"', 1)[0]
    client.post(f"/transcribe/sessions/{sid}/confirm",
                data={"token": "tok", "pages": ["0", "1"]})
    return client, sid, folder


def test_editor_page_has_substitution_defenses(setup):
    client, sid, _folder = setup
    response = client.get(f"/transcribe/sessions/{sid}/pages/0")
    assert response.status_code == 200
    for attr in ('spellcheck="false"', 'autocorrect="off"', 'autocapitalize="off"'):
        assert attr in response.text


def test_save_no_text_and_flag_actions(setup):
    client, sid, _folder = setup
    save = client.post(f"/transcribe/sessions/{sid}/pages/0", data={
        "token": "tok", "action": "save", "text": "Line one\nLine two",
        "elapsed": "12", "active": "8", "nonce": "n1"}, follow_redirects=False)
    assert save.status_code == 303  # redirects to next page
    no_text = client.post(f"/transcribe/sessions/{sid}/pages/1", data={
        "token": "tok", "action": "no_text", "reason": "blank"}, follow_redirects=False)
    assert no_text.status_code == 303
    flag = client.post(f"/transcribe/sessions/{sid}/pages/0", data={
        "token": "tok", "action": "flag", "flagged": "on", "note": "check ligature"},
        follow_redirects=False)
    assert flag.status_code == 303
    bad = client.post(f"/transcribe/sessions/{sid}/pages/0", data={
        "token": "wrong", "action": "save", "text": "x"})
    assert bad.status_code == 403


def test_image_endpoint_derives_tiff_to_jpeg(setup):
    client, sid, _folder = setup
    response = client.get(
        f"/transcribe/sessions/{sid}/images/0/full/max/0/default.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    info = client.get(f"/transcribe/sessions/{sid}/images/0/info.json")
    assert info.status_code == 200
    doc = info.json()
    # R2-S7: this asserted "level1" while the service rejected four
    # level-1-required features. The profile must match what the route will
    # actually serve, so exercise an advertised extraFeature here rather than
    # trusting the declaration -- test_derive.py checks the declaration itself.
    assert doc["profile"] == "level0" and doc["width"] == 60
    assert "sizeByW" in doc["extraFeatures"]
    served = client.get(
        f"/transcribe/sessions/{sid}/images/0/full/30,/0/default.jpg")
    assert served.status_code == 200, "advertised sizeByW must actually work"


def test_image_endpoint_rejects_unimplemented(setup):
    client, sid, _folder = setup
    response = client.get(
        f"/transcribe/sessions/{sid}/images/0/full/max/90/default.jpg")
    assert response.status_code == 400


def test_editor_page_escapes_hostile_manifest_image_urls(tmp_path):
    from dpi_eval import pages, sessions as sess
    from dpi_eval.iiif import CanvasRecord

    root = sess.transcriptions_root(tmp_path)
    hostile = 'https://x/i/0" onerror="alert(1)'
    records = [CanvasRecord("https://x/c/0", "Page 0", hostile, None)]
    session = sess.create_iiif_session(root, "https://x/m", records, "from_scratch", "")
    sess.confirm_session(root, session["id"], [0])
    session = sess.load_session(root, session["id"])
    page = session["pages"][0]
    html_out = pages.editor_page(session, page, "", "", "tok", "Page 1 of 1")
    assert 'onerror="alert(1)' not in html_out


def test_editor_page_refuses_javascript_scheme_image_url(tmp_path):
    from dpi_eval import pages, sessions as sess
    from dpi_eval.iiif import CanvasRecord

    root = sess.transcriptions_root(tmp_path)
    records = [CanvasRecord("https://x/c/0", "Page 0", "javascript:alert(1)", None)]
    session = sess.create_iiif_session(root, "https://x/m", records, "from_scratch", "")
    sess.confirm_session(root, session["id"], [0])
    session = sess.load_session(root, session["id"])
    page = session["pages"][0]
    html_out = pages.editor_page(session, page, "", "", "tok", "Page 1 of 1")
    assert "javascript:" not in html_out


def test_editor_page_survives_a_session_saved_before_the_id_type_guard(tmp_path):
    """R2-C1 leftover: the parser now guarantees `image_url` is a str, but a
    session.json written before that fix still carries whatever the manifest
    had. `_safe_url`'s `url: str` is an annotation, not a runtime check, so a
    dict reached `.startswith()` and the editor 500ed with no way for the user
    to recover — nothing in the app rewrites that file."""
    import json

    from dpi_eval import pages, sessions as sess
    from dpi_eval.iiif import CanvasRecord

    root = sess.transcriptions_root(tmp_path)
    records = [CanvasRecord(
        "https://x/c/0", "Page 0", "https://x/i/0.jpg", None)]
    session = sess.create_iiif_session(
        root, "https://x/m", records, "from_scratch", "")
    sess.confirm_session(root, session["id"], [0])
    # Simulate the pre-fix file: hand-edit the id back to the dict shape that
    # parse_manifest would now reject outright.
    path = sess.session_dir(root, session["id"]) / "session.json"
    on_disk = json.loads(path.read_text())
    on_disk["pages"][0]["image_url"] = {"@id": "https://x/i/0.jpg"}
    path.write_text(json.dumps(on_disk))

    session = sess.load_session(root, session["id"])
    page = session["pages"][0]
    html_out = pages.editor_page(session, page, "", "", "tok", "Page 1 of 1")
    # Degrades to no image rather than faulting; the page still opens so the
    # transcription and the export are reachable.
    assert "<h1>" in html_out
    assert "@id" not in html_out


def test_image_info_returns_json_500_for_corrupt_master(setup):
    client, sid, folder = setup
    (folder / "a.tif").write_bytes(b"junk not an image")
    response = client.get(f"/transcribe/sessions/{sid}/images/0/info.json")
    assert response.status_code == 500
    assert "error" in response.json()
