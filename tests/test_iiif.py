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


_NON_STRING_IDS = [{"evil": 1}, ["https://x/a.jpg"], 7, True]


@pytest.mark.parametrize("bad_id", _NON_STRING_IDS)
def test_parse_rejects_v3_body_with_non_string_id(bad_id):
    # A non-string id is truthy, so `if not image_url` never fires: without a
    # type check the record reaches session.json and the editor's _safe_url
    # calls .startswith() on it, leaving the session permanently un-openable.
    doc = _load("manifest_v3.json")
    doc["items"][0]["items"][0]["items"][0]["body"]["id"] = bad_id
    with pytest.raises(IIIFError, match="must be a string"):
        parse_manifest(doc)


@pytest.mark.parametrize("bad_id", _NON_STRING_IDS)
def test_parse_rejects_v2_resource_with_non_string_id(bad_id):
    doc = _load("manifest_v2.json")
    doc["sequences"][0]["canvases"][0]["images"][0]["resource"]["@id"] = bad_id
    with pytest.raises(IIIFError, match="must be a string"):
        parse_manifest(doc)


def test_parse_rejects_v3_service_with_non_string_id():
    # image_service is string-formatted into an Image API URL by the editor,
    # so a non-string here is the same permanently-broken page as a bad body
    # id.
    doc = _load("manifest_v3.json")
    body = doc["items"][0]["items"][0]["items"][0]["body"]
    body["service"] = [{"id": {"evil": 1}, "type": "ImageService3"}]
    with pytest.raises(IIIFError, match="must be a string"):
        parse_manifest(doc)


def test_parse_rejects_v2_service_with_non_string_id():
    doc = _load("manifest_v2.json")
    resource = doc["sequences"][0]["canvases"][0]["images"][0]["resource"]
    resource["service"] = {"@id": ["https://iiif.example.edu/i/0"]}
    with pytest.raises(IIIFError, match="must be a string"):
        parse_manifest(doc)


def test_parse_rejects_v3_canvas_with_non_string_id():
    # canvas_id is carried into session.json and the export rows; a dict there
    # would be repr'd into the evidence a purchasing decision is read off.
    doc = _load("manifest_v3.json")
    doc["items"][1]["id"] = {"evil": 1}
    with pytest.raises(IIIFError, match="must be a string"):
        parse_manifest(doc)


def test_parse_rejects_v2_canvas_with_non_string_id():
    doc = _load("manifest_v2.json")
    doc["sequences"][0]["canvases"][1]["@id"] = {"evil": 1}
    with pytest.raises(IIIFError, match="must be a string"):
        parse_manifest(doc)


@pytest.mark.parametrize("bad_type", [None, "Range", "canvas", 3, {"a": 1}])
def test_parse_rejects_v3_item_that_is_not_a_canvas(bad_type):
    # The skip used to run before canvas_count += 1, so the bad item vanished
    # from BOTH sides of the index-skew guard: three canvases with the middle
    # one malformed parsed as two records, and canvas 2's image landed at
    # index 1. Page 1's transcription would then be graded against canvas 2's
    # page_1 OCR with nothing in the output saying so.
    doc = _load("manifest_v3.json")
    middle = json.loads(json.dumps(doc["items"][0]))
    middle["id"] = "https://iiif.example.edu/c3/mid"
    middle["items"][0]["items"][0]["body"]["id"] = "https://x/i/mid.jpg"
    middle["items"][0]["items"][0]["body"].pop("service", None)
    if bad_type is None:
        middle.pop("type")
    else:
        middle["type"] = bad_type
    doc["items"].insert(1, middle)
    with pytest.raises(IIIFError, match="Canvas"):
        parse_manifest(doc)


