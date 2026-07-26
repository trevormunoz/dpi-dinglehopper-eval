import json
from pathlib import Path

import pytest

from dpi_eval.iiif import IIIFError, fetch_manifest, make_stem, parse_manifest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_v2_yields_ordered_canvas_records():
    records = parse_manifest(_load("manifest_v2.json"))
    assert [r.canvas_id for r in records] == [
        "https://iiif.example.edu/c/0", "https://iiif.example.edu/c/1"]
    assert records[0].label == "Masthead"
    assert records[0].image_service == "https://iiif.example.edu/i/0"
    assert records[1].image_service is None
    assert records[1].image_url.endswith("/default.jpg")


def test_parse_v3_language_map_labels_and_service():
    records = parse_manifest(_load("manifest_v3.json"))
    assert records[0].label == "Front page"
    assert records[0].image_service == "https://iiif.example.edu/i3/0"
    assert records[1].label == "日本語"


def test_make_stem_zero_based_padded_with_slug():
    assert make_stem(7, "Masthead") == "p0007-masthead"


def test_make_stem_falls_back_to_index_when_slug_empties():
    # Non-Latin labels (Japanese-books material) slug to nothing.
    assert make_stem(3, "日本語") == "p0003"
    assert make_stem(4, "") == "p0004"


def test_fetch_rejects_non_https():
    with pytest.raises(IIIFError):
        fetch_manifest("http://iiif.example.edu/m/1")


def test_parse_rejects_manifest_with_no_canvases():
    with pytest.raises(IIIFError):
        parse_manifest({"@context": "x", "sequences": []})


def test_parse_rejects_manifest_with_imageless_canvas_mid_sequence():
    doc = _load("manifest_v2.json")
    doc["sequences"][0]["canvases"].insert(
        1, {"@id": "https://iiif.example.edu/c/blank", "label": "Blank", "images": []})
    with pytest.raises(IIIFError):
        parse_manifest(doc)


def test_parse_v3_choice_body_uses_first_choice():
    doc = _load("manifest_v3.json")
    canvas = doc["items"][0]
    anno = canvas["items"][0]["items"][0]
    original_body = anno["body"]
    anno["body"] = {
        "type": "Choice",
        "items": [original_body, {"id": "https://x/alt.jpg", "type": "Image"}],
    }
    records = parse_manifest(doc)
    assert records[0].image_url == "https://iiif.example.edu/i3/0/full/max/0/default.jpg"


def test_parse_rejects_manifest_with_empty_image_url_in_v3_body():
    # An empty image_url must be treated as "no usable image" regardless of
    # how it arose (bare body, Choice with an empty id, etc.) so the
    # index-skew guard below can catch it and refuse the manifest rather
    # than silently creating imageless pages.
    doc = _load("manifest_v3.json")
    canvas = doc["items"][0]
    anno = canvas["items"][0]["items"][0]
    anno["body"]["id"] = ""
    with pytest.raises(IIIFError):
        parse_manifest(doc)


def test_parse_rejects_manifest_with_malformed_v3_items():
    with pytest.raises(IIIFError):
        parse_manifest({"@context": "x", "items": {"a": 1}})


def test_parse_rejects_manifest_with_malformed_v2_images():
    doc = {"@context": "x", "sequences": [{"canvases": [
        {"@id": "https://iiif.example.edu/c/0", "label": "P1",
         "images": {"a": 1}}]}]}
    with pytest.raises(IIIFError):
        parse_manifest(doc)


def test_fetch_manifest_happy_path_parses_json(monkeypatch):
    import io

    from dpi_eval import iiif as iiif_module

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def geturl(self):
            return "https://iiif.example.edu/m/1"

    def fake_open(url, data=None, timeout=None):
        assert url == "https://iiif.example.edu/m/1"
        return FakeResponse(b'{"@context": "x", "sequences": []}')

    monkeypatch.setattr(iiif_module._opener, "open", fake_open)
    doc = fetch_manifest("https://iiif.example.edu/m/1")
    assert doc == {"@context": "x", "sequences": []}


def test_fetch_manifest_rejects_final_url_that_redirected_to_http(monkeypatch):
    import io

    from dpi_eval import iiif as iiif_module

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def geturl(self):
            # Belt-and-braces path: some handler let a redirect through
            # without going through _NoInsecureRedirectHandler's check —
            # the post-hoc geturl() check must still catch it.
            return "http://169.254.169.254/latest/meta-data/"

    def fake_open(url, data=None, timeout=None):
        return FakeResponse(b'{"@context": "x", "sequences": []}')

    monkeypatch.setattr(iiif_module._opener, "open", fake_open)
    with pytest.raises(IIIFError):
        fetch_manifest("https://iiif.example.edu/m/1")


def test_fetch_manifest_redirect_to_http_never_issues_the_http_request(monkeypatch):
    import email.message
    import io
    import urllib.request

    attempted = []

    class FakeHandlerResponse(io.BytesIO):
        def __init__(self, url, code, headers_dict, body=b""):
            super().__init__(body)
            self._url = url
            self.code = code
            self.status = code
            self.msg = "Found" if code != 200 else "OK"
            message = email.message.Message()
            for key, value in headers_dict.items():
                message[key] = value
            self.headers = message

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def geturl(self):
            return self._url

        def info(self):
            return self.headers

    def fake_https_open(self, req):
        attempted.append(req.full_url)
        # Simulate the manifest host issuing a 302 to an internal address —
        # the SSRF-via-redirect shape from the review.
        return FakeHandlerResponse(
            req.full_url, 302,
            {"location": "http://169.254.169.254/latest/meta-data/"})

    def fake_http_open(self, req):
        attempted.append(req.full_url)
        raise AssertionError(
            "must not issue a request to the http redirect target")

    monkeypatch.setattr(
        urllib.request.HTTPSHandler, "https_open", fake_https_open)
    monkeypatch.setattr(
        urllib.request.HTTPHandler, "http_open", fake_http_open)

    with pytest.raises(IIIFError):
        fetch_manifest("https://iiif.example.edu/m/1")

    assert attempted == ["https://iiif.example.edu/m/1"]
    assert "http://169.254.169.254/latest/meta-data/" not in attempted


def test_fetch_manifest_rejects_oversized_body(monkeypatch):
    import io

    from dpi_eval import iiif as iiif_module

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def geturl(self):
            return "https://iiif.example.edu/m/1"

    huge_payload = (
        b'{"@context": "' + b'x' * 20_000_000 + b'", "sequences": []}'
    )

    def fake_open(url, data=None, timeout=None):
        return FakeResponse(huge_payload)

    monkeypatch.setattr(iiif_module._opener, "open", fake_open)
    with pytest.raises(IIIFError):
        fetch_manifest("https://iiif.example.edu/m/1")
