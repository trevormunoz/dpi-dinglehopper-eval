"""IIIF Presentation manifest fetch and parse (v2 and v3).

Prior art: iiif_ocr's iiif_models.py (v2 dataclasses) — drafted on, not
depended on (its PaddleOCR/OpenCV chain is far too heavy for the offline
wheelhouse, and it is v2-only where we need v3 too).
"""

import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from importlib.metadata import PackageNotFoundError, version as _pkg_version
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


try:
    # The distribution name, not the import package (`dpi_eval`) — they differ.
    _VERSION = _pkg_version("dpi-dinglehopper-eval")
except PackageNotFoundError:  # running from a source tree, not installed
    _VERSION = "0+unknown"

DEFAULT_USER_AGENT = f"dpi-eval/{_VERSION} (+OCR evaluation harness)"


def _user_agent() -> str:
    """The User-Agent to send with a manifest fetch.

    Defaults to identifying ourselves honestly. It is overridable because
    institutional IIIF servers sit behind a WAF that filters on this header,
    and UMD's answers 400 to `Python-urllib/3.11` *and* to an honest
    `dpi-eval/…` — only a browser-shaped string gets through. Mimicking a
    browser by default would make our traffic indistinguishable from a
    student's in the logs that would want to tell them apart, so the honest
    value stays the default and the operator opts into the workaround.

    A blank override falls back rather than sending an empty header: no
    User-Agent at all draws a 403 from the same WAF.
    """
    configured = (os.environ.get("DPI_EVAL_USER_AGENT") or "").strip()
    return configured or DEFAULT_USER_AGENT


def fetch_manifest(url: str, timeout: float = 30.0) -> dict:
    if not url.startswith("https://"):
        raise IIIFError("Manifest URL must be https:// — got: " + url)
    request = urllib.request.Request(
        url, headers={"User-Agent": _user_agent(), "Accept": "application/json"})
    try:
        with _opener.open(request, timeout=timeout) as resp:
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
    except urllib.error.HTTPError as exc:
        # A WAF rejects on the header, never having looked at the path, so a
        # bare "400 Bad Request" sends the user hunting for a typo in a URL
        # that is fine. Name the override on the codes a filter actually uses.
        hint = ""
        if exc.code in (400, 401, 403, 406, 429):
            hint = (
                f" The server may be filtering on User-Agent (we sent "
                f"{_user_agent()!r}). If this manifest opens in a browser, set "
                "DPI_EVAL_USER_AGENT to a value the server accepts and try "
                "again.")
        raise IIIFError(
            f"Could not fetch manifest {url}: HTTP {exc.code} "
            f"{exc.reason}.{hint}") from exc
    except Exception as exc:  # noqa: BLE001 — every failure is a create-time error
        raise IIIFError(f"Could not fetch manifest {url}: {exc}") from exc


def _v3_label(label) -> str:
    if isinstance(label, dict) and label:
        first_lang = next(iter(label.values()))
        if isinstance(first_lang, list) and first_lang:
            return str(first_lang[0])
    return str(label or "")


def _require_str_id(value, what: str) -> str:
    """Type-check one scalar id pulled out of a manifest; "" if absent.

    The isinstance guards below prove the shape of the *containers*; they say
    nothing about the scalars read out of them, and every id here is treated
    as a URL string downstream — image_url/image_service get formatted into
    Image API URLs and .startswith()-checked by the editor, canvas_id lands in
    session.json and the export rows. A non-string id is truthy, so an
    emptiness check waves it through and the page it creates can never be
    opened.

    Raising rather than coercing to "" is deliberate: an id of the wrong type
    is a malformed manifest, like every other shape violation in this module,
    not a canvas that honestly has no image. Both dispositions reject the
    manifest (a coerced "" would trip the canvas-count guard), but only this
    one names the real fault instead of blaming a missing image.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise IIIFError(
            f"Manifest {what} must be a string — this manifest is malformed "
            "and cannot be used.")
    return value


def _service_id(service) -> str | None:
    if isinstance(service, list):
        service = service[0] if service else None
    if isinstance(service, dict):
        service_id = (
            _require_str_id(service.get("@id"), "image service '@id'")
            or _require_str_id(service.get("id"), "image service 'id'"))
        return service_id or None
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
    # json.loads returns whatever the host sent — a top-level array, string
    # or number reaches here, and both callers catch IIIFError only, so
    # anything else escapes as a 500 rather than a create-time error.
    if not isinstance(doc, dict):
        raise IIIFError(
            "Manifest is not a JSON object — this manifest is malformed and "
            "cannot be used.")
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
                # Counted first, unconditionally — see the v3 branch below
                # for why nothing may return before this increment.
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
                image_url = _require_str_id(
                    resource.get("@id"), "image resource '@id'")
                if not image_url:
                    continue
                records.append(CanvasRecord(
                    canvas_id=_require_str_id(
                        canvas.get("@id"), "canvas '@id'"),
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
            # Counted first, unconditionally: this increment is the left-hand
            # side of the index-skew guard at the end of this function, so any
            # path that returns before it drops the item from *both* sides of
            # that comparison and the guard goes blind. Anything that would
            # shift a canvas index has to raise, never `continue`.
            canvas_count += 1
            if canvas.get("type") != "Canvas":
                raise IIIFError(
                    "Manifest 'items' has an entry whose type is not "
                    "'Canvas' — skipping it would shift every later page "
                    "index against page_{i}-style OCR, so this manifest "
                    "cannot be used as-is.")
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
            image_url = _require_str_id(
                body.get("id"), "image body 'id'") if body else ""
            if not image_url:
                continue
            records.append(CanvasRecord(
                canvas_id=_require_str_id(canvas.get("id"), "canvas 'id'"),
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
