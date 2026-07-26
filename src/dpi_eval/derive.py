"""IIIF Image API level-1 derivation over local masters (Pillow).

Engine choice per spec: Pillow, not shell-side Rust (thin-shell rule;
Rust has no native JP2 — it would bind the same C OpenJPEG Pillow
bundles). Performance ladder if pilot-measured decode latency hurts:
pyvips behind this same interface.

Declared capability = implemented capability: level 1 plus
sizeByConfinedWh (!w,h). Rotation other than 0, qualities other than
default, and formats other than jpg are rejected with 400.

Upscaling: IIIF Image API 3.0 requires a '^' prefix on the size
parameter to request upscaling, which level 1 (and this service) does
not implement. sizeByW/sizeByH therefore refuse to enlarge past the
(possibly region-cropped) source dimensions, matching the
sizeByConfinedWh behaviour Pillow's Image.thumbnail already gave us
for free. The editor's "Enlarge" lightbox shows the master at its own
resolution — it never needs synthetic upscaling.

Bound: MAX_DIM caps any requested width/height. This is a desktop
transcription editor serving locally-scanned page masters (largest
current fixture: 1700x2200); MAX_DIM=4000 gives ~2.3x headroom over
that for larger future scans while keeping the worst-case decoded RGB
buffer (4000x4000x3 bytes ~= 48MB) far below the multi-GB a
'.../full/100000,/0/default.jpg' request could otherwise force Pillow
to allocate. Combined with the upscale refusal above, every cached
derivative is now bounded in both count-of-possible-sizes (<=MAX_DIM
per axis) and per-file weight, so no separate cache-eviction scheme is
added: this is a single-user local session, not a public endpoint an
attacker can use to flood disk with arbitrary distinct sizes.
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


def derive(master: Path, region: str, size: str, cache_dir: Path) -> Path:
    params = parse_params(region, size, "0", "default", "jpg")
    src_tag = hashlib.sha1(str(master.resolve()).encode("utf-8")).hexdigest()[:8]
    key = f"{master.stem}_{src_tag}_{region}_{size}".replace(",", "-").replace("!", "c")
    key = re.sub(r"[^A-Za-z0-9_-]", "_", key)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{key}.jpg"
    if out.exists():
        return out

    try:
        with Image.open(master) as img:
            img = img.convert("RGB")
            if params["region"]:
                x, y, w, h = params["region"]
                if x >= img.width or y >= img.height or w == 0 or h == 0:
                    raise DeriveError("Region out of bounds.", status=400)
                img = img.crop((x, y, min(x + w, img.width), min(y + h, img.height)))
            if params["size"]:
                spec = params["size"]
                if spec[0] == "w":
                    if spec[1] > img.width:
                        raise DeriveError(
                            f"Requested width {spec[1]} exceeds source width {img.width}; "
                            "upscaling requires the IIIF '^' size prefix, which is not "
                            "supported.")
                    ratio = spec[1] / img.width
                    img = img.resize((spec[1], max(1, round(img.height * ratio))))
                elif spec[0] == "h":
                    if spec[1] > img.height:
                        raise DeriveError(
                            f"Requested height {spec[1]} exceeds source height {img.height}; "
                            "upscaling requires the IIIF '^' size prefix, which is not "
                            "supported.")
                    ratio = spec[1] / img.height
                    img = img.resize((max(1, round(img.width * ratio)), spec[1]))
                else:  # confined !w,h -- Image.thumbnail never upscales
                    img.thumbnail((spec[1], spec[2]))
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
    return {
        "@context": "http://iiif.io/api/image/3/context.json",
        "id": base_url,
        "type": "ImageService3",
        "protocol": "http://iiif.io/api/image",
        "profile": "level1",
        "width": width,
        "height": height,
        "extraFeatures": ["sizeByConfinedWh"],
    }
