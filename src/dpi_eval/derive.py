"""IIIF Image API level-1 derivation over local masters (Pillow).

Engine choice per spec: Pillow, not shell-side Rust (thin-shell rule;
Rust has no native JP2 — it would bind the same C OpenJPEG Pillow
bundles). Performance ladder if pilot-measured decode latency hurts:
pyvips behind this same interface.

Declared capability = implemented capability: level 1 plus
sizeByConfinedWh (!w,h). Rotation other than 0, qualities other than
default, and formats other than jpg are rejected with 400.
"""

import hashlib
import re
from pathlib import Path

from PIL import Image

_REGION = re.compile(r"^(\d+),(\d+),(\d+),(\d+)$")
_SIZE_W = re.compile(r"^(\d+),$")
_SIZE_H = re.compile(r"^,(\d+)$")
_SIZE_CONFINED = re.compile(r"^!(\d+),(\d+)$")


class DeriveError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


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
        parsed_size = ("w", int(m.group(1)))
    elif m := _SIZE_H.match(size):
        parsed_size = ("h", int(m.group(1)))
    elif m := _SIZE_CONFINED.match(size):
        parsed_size = ("confined", int(m.group(1)), int(m.group(2)))
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
                    ratio = spec[1] / img.width
                    img = img.resize((spec[1], max(1, round(img.height * ratio))))
                elif spec[0] == "h":
                    ratio = spec[1] / img.height
                    img = img.resize((max(1, round(img.width * ratio)), spec[1]))
                else:  # confined !w,h
                    img.thumbnail((spec[1], spec[2]))
            tmp = out.with_suffix(".tmp")
            img.save(tmp, format="JPEG", quality=90)
            tmp.replace(out)
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
