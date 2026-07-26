from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, features

from dpi_eval.derive import MAX_DIM, DeriveError, derive, image_dims, info_json, parse_params


@pytest.fixture
def master_bicolor(tmp_path: Path) -> Path:
    """400x200 master, left half red, right half blue -- lets tests verify
    a crop pulled the correct region rather than just the correct size."""
    path = tmp_path / "bicolor.png"
    img = Image.new("RGB", (400, 200), color=(0, 0, 255))
    for x in range(200):
        for y in range(200):
            img.putpixel((x, y), (255, 0, 0))
    img.save(path)
    return path


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


def test_derive_region_and_confined_size(master_bicolor, tmp_path):
    # Region is 2:1 (200x100 of a 400x200 master), so a confined !100,100
    # box must preserve aspect ratio -> 100x50, not a forced square.
    out = derive(master_bicolor, "0,0,200,100", "!100,100", tmp_path / "d")
    with Image.open(out) as img:
        assert img.size == (100, 50)


def test_derive_region_crops_correct_area(master_bicolor, tmp_path):
    # Left half of the master is red; cropping just that half must not
    # pick up any blue from the right half.
    out = derive(master_bicolor, "0,0,200,200", "max", tmp_path / "d")
    with Image.open(out) as img:
        assert img.size == (200, 200)
        r, g, b = img.getpixel((100, 100))
        assert r > 150 and b < 100


def test_derive_rejects_oversized_width(master_png, tmp_path, monkeypatch):
    # master_png is 400x200, so a plain request for 150px would neither
    # upscale nor exceed the real MAX_DIM=4000 -- lower the bound so this
    # test actually exercises _check_dim's `value > MAX_DIM` branch rather
    # than riding the (separate) upscale refusal, which is what a raw
    # 100000px request would trip regardless of any dimension bound.
    monkeypatch.setattr("dpi_eval.derive.MAX_DIM", 100)
    with pytest.raises(DeriveError) as exc_info:
        derive(master_png, "full", "150,", tmp_path / "d")
    assert exc_info.value.status == 400


def test_derive_rejects_oversized_confined(master_png, tmp_path):
    with pytest.raises(DeriveError) as exc_info:
        derive(master_png, "full", f"!{MAX_DIM + 1},{MAX_DIM + 1}", tmp_path / "d")
    assert exc_info.value.status == 400


def test_derive_rejects_upscale_plain_width(master_png, tmp_path):
    # master_png is 400x200; asking for 800, would upscale without the
    # IIIF '^' prefix this service does not implement.
    with pytest.raises(DeriveError) as exc_info:
        derive(master_png, "full", "800,", tmp_path / "d")
    assert exc_info.value.status == 400


def test_derive_rejects_upscale_plain_height(master_png, tmp_path):
    with pytest.raises(DeriveError) as exc_info:
        derive(master_png, "full", ",400", tmp_path / "d")
    assert exc_info.value.status == 400


def test_derive_confined_size_never_upscales(master_png, tmp_path):
    # master_png is 400x200; a confined box larger than the source must
    # not enlarge it (this already worked via Image.thumbnail, and must
    # keep working now that plain w,/,h reject upscaling outright).
    out = derive(master_png, "full", "!800,800", tmp_path / "d")
    with Image.open(out) as img:
        assert img.size == (400, 200)


def test_derive_rejects_zero_size_as_client_error(master_png, tmp_path):
    cache = tmp_path / "d"
    # parse_params raises before derive() ever creates the cache directory,
    # so `cache.exists()` is False here and a `... if cache.exists() else
    # True` guard around the glob assertion is vacuously satisfied no
    # matter what -- exercise a prior successful derive first so the
    # directory genuinely exists when we check for a .tmp leftover.
    derive(master_png, "full", "max", cache)
    assert cache.exists()
    with pytest.raises(DeriveError) as exc_info:
        derive(master_png, "full", "0,", cache)
    assert exc_info.value.status == 400
    assert "master" not in str(exc_info.value).lower()
    # no .tmp leftovers from a request that never should have started a save
    assert not any(cache.glob("**/*.tmp"))


