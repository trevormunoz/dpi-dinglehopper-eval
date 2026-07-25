"""IIIF Presentation manifest fetch and parse (v2 and v3).

Prior art: iiif_ocr's iiif_models.py (v2 dataclasses) — drafted on, not
depended on (its PaddleOCR/OpenCV chain is far too heavy for the offline
wheelhouse, and it is v2-only where we need v3 too).
"""

import json
import re
import unicodedata
import urllib.request
from dataclasses import dataclass


class IIIFError(Exception):
    pass


@dataclass
class CanvasRecord:
    canvas_id: str
    label: str
    image_url: str
    image_service: str | None


def fetch_manifest(url: str, timeout: float = 30.0) -> dict:
    if not url.startswith("https://"):
        raise IIIFError("Manifest URL must be https:// — got: " + url)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — every failure is a create-time error
        raise IIIFError(f"Could not fetch manifest {url}: {exc}") from exc


def _v3_label(label) -> str:
    if isinstance(label, dict) and label:
        first_lang = next(iter(label.values()))
        if isinstance(first_lang, list) and first_lang:
            return str(first_lang[0])
    return str(label or "")


def _service_id(service) -> str | None:
    if isinstance(service, list):
        service = service[0] if service else None
    if isinstance(service, dict):
        return service.get("@id") or service.get("id")
    return None


def parse_manifest(doc: dict) -> list[CanvasRecord]:
    records: list[CanvasRecord] = []
    canvas_count = 0
    if "sequences" in doc:  # Presentation v2
        for seq in doc.get("sequences", []):
            for canvas in seq.get("canvases", []):
                canvas_count += 1
                images = canvas.get("images", [])
                if not images:
                    continue
                resource = images[0].get("resource", {})
                records.append(CanvasRecord(
                    canvas_id=canvas.get("@id", ""),
                    label=str(canvas.get("label") or ""),
                    image_url=resource.get("@id", ""),
                    image_service=_service_id(resource.get("service")),
                ))
    else:  # Presentation v3
        for canvas in doc.get("items", []):
            if canvas.get("type") != "Canvas":
                continue
            canvas_count += 1
            body = None
            for page in canvas.get("items", []):
                for anno in page.get("items", []):
                    body_candidate = anno.get("body")
                    if isinstance(body_candidate, list) and body_candidate \
                            and isinstance(body_candidate[0], dict):
                        body_candidate = body_candidate[0]
                    if isinstance(body_candidate, dict):
                        body = body_candidate
                        break
                if body:
                    break
            if body is None:
                continue
            records.append(CanvasRecord(
                canvas_id=canvas.get("id", ""),
                label=_v3_label(canvas.get("label")),
                image_url=body.get("id", ""),
                image_service=_service_id(body.get("service")),
            ))
    if not records:
        raise IIIFError("Manifest contains no canvases with images.")
    if len(records) != canvas_count:
        raise IIIFError(
            f"Manifest has {canvas_count} canvases but only {len(records)} "
            "with a usable image. Page numbering would drift against "
            "page_{i}-style OCR — this manifest cannot be used as-is.")
    return records


def _slugify(label: str) -> str:
    ascii_label = (
        unicodedata.normalize("NFKD", label)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_label).strip("-")
    return slug[:40]


def make_stem(index: int, label: str) -> str:
    """0-based, zero-padded stem. The trailing/embedded index is the
    alignment key against iiif_ocr's page_{i} output — do not change the
    base without changing alignment.py and its off-by-one regression test."""
    slug = _slugify(label)
    return f"p{index:04d}-{slug}" if slug else f"p{index:04d}"
