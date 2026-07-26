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


# A large but real-world book manifest (thousands of canvases, full IIIF
# service blocks, multi-language label maps) weighs a few MB at most; 10 MB
# leaves generous headroom while still capping worst-case memory use for a
# create-time HTTP fetch.
_MAX_MANIFEST_BYTES = 10 * 1024 * 1024


class _NoInsecureRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuses to follow a redirect to a non-https:// URL.

    Plain urlopen()/the default opener follow https:// -> http://
    redirects transparently (HTTPRedirectHandler doesn't care about
    scheme), which is an SSRF shape: a manifest host that 302s to an
    internal http:// address gets fetched before we ever get a chance to
    inspect the response. Raising here happens inside redirect_request,
    before the new request is ever issued — so the insecure target is
    never contacted.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise IIIFError(
                "Manifest fetch redirected to a non-https:// URL — "
                f"refusing to follow: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Built once at import time; build_opener() sees _NoInsecureRedirectHandler
# is a subclass of the default HTTPRedirectHandler and uses it in place of
# the default, rather than installing both.
_opener = urllib.request.build_opener(_NoInsecureRedirectHandler)


def fetch_manifest(url: str, timeout: float = 30.0) -> dict:
    if not url.startswith("https://"):
        raise IIIFError("Manifest URL must be https:// — got: " + url)
    try:
        with _opener.open(url, timeout=timeout) as resp:
            # Belt-and-braces: _NoInsecureRedirectHandler already refuses to
            # follow an insecure redirect before it is issued. Re-check the
            # final URL too, in case some other handler path we haven't
            # anticipated lets one through.
            final_url = resp.geturl()
            if not final_url.startswith("https://"):
                raise IIIFError(
                    "Manifest fetch redirected to a non-https:// URL — "
                    f"refusing to follow: {final_url}")
            body = resp.read(_MAX_MANIFEST_BYTES + 1)
            if len(body) > _MAX_MANIFEST_BYTES:
                raise IIIFError(
                    f"Manifest at {url} exceeds the "
                    f"{_MAX_MANIFEST_BYTES} byte limit — refusing to read "
                    "further.")
            return json.loads(body.decode("utf-8"))
    except IIIFError:
        raise
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


def _resolve_v3_body(body_candidate):
    """Unwrap the annotation body shapes Presentation v3 allows: a plain
    Image body, a JSON array (first element wins), or a `Choice` (first
    `items` entry wins). Returns a dict, or None if no usable body."""
    if isinstance(body_candidate, list) and body_candidate \
            and isinstance(body_candidate[0], dict):
        body_candidate = body_candidate[0]
    if not isinstance(body_candidate, dict):
        return None
    if body_candidate.get("type") == "Choice":
        choices = body_candidate.get("items")
        if not isinstance(choices, list) or not choices \
                or not isinstance(choices[0], dict):
            return None
        return choices[0]
    return body_candidate


def parse_manifest(doc: dict) -> list[CanvasRecord]:
    records: list[CanvasRecord] = []
    canvas_count = 0
    if "sequences" in doc:  # Presentation v2
        sequences = doc.get("sequences", [])
        if not isinstance(sequences, list):
            raise IIIFError(
                "Manifest 'sequences' must be a list — this manifest is "
                "malformed and cannot be used.")
        for seq in sequences:
            if not isinstance(seq, dict):
                raise IIIFError(
                    "Manifest has a non-object entry in 'sequences' — this "
                    "manifest is malformed and cannot be used.")
            canvases = seq.get("canvases", [])
            if not isinstance(canvases, list):
                raise IIIFError(
                    "Sequence 'canvases' must be a list — this manifest is "
                    "malformed and cannot be used.")
            for canvas in canvases:
                if not isinstance(canvas, dict):
                    raise IIIFError(
                        "Manifest has a non-object entry in 'canvases' — "
                        "this manifest is malformed and cannot be used.")
                canvas_count += 1
                images = canvas.get("images", [])
                if not isinstance(images, list):
                    raise IIIFError(
                        "Canvas 'images' must be a list — this manifest is "
                        "malformed and cannot be used.")
                if not images:
                    continue
                first_image = images[0]
                if not isinstance(first_image, dict):
                    raise IIIFError(
                        "Manifest has a non-object entry in canvas "
                        "'images' — this manifest is malformed and cannot "
                        "be used.")
                resource = first_image.get("resource", {})
                if not isinstance(resource, dict):
                    raise IIIFError(
                        "Image 'resource' must be an object — this "
                        "manifest is malformed and cannot be used.")
                image_url = resource.get("@id", "")
                if not image_url:
                    continue
                records.append(CanvasRecord(
                    canvas_id=canvas.get("@id", ""),
                    label=str(canvas.get("label") or ""),
                    image_url=image_url,
                    image_service=_service_id(resource.get("service")),
                ))
    else:  # Presentation v3
        items = doc.get("items", [])
        if not isinstance(items, list):
            raise IIIFError(
                "Manifest 'items' must be a list — this manifest is "
                "malformed and cannot be used.")
        for canvas in items:
            if not isinstance(canvas, dict):
                raise IIIFError(
                    "Manifest has a non-object entry in 'items' — this "
                    "manifest is malformed and cannot be used.")
            if canvas.get("type") != "Canvas":
                continue
            canvas_count += 1
            body = None
            canvas_items = canvas.get("items", [])
            if not isinstance(canvas_items, list):
                raise IIIFError(
                    "Canvas 'items' must be a list — this manifest is "
                    "malformed and cannot be used.")
            for page in canvas_items:
                if not isinstance(page, dict):
                    raise IIIFError(
                        "Manifest has a non-object entry in canvas "
                        "'items' — this manifest is malformed and cannot "
                        "be used.")
                page_items = page.get("items", [])
                if not isinstance(page_items, list):
                    raise IIIFError(
                        "AnnotationPage 'items' must be a list — this "
                        "manifest is malformed and cannot be used.")
                for anno in page_items:
                    if not isinstance(anno, dict):
                        raise IIIFError(
                            "Manifest has a non-object entry in "
                            "AnnotationPage 'items' — this manifest is "
                            "malformed and cannot be used.")
                    body = _resolve_v3_body(anno.get("body"))
                    if body:
                        break
                if body:
                    break
            image_url = body.get("id", "") if body else ""
            if not image_url:
                continue
            records.append(CanvasRecord(
                canvas_id=canvas.get("id", ""),
                label=_v3_label(canvas.get("label")),
                image_url=image_url,
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
