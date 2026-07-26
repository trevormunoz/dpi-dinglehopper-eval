"""IIIF Image API level-1 derivation over local masters (Pillow).

Engine choice per spec: Pillow, not shell-side Rust (thin-shell rule;
Rust has no native JP2 — it would bind the same C OpenJPEG Pillow
bundles). Performance ladder if pilot-measured decode latency hurts:
pyvips behind this same interface.

Declared capability = implemented capability. Per the IIIF Image API
3.0 compliance table, level 1 requires regionByPx, regionSquare,
sizeByW, sizeByH, sizeByWh, baseUriRedirect and cors. This service
rejects region=square, has no bare-"w,h" size form, no bare-{n} ->
info.json redirect, and sets no CORS headers, so it does not meet
level 1 and must not claim to (info_json below declares level0 plus
the extraFeatures actually implemented: regionByPx, sizeByW, sizeByH,
sizeByConfinedWh (!w,h)). Rotation other than 0, qualities other than
default, and formats other than jpg are rejected with 400.

Upscaling: IIIF Image API 3.0 requires a '^' prefix on the size
parameter to request upscaling, which level 1 (and this service) does
not implement. sizeByW/sizeByH therefore refuse to enlarge past the
(possibly region-cropped) source dimensions, matching the
sizeByConfinedWh behaviour Pillow's Image.thumbnail already gave us
for free. The editor's "Enlarge" lightbox shows the master at its own
resolution — it never needs synthetic upscaling.

Per-file bound: MAX_DIM caps every derivative's width/height on every
path, including size=max/full, which used to skip the bound entirely
and decode the master at native resolution -- a
'.../full/100000,/0/default.jpg'-shaped master could force Pillow to
allocate multi-GB. max/full is now clamped to MAX_DIM the same way
sizeByConfinedWh already was (aspect-preserving fit, never upscaled).
This is a desktop transcription editor serving locally-scanned page
masters (largest current fixture: 1700x2200); MAX_DIM=4000 gives
~2.3x headroom over that for larger future scans while keeping the
worst-case decoded RGB buffer (4000x4000x3 bytes ~= 48MB) far below
what an unbounded request could otherwise force.

Cache-key bound (partial, not a size bound): the key is built from the
*clamped* region/size actually produced, not the raw request string,
so requests that clamp to identical pixels (e.g. a swept
region=0,0,{100..140},h against a small master, or region=0,0,huge,huge
vs. region=full) share one cache file instead of each minting a
byte-identical duplicate. This does NOT bound the *number* of cache
entries: IIIF permits arbitrary pixel regions, and a client (or an
untrusted local page driving the token-free image routes with
`<img src>`) requesting many genuinely distinct crops still creates
one file per distinct crop, unbounded, with no eviction. Per-file size
is now bounded; total cache directory size is not. If that becomes a
real problem, the fix is disk-usage eviction (LRU by mtime) or a
per-session cache byte cap, not a claim that the current bound already
covers it.
"""

import hashlib
import re
import secrets
from pathlib import Path

from PIL import Image

MAX_DIM = 4000

_REGION = re.compile(r"^(\d+),(\d+),(\d+),(\d+)$")
_SIZE_W = re.compile(r"^(\d+),$")
_SIZE_H = re.compile(r"^,(\d+)$")
_SIZE_CONFINED = re.compile(r"^!(\d+),(\d+)$")


class DeriveError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _check_dim(value: int) -> int:
    if value <= 0:
        raise DeriveError("Width and height must be > 0.")
    if value > MAX_DIM:
        raise DeriveError(f"Requested dimension {value} exceeds the maximum of {MAX_DIM}px.")
    return value


def parse_params(region: str, size: str, rotation: str, quality: str, fmt: str) -> dict:
    if rotation != "0":
        raise DeriveError("Only rotation 0 is supported (level 1).")
    if quality != "default":
        raise DeriveError("Only quality 'default' is supported (level 1).")
    if fmt != "jpg":
        raise DeriveError("Only .jpg output is supported.")

    if region == "full":
        parsed_region = None
    else:
        match = _REGION.match(region)
        if not match:
            raise DeriveError(f"Unsupported region: {region!r}")
        parsed_region = tuple(int(g) for g in match.groups())

    if size in ("max", "full"):
        parsed_size = None
    elif m := _SIZE_W.match(size):
        parsed_size = ("w", _check_dim(int(m.group(1))))
    elif m := _SIZE_H.match(size):
        parsed_size = ("h", _check_dim(int(m.group(1))))
    elif m := _SIZE_CONFINED.match(size):
        parsed_size = ("confined", _check_dim(int(m.group(1))), _check_dim(int(m.group(2))))
    else:
        raise DeriveError(f"Unsupported size: {size!r}")

    return {"region": parsed_region, "size": parsed_size}


