from pathlib import Path

import pytest
from PIL import Image, features

from dpi_eval.derive import DeriveError, derive, image_dims, info_json, parse_params


@pytest.fixture
def master_png(tmp_path: Path) -> Path:
    path = tmp_path / "master.png"
    Image.new("RGB", (400, 200), color=(200, 10, 10)).save(path)
    return path


@pytest.fixture
def master_tiff(tmp_path: Path) -> Path:
    path = tmp_path / "master.tif"
    Image.new("RGB", (400, 200), color=(10, 200, 10)).save(path)
    return path


def test_parse_full_max_and_confined():
    assert parse_params("full", "max", "0", "default", "jpg") == {
        "region": None, "size": None}
    assert parse_params("10,20,100,50", "!300,300", "0", "default", "jpg") == {
        "region": (10, 20, 100, 50), "size": ("confined", 300, 300)}
    assert parse_params("full", "250,", "0", "default", "jpg") == {
        "region": None, "size": ("w", 250)}


def test_parse_rejects_unimplemented_features():
    with pytest.raises(DeriveError):
        parse_params("full", "max", "90", "default", "jpg")  # rotation
    with pytest.raises(DeriveError):
        parse_params("full", "max", "0", "gray", "jpg")  # quality
    with pytest.raises(DeriveError):
        parse_params("full", "max", "0", "default", "png")  # format
    with pytest.raises(DeriveError):
        parse_params("pct:10,10,50,50", "max", "0", "default", "jpg")


def test_derive_converts_and_caches(master_tiff, tmp_path):
    cache = tmp_path / "derivatives"
    out = derive(master_tiff, "full", "max", cache)
    assert out.suffix == ".jpg"
    with Image.open(out) as img:
        assert img.size == (400, 200)
    first_mtime = out.stat().st_mtime_ns
    again = derive(master_tiff, "full", "max", cache)
    assert again == out
    assert again.stat().st_mtime_ns == first_mtime  # cached, not re-derived


def test_derive_region_and_confined_size(master_png, tmp_path):
    out = derive(master_png, "0,0,200,200", "!100,100", tmp_path / "d")
    with Image.open(out) as img:
        assert max(img.size) == 100


@pytest.mark.skipif(
    not features.check_codec("jpg_2000"), reason="Pillow built without OpenJPEG")
def test_derive_jp2(tmp_path):
    master = tmp_path / "master.jp2"
    Image.new("RGB", (100, 80), color=(5, 5, 200)).save(master)
    out = derive(master, "full", "max", tmp_path / "d")
    with Image.open(out) as img:
        assert img.size == (100, 80)


def test_image_dims_header_only(master_png):
    assert image_dims(master_png) == (400, 200)


def test_info_json_declares_exactly_level1_plus_confined():
    doc = info_json("http://127.0.0.1:8765/x/images/0", 400, 200)
    assert doc["@context"] == "http://iiif.io/api/image/3/context.json"
    assert doc["type"] == "ImageService3"
    assert doc["profile"] == "level1"
    assert doc["extraFeatures"] == ["sizeByConfinedWh"]
    assert (doc["width"], doc["height"]) == (400, 200)


def test_corrupt_master_raises_derive_error(tmp_path):
    bad = tmp_path / "bad.tif"
    bad.write_bytes(b"not an image at all")
    with pytest.raises(DeriveError) as exc_info:
        derive(bad, "full", "max", tmp_path / "d")
    assert exc_info.value.status == 500
    with pytest.raises(DeriveError):
        image_dims(bad)


def test_cache_key_distinguishes_same_stem_different_masters(tmp_path):
    a_dir = tmp_path / "a"; b_dir = tmp_path / "b"
    a_dir.mkdir(); b_dir.mkdir()
    Image.new("RGB", (30, 30), color=(255, 0, 0)).save(a_dir / "page.png")
    Image.new("RGB", (60, 60), color=(0, 255, 0)).save(b_dir / "page.png")
    cache = tmp_path / "derivatives"
    out_a = derive(a_dir / "page.png", "full", "max", cache)
    out_b = derive(b_dir / "page.png", "full", "max", cache)
    assert out_a != out_b
    with Image.open(out_b) as img:
        assert img.size == (60, 60)
