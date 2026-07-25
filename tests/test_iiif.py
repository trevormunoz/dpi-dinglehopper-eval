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
    anno["body"] = [anno["body"], {"id": "https://x/alt.jpg", "type": "Image"}]
    records = parse_manifest(doc)
    assert records[0].image_url == "https://iiif.example.edu/i3/0/full/max/0/default.jpg"


def test_fetch_manifest_happy_path_parses_json(monkeypatch):
    import io
    import urllib.request

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_urlopen(url, timeout=None):
        assert url == "https://iiif.example.edu/m/1"
        return FakeResponse(b'{"@context": "x", "sequences": []}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    doc = fetch_manifest("https://iiif.example.edu/m/1")
    assert doc == {"@context": "x", "sequences": []}