def image_dims(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as img:  # lazy: reads headers, not pixel data
            return img.size
    except Exception as exc:
        raise DeriveError(f"Cannot read master image {path.name}: {exc}",
                          status=500) from exc


def _confined_dims(w: int, h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """Aspect-preserving fit of w x h inside max_w x max_h, never upscaling.
    Used for both !w,h (confined) requests and to bound max/full the same
    way, and computed independently of any decoded pixel data so the cache
    key (built before the master is opened) matches the actual output."""
    if w <= max_w and h <= max_h:
        return w, h
    ratio = min(max_w / w, max_h / h)
    return max(1, round(w * ratio)), max(1, round(h * ratio))


def _resolve_output_dims(rw: int, rh: int, size_spec) -> tuple[int, int]:
    """Given the region's actual width/height (rw, rh), compute the exact
    output pixel dimensions the given parsed size spec produces -- pure
    arithmetic on already-clamped dimensions, no image decode required.
    max/full (size_spec is None) is bounded to MAX_DIM like every other
    path (R2-S8: this used to skip the bound and decode the master at
    native resolution)."""
    if size_spec is None:  # "max" or "full"
        return _confined_dims(rw, rh, MAX_DIM, MAX_DIM)
    kind = size_spec[0]
    if kind == "w":
        target_w = size_spec[1]
        if target_w > rw:
            raise DeriveError(
                f"Requested width {target_w} exceeds source width {rw}; "
                "upscaling requires the IIIF '^' size prefix, which is not "
                "supported.")
        return target_w, max(1, round(rh * target_w / rw))
    if kind == "h":
        target_h = size_spec[1]
        if target_h > rh:
            raise DeriveError(
                f"Requested height {target_h} exceeds source height {rh}; "
                "upscaling requires the IIIF '^' size prefix, which is not "
                "supported.")
        return max(1, round(rw * target_h / rh)), target_h
    # confined !w,h
    return _confined_dims(rw, rh, size_spec[1], size_spec[2])


def derive(master: Path, region: str, size: str, cache_dir: Path) -> Path:
    params = parse_params(region, size, "0", "default", "jpg")
    width, height = image_dims(master)  # header-only read, no pixel decode

    # Canonicalize the region against the master's real dimensions *before*
    # building the cache key. Region is part of the key, and IIIF region
    # values are clamped to the source (an over-large w/h just clips), so
    # two different request strings that clamp to the same box (R2-S8: a
    # swept region=0,0,{100..140},h, or region=full vs. an absurdly large
    # explicit box) must resolve to the same key -- otherwise each distinct
    # string mints its own byte-identical cache file.
    if params["region"]:
        x, y, w, h = params["region"]
        if x >= width or y >= height or w == 0 or h == 0:
            raise DeriveError("Region out of bounds.", status=400)
        rx, ry = x, y
        rw, rh = min(w, width - x), min(h, height - y)
    else:
        rx, ry, rw, rh = 0, 0, width, height

    out_w, out_h = _resolve_output_dims(rw, rh, params["size"])

    src_tag = hashlib.sha1(str(master.resolve()).encode("utf-8")).hexdigest()[:8]
    key = f"{master.stem}_{src_tag}_{rx}-{ry}-{rw}-{rh}_{out_w}x{out_h}"
    key = re.sub(r"[^A-Za-z0-9_-]", "_", key)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{key}.jpg"
    if out.exists():
        return out

    try:
        with Image.open(master) as img:
            img = img.convert("RGB")
            if params["region"]:
                img = img.crop((rx, ry, rx + rw, ry + rh))
            if (out_w, out_h) != (rw, rh):
                img = img.resize((out_w, out_h))
            tmp = out.with_suffix(f".{secrets.token_hex(4)}.tmp")
            try:
                img.save(tmp, format="JPEG", quality=90)
                tmp.replace(out)
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
    except DeriveError:
        raise
    except Exception as exc:
        raise DeriveError(f"Cannot read master image {master.name}: {exc}",
                          status=500) from exc
    return out


def info_json(base_url: str, width: int, height: int) -> dict:
    # profile=level0: this service does not implement regionSquare,
    # sizeByWh, baseUriRedirect or cors, all required for level1 (see
    # module docstring). extraFeatures lists exactly what IS implemented
    # beyond the level0 baseline, so a spec-honest client sees a bare
    # bounding box of real support instead of a level1 claim it can't rely on.
    return {
        "@context": "http://iiif.io/api/image/3/context.json",
        "id": base_url,
        "type": "ImageService3",
        "protocol": "http://iiif.io/api/image",
        "profile": "level0",
        "width": width,
        "height": height,
        "extraFeatures": ["regionByPx", "sizeByW", "sizeByH", "sizeByConfinedWh"],
    }