def test_derive_cleans_up_tmp_on_save_failure(master_png, tmp_path):
    cache = tmp_path / "d"
    with patch("PIL.Image.Image.save", side_effect=OSError("disk full")):
        with pytest.raises(DeriveError) as exc_info:
            derive(master_png, "full", "max", cache)
    assert exc_info.value.status == 500
    assert not list(cache.glob("*.tmp"))


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


def test_info_json_declares_only_what_is_implemented():
    # Per the IIIF Image API 3.0 compliance table, level1 requires
    # regionByPx, regionSquare, sizeByW, sizeByH, sizeByWh, baseUriRedirect
    # and cors. This service rejects region=square, has no bare-"w,h" size
    # form, no bare-{n}->info.json redirect and sets no CORS headers, so
    # claiming "level1" is false advertising to any client that trusts the
    # profile. It must declare the lower level it actually is (level0) and
    # list only the extra features genuinely implemented.
    doc = info_json("http://127.0.0.1:8765/x/images/0", 400, 200)
    assert doc["@context"] == "http://iiif.io/api/image/3/context.json"
    assert doc["type"] == "ImageService3"
    assert doc["profile"] == "level0"
    assert set(doc["extraFeatures"]) == {
        "regionByPx", "sizeByW", "sizeByH", "sizeByConfinedWh"}
    # None of the level1-required features this service does not implement
    # may be claimed, whether as the profile itself or via extraFeatures.
    assert "regionSquare" not in doc["extraFeatures"]
    assert "sizeByWh" not in doc["extraFeatures"]
    assert "baseUriRedirect" not in doc["extraFeatures"]
    assert "cors" not in doc["extraFeatures"]
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


def test_cache_key_reflects_actual_pixels_not_request_string(master_png, tmp_path):
    # master_png is 400x200. Two region strings that both clamp to the
    # same actual crop (the whole master) must share one cache file, not
    # each get their own -- otherwise an attacker sweeping the region
    # string space (e.g. 0,0,{100..139},200) fills disk with duplicate
    # JPEGs of identical pixels. Region is part of the cache key, so this
    # only holds if the key is built from the clamped/actual dimensions.
    cache = tmp_path / "d"
    out_a = derive(master_png, "0,0,400,200", "max", cache)
    out_b = derive(master_png, "0,0,999999999,999999999", "max", cache)
    assert out_a == out_b
    assert len(list(cache.glob("*.jpg"))) == 1


def test_size_max_is_bounded_like_every_other_path(master_png, tmp_path, monkeypatch):
    # The module docstring claims every cached derivative is bounded to
    # MAX_DIM per axis, but size=max/full skipped _check_dim entirely and
    # decoded the master at native resolution. Lower MAX_DIM below the
    # master's real size (400x200) and confirm max/full is clamped to it,
    # preserving aspect ratio rather than decoding unbounded pixels.
    monkeypatch.setattr("dpi_eval.derive.MAX_DIM", 100)
    out = derive(master_png, "full", "max", tmp_path / "d")
    with Image.open(out) as img:
        assert img.width <= 100 and img.height <= 100
        assert img.width == 100  # 400x200 -> aspect-preserving fit to 100x?


def test_decode_time_corruption_raises_derive_error(tmp_path):
    good = tmp_path / "good.png"
    Image.new("RGB", (50, 50), color=(1, 2, 3)).save(good)
    data = bytearray(good.read_bytes())
    # Corrupt bytes past the 33-byte signature+IHDR so the file still
    # opens (or fails) but pixel decode breaks either way.
    for i in range(40, min(len(data) - 8, 120)):
        data[i] ^= 0xFF
    bad = tmp_path / "bad.png"
    bad.write_bytes(bytes(data))
    with pytest.raises(DeriveError) as exc_info:
        derive(bad, "full", "max", tmp_path / "d")
    assert exc_info.value.status == 500
