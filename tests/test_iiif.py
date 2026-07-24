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