def test_parse_v3_non_canvas_item_never_shifts_surviving_indices():
    # Belt-and-braces on the above: whatever the disposition of a non-Canvas
    # item, it must never be possible for a record to end up at an index that
    # is not its own position in `items`.
    doc = _load("manifest_v3.json")
    doc["items"].insert(1, {"id": "https://iiif.example.edu/r/0",
                            "type": "Range"})
    try:
        records = parse_manifest(doc)
    except IIIFError:
        return
    assert [r.canvas_id for r in records] == [
        "https://iiif.example.edu/c3/0", "https://iiif.example.edu/r/0",
        "https://iiif.example.edu/c3/1"], (
        "a skipped item shifted every later canvas index")


@pytest.mark.parametrize(
    "doc", [[], ["sequences"], "sequences", 7, None])
def test_parse_rejects_manifest_that_is_not_an_object(doc):
    # Same class as the scalar ids: json.loads happily returns a list, a str
    # or a number, and both callers catch only IIIFError — so an
    # AttributeError from doc.get() (or, for a str, a substring "sequences"
    # match) escapes as a 500 instead of a readable create-time error.
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

    def fake_open(req, data=None, timeout=None):
        # fetch_manifest wraps the URL in a Request so it can carry headers.
        assert req.full_url == "https://iiif.example.edu/m/1"
        return FakeResponse(b'{"@context": "x", "sequences": []}')

    monkeypatch.setattr(iiif_module._opener, "open", fake_open)
    doc = fetch_manifest("https://iiif.example.edu/m/1")
    assert doc == {"@context": "x", "sequences": []}


def _capturing_opener(monkeypatch, body=b'{"@context": "x", "sequences": []}'):
    """Patch _opener.open and hand back the list it records requests into."""
    import io

    from dpi_eval import iiif as iiif_module

    seen = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def geturl(self):
            return "https://iiif.example.edu/m/1"

    def fake_open(req, data=None, timeout=None):
        seen.append(req)
        return FakeResponse(body)

    monkeypatch.setattr(iiif_module._opener, "open", fake_open)
    return seen


def test_fetch_manifest_sends_an_identifying_user_agent(monkeypatch):
    """Default is honest: the fetch says what it is. urllib's own
    'Python-urllib/3.x' says nothing about who is asking."""
    monkeypatch.delenv("DPI_EVAL_USER_AGENT", raising=False)
    seen = _capturing_opener(monkeypatch)
    fetch_manifest("https://iiif.example.edu/m/1")
    sent = seen[0].get_header("User-agent")
    assert sent and sent.startswith("dpi-eval/")
    assert "Python-urllib" not in sent


def test_fetch_manifest_user_agent_is_configurable(monkeypatch):
    """UMD (and other institutions) front their IIIF servers with a WAF that
    400s an unrecognised User-Agent, including an honest one. Operators need to
    be able to set what gets sent without editing source."""
    monkeypatch.setenv("DPI_EVAL_USER_AGENT", "Mozilla/5.0 (Macintosh)")
    seen = _capturing_opener(monkeypatch)
    fetch_manifest("https://iiif.example.edu/m/1")
    assert seen[0].get_header("User-agent") == "Mozilla/5.0 (Macintosh)"


def test_fetch_manifest_blank_user_agent_falls_back_to_the_default(monkeypatch):
    """An empty env var must not send an empty header — UMD's WAF answers 403
    to a request with no User-Agent at all."""
    monkeypatch.setenv("DPI_EVAL_USER_AGENT", "   ")
    seen = _capturing_opener(monkeypatch)
    fetch_manifest("https://iiif.example.edu/m/1")
    assert seen[0].get_header("User-agent").startswith("dpi-eval/")


def test_fetch_manifest_explains_a_probable_waf_rejection(monkeypatch):
    """A bare '400 Bad Request' sends the user hunting for a broken URL, when
    the real cause is a filter that never looked at the URL. The error has to
    name the override, or nobody can act on it."""
    import urllib.error

    from dpi_eval import iiif as iiif_module

    def fake_open(req, data=None, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {}, None)

    monkeypatch.setattr(iiif_module._opener, "open", fake_open)
    with pytest.raises(IIIFError) as excinfo:
        fetch_manifest("https://iiif.example.edu/m/1")
    message = str(excinfo.value)
    assert "DPI_EVAL_USER_AGENT" in message
    assert "400" in message


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
