# Transcription Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the student-facing transcription editor (sessions from local folders or IIIF manifests, line-for-line typing with versioned conventions, alignment-staged grading, collection-labeled export) per the approved spec `docs/superpowers/specs/2026-07-24-transcription-editor-design.md` (4cd9a0d).

**Architecture:** Four new pure-Python modules beside the engine (`conventions.py`, `iiif.py`, `derive.py`, `alignment.py`) plus a large `sessions.py`, wired into the existing FastAPI app (`web.py`/`pages.py`). The engine (`runner.py`, `pairing.py`) is untouched; grading goes through staged, status-filtered folders. All mutating `/transcribe` routes are token-gated in both modes.

**Tech Stack:** Python ≥3.10, FastAPI, Pillow (new dependency — wheelhouse impact must be stated in the PR), stdlib `urllib` for manifest fetch (open decision #3: resolved as stdlib — zero new wheels), pytest + httpx TestClient.

## Global Constraints

- Never import `dinglehopper` in any new module (engine fence; `web.py:1-4`).
- Self-contained pages: no CDN scripts, no external stylesheets; inline JS/CSS only.
- Line-for-line transcription: `conventions.normalize` PRESERVES interior newlines.
- All mutating `/transcribe` routes require the per-launch token (header `X-DPI-Eval-Token` or form field `token`).
- Session stems for IIIF sources embed the **0-based** canvas index (`p0007-…` = canvas 7 counting from 0), matching iiif_ocr's `page_{i}` naming exactly.
- Editor textarea always carries `spellcheck="false" autocorrect="off" autocapitalize="off"`.
- GT files are named `<stem>.gt.txt`; grading and export only ever read **staged, status-filtered** copies, never raw `gt/`.
- Timestamps: `datetime.now(timezone.utc).isoformat(timespec="seconds")`.
- Commit after every task with a conventional-commit message (commitlint enforced).

---

### Task 1: conventions.py — versioned normalization

**Files:**
- Create: `src/dpi_eval/conventions.py`
- Test: `tests/test_conventions.py`

**Interfaces:**
- Produces: `CONVENTIONS_VERSION: str = "1"`; `normalize(text: str) -> tuple[str, int]` returning `(normalized_text, change_count)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_conventions.py
from dpi_eval.conventions import CONVENTIONS_VERSION, normalize


def test_version_is_stringy_and_stable():
    assert CONVENTIONS_VERSION == "1"


def test_preserves_interior_newlines_line_for_line():
    text = "First line\nSecond line\n"
    out, changes = normalize(text)
    assert out == "First line\nSecond line\n"
    assert changes == 0


def test_crlf_becomes_lf_and_counts_as_change():
    out, changes = normalize("a\r\nb\r\n")
    assert out == "a\nb\n"
    assert changes == 1


def test_strips_trailing_spaces_per_line():
    out, changes = normalize("word   \nnext\n")
    assert out == "word\nnext\n"
    assert changes == 1


def test_nfc_normalization():
    decomposed = "étude\n"  # e + combining acute
    out, changes = normalize(decomposed)
    assert out == "étude\n"
    assert changes == 1


def test_ensures_single_trailing_newline():
    out, changes = normalize("last line")
    assert out == "last line\n"
    assert changes == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_conventions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dpi_eval.conventions'`

- [ ] **Step 3: Write the implementation**

```python
# src/dpi_eval/conventions.py
"""Transcription conventions, applied at save time.

Cornerstone (spec, Trevor 2026-07-24): transcription is LINE-FOR-LINE —
students press Enter at each printed line end, so interior newlines are
data and are never stripped. Rules here normalize within lines only.

Bump CONVENTIONS_VERSION whenever any rule changes; sessions stamped
with a different version become read-only (sessions.py enforces this).
Remaining conventions content (hyphenation, ligatures, long s) is spec
open decision #1 and lands here as new rules + a version bump.
"""

import unicodedata

CONVENTIONS_VERSION = "1"


def normalize(text: str) -> tuple[str, int]:
    """Apply conventions v1. Returns (normalized_text, change_count) where
    change_count is the number of rules that altered the text (not the
    number of characters changed) — surfaced to the student as
    "N changes applied by conventions v1"."""
    changes = 0

    crlf_fixed = text.replace("\r\n", "\n").replace("\r", "\n")
    if crlf_fixed != text:
        changes += 1
    text = crlf_fixed

    nfc = unicodedata.normalize("NFC", text)
    if nfc != text:
        changes += 1
    text = nfc

    stripped = "\n".join(line.rstrip() for line in text.split("\n"))
    if stripped != text:
        changes += 1
    text = stripped

    if text and not text.endswith("\n"):
        text += "\n"
        changes += 1
    while text.endswith("\n\n"):
        text = text[:-1]
        changes += 1

    return text, changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_conventions.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/conventions.py tests/test_conventions.py
git commit -m "feat: versioned transcription conventions (line-for-line, NFC, per-line trailing-space strip)"
```

---

### Task 2: iiif.py — manifest fetch, parse, stems

**Files:**
- Create: `src/dpi_eval/iiif.py`
- Create: `tests/fixtures/manifest_v2.json`, `tests/fixtures/manifest_v3.json`
- Test: `tests/test_iiif.py`

**Interfaces:**
- Produces: `class IIIFError(Exception)`; `@dataclass CanvasRecord(canvas_id: str, label: str, image_url: str, image_service: str | None)`; `fetch_manifest(url: str) -> dict` (https-only, raises `IIIFError`); `parse_manifest(doc: dict) -> list[CanvasRecord]`; `make_stem(index: int, label: str) -> str` (0-based, `p%04d` + slug, index-only fallback).

- [ ] **Step 1: Create fixture manifests**

```json
// tests/fixtures/manifest_v2.json
{
  "@context": "http://iiif.io/api/presentation/2/context.json",
  "@id": "https://iiif.example.edu/m/1",
  "@type": "sc:Manifest",
  "sequences": [{"canvases": [
    {"@id": "https://iiif.example.edu/c/0", "label": "Masthead",
     "images": [{"resource": {
       "@id": "https://iiif.example.edu/i/0/full/full/0/default.jpg",
       "service": {"@id": "https://iiif.example.edu/i/0"}}}]},
    {"@id": "https://iiif.example.edu/c/1", "label": "Page 2",
     "images": [{"resource": {
       "@id": "https://iiif.example.edu/i/1/full/full/0/default.jpg"}}]}
  ]}]
}
```

```json
// tests/fixtures/manifest_v3.json
{
  "@context": "http://iiif.io/api/presentation/3/context.json",
  "id": "https://iiif.example.edu/m/2",
  "type": "Manifest",
  "items": [
    {"id": "https://iiif.example.edu/c3/0", "type": "Canvas",
     "label": {"en": ["Front page"]},
     "items": [{"type": "AnnotationPage", "items": [
       {"type": "Annotation", "body": {
         "id": "https://iiif.example.edu/i3/0/full/max/0/default.jpg",
         "type": "Image",
         "service": [{"id": "https://iiif.example.edu/i3/0", "type": "ImageService3"}]}}]}]},
    {"id": "https://iiif.example.edu/c3/1", "type": "Canvas",
     "label": {"ja": ["日本語"]},
     "items": [{"type": "AnnotationPage", "items": [
       {"type": "Annotation", "body": {
         "id": "https://iiif.example.edu/i3/1/full/max/0/default.jpg",
         "type": "Image"}}]}]}
  ]
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_iiif.py
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_iiif.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dpi_eval.iiif'`

- [ ] **Step 4: Write the implementation**

```python
# src/dpi_eval/iiif.py
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
    if "sequences" in doc:  # Presentation v2
        for seq in doc.get("sequences", []):
            for canvas in seq.get("canvases", []):
                images = canvas.get("images", [])
                if not images:
                    continue
                resource = images[0].get("resource", {})
                records.append(CanvasRecord(
                    canvas_id=canvas.get("@id", ""),
                    label=str(canvas.get("label", "")),
                    image_url=resource.get("@id", ""),
                    image_service=_service_id(resource.get("service")),
                ))
    else:  # Presentation v3
        for canvas in doc.get("items", []):
            if canvas.get("type") != "Canvas":
                continue
            body = None
            for page in canvas.get("items", []):
                for anno in page.get("items", []):
                    if isinstance(anno.get("body"), dict):
                        body = anno["body"]
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_iiif.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/dpi_eval/iiif.py tests/test_iiif.py tests/fixtures/manifest_v2.json tests/fixtures/manifest_v3.json
git commit -m "feat: IIIF manifest fetch/parse (v2+v3) and 0-based canvas stems"
```

---

### Task 3: derive.py — Image API level-1 derivation

**Files:**
- Create: `src/dpi_eval/derive.py`
- Modify: `pyproject.toml` (add `"pillow>=10"` to `[project] dependencies`)
- Test: `tests/test_derive.py`

**Interfaces:**
- Produces: `class DeriveError(Exception)` (has `.status` int); `parse_params(region: str, size: str, rotation: str, quality: str, fmt: str) -> dict`; `derive(master: Path, region: str, size: str, cache_dir: Path) -> Path`; `image_dims(path: Path) -> tuple[int, int]` (header-only); `info_json(base_url: str, width: int, height: int) -> dict` (ImageService3, profile level1, `extraFeatures: ["sizeByConfinedWh"]`).

- [ ] **Step 1: Add Pillow to pyproject**

In `pyproject.toml` `[project] dependencies`, append `"pillow>=10",` after `"uvicorn>=0.29",`. Run `uv sync`. **PR note requirement (spec):** the PR description must state the wheelhouse impact — one Pillow wheel (bundles OpenJPEG for JP2 and libtiff for TIFF).

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_derive.py
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_derive.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dpi_eval.derive'`

- [ ] **Step 4: Write the implementation**

```python
# src/dpi_eval/derive.py
"""IIIF Image API level-1 derivation over local masters (Pillow).

Engine choice per spec: Pillow, not shell-side Rust (thin-shell rule;
Rust has no native JP2 — it would bind the same C OpenJPEG Pillow
bundles). Performance ladder if pilot-measured decode latency hurts:
pyvips behind this same interface.

Declared capability = implemented capability: level 1 plus
sizeByConfinedWh (!w,h). Rotation other than 0, qualities other than
default, and formats other than jpg are rejected with 400.
"""

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
    with Image.open(path) as img:  # lazy: reads headers, not pixel data
        return img.size


def derive(master: Path, region: str, size: str, cache_dir: Path) -> Path:
    params = parse_params(region, size, "0", "default", "jpg")
    key = f"{master.stem}_{region}_{size}".replace(",", "-").replace("!", "c")
    key = re.sub(r"[^A-Za-z0-9_-]", "_", key)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{key}.jpg"
    if out.exists():
        return out

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_derive.py -v`
Expected: 7 passed (or 6 passed + 1 skipped if the local Pillow lacks OpenJPEG — the wheelhouse Pillow has it)

- [ ] **Step 6: Commit**

```bash
git add src/dpi_eval/derive.py tests/test_derive.py pyproject.toml uv.lock
git commit -m "feat: Image API level-1 derivation (Pillow, cached, region+size, info.json)"
```

---

### Task 4: alignment.py — OCR-to-page mapping

**Files:**
- Create: `src/dpi_eval/alignment.py`
- Test: `tests/test_alignment.py`

**Interfaces:**
- Consumes: nothing from other new modules.
- Produces: `OCR_STAGE_EXTENSIONS = {".hocr": ".hocr", ".xml": ".xml", ".txt": ".txt"}`; `trailing_int(stem: str) -> int | None`; `align(pages: list[dict], filenames: list[str], by: str) -> dict` where `by` is `"index"` or `"stem"`, `pages` are session page dicts (need keys `stem`, `source_index`), and the return is `{"matched": {stem: filename}, "unmatched_pages": [stem], "unmatched_files": [filename], "ignored": [filename]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_alignment.py
from dpi_eval.alignment import align, trailing_int


def _pages(indices):
    return [{"stem": f"p{i:04d}-label", "source_index": i} for i in indices]


def test_trailing_int():
    assert trailing_int("page_0") == 0
    assert trailing_int("page_11") == 11
    assert trailing_int("0042_scan") is None
    assert trailing_int("cover") is None


def test_index_alignment_is_zero_based_no_off_by_one():
    """Regression pin (PAR round 2): iiif_ocr writes page_0.hocr for the
    FIRST canvas. p0000-* must pair page_0.hocr, never page_1.hocr."""
    files = [f"page_{i}.hocr" for i in range(12)]
    result = align(_pages(range(12)), files, by="index")
    assert result["matched"]["p0000-label"] == "page_0.hocr"
    assert result["matched"]["p0007-label"] == "page_7.hocr"
    assert result["unmatched_pages"] == []
    assert result["unmatched_files"] == []


def test_index_alignment_reports_unmatched_both_sides():
    result = align(_pages([0, 1]), ["page_0.hocr", "vendor-scan-A.hocr"], by="index")
    assert result["matched"] == {"p0000-label": "page_0.hocr"}
    assert result["unmatched_pages"] == ["p0001-label"]
    assert result["unmatched_files"] == ["vendor-scan-A.hocr"]


def test_non_ocr_files_are_ignored_not_reported():
    """iiif_ocr leaves page_N.jpeg / page_N_scaled.jpeg beside its hOCR."""
    result = align(_pages([0]), ["page_0.hocr", "page_0.jpeg", "notes.md"], by="index")
    assert result["matched"] == {"p0000-label": "page_0.hocr"}
    assert result["ignored"] == ["notes.md", "page_0.jpeg"]
    assert result["unmatched_files"] == []


def test_stem_alignment_for_local_sessions():
    pages = [{"stem": "scan-A", "source_index": 0}, {"stem": "scan-B", "source_index": 1}]
    result = align(pages, ["scan-A.xml", "other.txt"], by="stem")
    assert result["matched"] == {"scan-A": "scan-A.xml"}
    assert result["unmatched_pages"] == ["scan-B"]
    assert result["unmatched_files"] == ["other.txt"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_alignment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dpi_eval.alignment'`

- [ ] **Step 3: Write the implementation**

```python
# src/dpi_eval/alignment.py
"""Map OCR (or draft) files to session pages.

IIIF sessions align by canvas index — source_index is 0-based over all
canvases, matching iiif_ocr's page_{i} naming exactly (spec-pinned; see
the off-by-one regression test). Local sessions align by stem equality.
Auto-alignment is a convenience; the editable preview is the contract —
callers overlay manual overrides on the returned mapping.
"""

import re
from pathlib import Path

# Recognized OCR extensions, mapped to the suffixes pairing.discover_pairs
# accepts. Anything else is ignored (not an error): iiif_ocr leaves
# page_N.jpeg images beside its hOCR output.
OCR_STAGE_EXTENSIONS = {".hocr": ".hocr", ".xml": ".xml", ".txt": ".txt"}

_TRAILING_INT = re.compile(r"(\d+)$")


def trailing_int(stem: str) -> int | None:
    match = _TRAILING_INT.search(stem)
    return int(match.group(1)) if match else None


def align(pages: list[dict], filenames: list[str], by: str) -> dict:
    ocr_files = []
    ignored = []
    for name in sorted(filenames):
        if Path(name).suffix.lower() in OCR_STAGE_EXTENSIONS:
            ocr_files.append(name)
        else:
            ignored.append(name)

    matched: dict[str, str] = {}
    used: set[str] = set()
    for page in pages:
        candidate = None
        if by == "index":
            for name in ocr_files:
                if trailing_int(Path(name).stem) == page["source_index"]:
                    candidate = name
                    break
        else:
            for name in ocr_files:
                if Path(name).stem == page["stem"]:
                    candidate = name
                    break
        if candidate and candidate not in used:
            matched[page["stem"]] = candidate
            used.add(candidate)

    return {
        "matched": matched,
        "unmatched_pages": [p["stem"] for p in pages if p["stem"] not in matched],
        "unmatched_files": [n for n in ocr_files if n not in used],
        "ignored": ignored,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_alignment.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/alignment.py tests/test_alignment.py
git commit -m "feat: OCR-to-page alignment (0-based index for IIIF, stem for local)"
```

---

### Task 5: sessions.py — model, create, confirm, list

**Files:**
- Create: `src/dpi_eval/sessions.py`
- Test: `tests/test_sessions_create.py`

**Interfaces:**
- Consumes: `iiif.CanvasRecord`, `iiif.make_stem`, `alignment.align`, `conventions.CONVENTIONS_VERSION`.
- Produces (used by every later task):
  - `class SessionError(Exception)` (`.message`)
  - `IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2"}`
  - `transcriptions_root(base_dir: Path) -> Path` → `base_dir / "transcriptions"`
  - `new_session_id() -> str` → `s-YYYYMMDD-HHMMSS-<4 hex>`
  - `create_local_session(root, folder: Path, mode: str, collection: str, draft_source: Path | None) -> dict` — draft state, full enumeration
  - `create_iiif_session(root, manifest_url: str, records: list[CanvasRecord], mode, collection) -> dict`
  - `confirm_session(root, session_id: str, selected_indices: list[int]) -> dict`
  - `load_session(root, session_id: str) -> dict` / `save_session(root, session: dict) -> None` (atomic) / `list_sessions(root) -> list[dict]`
  - `session_dir(root, session_id) -> Path`; GT folder is `session_dir / "gt"`
  - `detect_draft_format(path: Path) -> str` → `"hocr" | "txt" | "rejected"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sessions_create.py
from pathlib import Path

import pytest
from PIL import Image

from dpi_eval.conventions import CONVENTIONS_VERSION
from dpi_eval.iiif import CanvasRecord
from dpi_eval.sessions import (
    SessionError, confirm_session, create_iiif_session, create_local_session,
    detect_draft_format, list_sessions, load_session, transcriptions_root,
)


@pytest.fixture
def root(tmp_path):
    return transcriptions_root(tmp_path)


@pytest.fixture
def image_folder(tmp_path):
    folder = tmp_path / "masters"
    folder.mkdir()
    for name in ("scan-B.tif", "scan-A.jp2", "notes.md", ".DS_Store"):
        (folder / name).write_bytes(b"x")
    return folder


def test_create_local_session_enumerates_images_sorted_draft_state(root, image_folder):
    session = create_local_session(root, image_folder, "from_scratch", "", None)
    assert session["state"] == "draft"
    assert session["mode"] == "from_scratch"
    assert session["conventions_version"] == CONVENTIONS_VERSION
    assert [p["stem"] for p in session["pages"]] == ["scan-A", "scan-B"]
    assert session["pages"][0]["status"] == "pending"
    assert session["pages"][0]["source_index"] == 0


def test_confirm_prunes_to_selection_and_activates(root, image_folder):
    session = create_local_session(root, image_folder, "from_scratch", "diamondback", None)
    confirmed = confirm_session(root, session["id"], [1])
    assert confirmed["state"] == "active"
    assert [p["stem"] for p in confirmed["pages"]] == ["scan-B"]
    reloaded = load_session(root, session["id"])
    assert reloaded["state"] == "active"
    assert reloaded["collection"] == "diamondback"


def test_create_iiif_session_uses_canvas_records(root):
    records = [
        CanvasRecord("https://x/c/0", "Masthead", "https://x/i/0/full/max/0/default.jpg", "https://x/i/0"),
        CanvasRecord("https://x/c/1", "日本語", "https://x/i/1/full/max/0/default.jpg", None),
    ]
    session = create_iiif_session(root, "https://x/m/1", records, "from_scratch", "")
    stems = [p["stem"] for p in session["pages"]]
    assert stems == ["p0000-masthead", "p0001"]
    assert session["pages"][0]["image_url"] == "https://x/i/0/full/max/0/default.jpg"
    assert session["pages"][0]["canvas_id"] == "https://x/c/0"


def test_list_sessions_newest_first(root, image_folder):
    a = create_local_session(root, image_folder, "from_scratch", "", None)
    b = create_local_session(root, image_folder, "corrected", "", image_folder)
    listed = [s["id"] for s in list_sessions(root)]
    assert set(listed) == {a["id"], b["id"]}


def test_detect_draft_format(tmp_path):
    hocr = tmp_path / "a.hocr"
    hocr.write_text('<html><body><div class="ocr_page">x</div></body></html>')
    alto = tmp_path / "b.xml"
    alto.write_text('<?xml version="1.0"?><alto xmlns="x"></alto>')
    page = tmp_path / "c.xml"
    page.write_text('<?xml version="1.0"?><PcGts xmlns="y"></PcGts>')
    txt = tmp_path / "d.txt"
    txt.write_text("plain text")
    assert detect_draft_format(hocr) == "hocr"
    assert detect_draft_format(alto) == "rejected"
    assert detect_draft_format(page) == "rejected"
    assert detect_draft_format(txt) == "txt"


def test_corrected_mode_with_alto_drafts_rejected(root, image_folder, tmp_path):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "scan-A.xml").write_text('<?xml version="1.0"?><alto></alto>')
    with pytest.raises(SessionError):
        create_local_session(root, image_folder, "corrected", "", drafts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sessions_create.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dpi_eval.sessions'`

- [ ] **Step 3: Write the implementation**

```python
# src/dpi_eval/sessions.py
"""Transcription session lifecycle. Files-first: a session is a directory
holding session.json (all metadata) and gt/ (pure normalized text only).

Engine fence: this module never imports dinglehopper. Grading goes
through staged, status-filtered copies (stage_for_grade, Task 7) — the
engine's pairing never reads raw gt/ or session state.
"""

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from dpi_eval.adapter import sniff_format
from dpi_eval.alignment import align
from dpi_eval.conventions import CONVENTIONS_VERSION
from dpi_eval.iiif import CanvasRecord, make_stem

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2"}
_ALTO_PAGE_MARKERS = (b"<alto", b"<PcGts")


class SessionError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def transcriptions_root(base_dir: Path) -> Path:
    root = base_dir / "transcriptions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_dir(root: Path, session_id: str) -> Path:
    if not re.fullmatch(r"s-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", session_id):
        raise SessionError("No such session.")
    return root / session_id


def new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"s-{stamp}-{secrets.token_hex(2)}"


def save_session(root: Path, session: dict) -> None:
    target = session_dir(root, session["id"]) / "session.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def load_session(root: Path, session_id: str) -> dict:
    path = session_dir(root, session_id) / "session.json"
    if not path.exists():
        raise SessionError("No such session.")
    return json.loads(path.read_text(encoding="utf-8"))


def list_sessions(root: Path) -> list[dict]:
    sessions = []
    for path in sorted(root.glob("s-*/session.json"), reverse=True):
        try:
            sessions.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sessions


def detect_draft_format(path: Path) -> str:
    """hOCR and plain text are usable draft formats; ALTO/PAGE are
    rejected — the editor has no dinglehopper downstream to parse them
    (adapter passes XML through by design). Root-element sniff wins over
    extension, so hOCR delivered as .xml still passes."""
    if sniff_format(path) == "hocr":
        return "hocr"
    head = path.read_bytes()[:4096]
    if any(marker in head for marker in _ALTO_PAGE_MARKERS):
        return "rejected"
    return "txt" if path.suffix.lower() == ".txt" else "rejected"


def _page_record(stem: str, index: int) -> dict:
    return {
        "stem": stem, "status": "pending", "no_text_reason": None,
        "flagged": False, "note": "", "canvas_id": None, "image_url": None,
        "image_service": None, "label": "", "source_index": index,
        "seconds_elapsed": 0, "seconds_active": 0, "saved_at": None,
        "last_nonce": None, "draft_file": None,
    }


def _validate_drafts(pages: list[dict], draft_source: Path, by: str) -> None:
    files = [p.name for p in sorted(draft_source.iterdir()) if p.is_file()]
    for name in files:
        candidate = draft_source / name
        if candidate.suffix.lower() in (".hocr", ".xml", ".txt"):
            if detect_draft_format(candidate) == "rejected":
                raise SessionError(
                    f"Draft file {name} is ALTO/PAGE XML, which the editor "
                    "cannot display as text. Correction drafts must be hOCR "
                    "or plain .txt in v1."
                )
    result = align(pages, files, by=by)
    for page in pages:
        page["draft_file"] = result["matched"].get(page["stem"])


def _base_session(mode: str, collection: str, source: dict) -> dict:
    if mode not in ("from_scratch", "corrected"):
        raise SessionError(f"Unknown mode: {mode}")
    return {
        "id": new_session_id(), "created": _now(), "state": "draft",
        "mode": mode, "collection": collection.strip(),
        "source": source, "conventions_version": CONVENTIONS_VERSION,
        "draft_source": None, "pages": [],
    }


def create_local_session(
    root: Path, folder: Path, mode: str, collection: str,
    draft_source: Path | None,
) -> dict:
    if not folder.is_dir():
        raise SessionError(f"Not a readable folder: {folder}")
    images = sorted(
        p for p in folder.iterdir()
        if p.is_file() and not p.name.startswith(".")
        and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise SessionError("That folder contains no page images.")
    session = _base_session(mode, collection, {"type": "local", "path": str(folder)})
    session["pages"] = [_page_record(p.stem, i) for i, p in enumerate(images)]
    for page, path in zip(session["pages"], images):
        page["image_file"] = path.name
    if mode == "corrected":
        if draft_source is None or not draft_source.is_dir():
            raise SessionError("Correction mode needs a draft folder.")
        session["draft_source"] = str(draft_source)
        _validate_drafts(session["pages"], draft_source, by="stem")
    save_session(root, session)
    return session


def create_iiif_session(
    root: Path, manifest_url: str, records: list[CanvasRecord],
    mode: str, collection: str, draft_source: Path | None = None,
) -> dict:
    session = _base_session(
        mode, collection, {"type": "iiif", "manifest_url": manifest_url})
    for i, record in enumerate(records):
        page = _page_record(make_stem(i, record.label), i)
        page.update(canvas_id=record.canvas_id, image_url=record.image_url,
                    image_service=record.image_service, label=record.label)
        session["pages"].append(page)
    stems = [p["stem"] for p in session["pages"]]
    if len(stems) != len(set(stems)):
        raise SessionError("Manifest produced colliding page stems.")
    if mode == "corrected":
        if draft_source is None or not draft_source.is_dir():
            raise SessionError("Correction mode needs a draft folder.")
        session["draft_source"] = str(draft_source)
        _validate_drafts(session["pages"], draft_source, by="index")
    save_session(root, session)
    return session


def confirm_session(root: Path, session_id: str, selected_indices: list[int]) -> dict:
    session = load_session(root, session_id)
    if session["state"] != "draft":
        raise SessionError("Session is already confirmed.")
    if not selected_indices:
        raise SessionError("Select at least one page.")
    keep = set(selected_indices)
    session["pages"] = [p for p in session["pages"] if p["source_index"] in keep]
    session["state"] = "active"
    save_session(root, session)
    return session
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sessions_create.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/sessions.py tests/test_sessions_create.py
git commit -m "feat: session model — draft/confirm lifecycle, local and IIIF creation, draft validation"
```

---

### Task 6: sessions.py — save/no-text/flag transitions, timing, reconciliation

**Files:**
- Modify: `src/dpi_eval/sessions.py` (append)
- Modify: `src/dpi_eval/adapter.py:6-8` (amend the deletability comment)
- Test: `tests/test_sessions_transitions.py`

**Interfaces:**
- Consumes: Task 5's `load_session`/`save_session`/`session_dir`; `conventions.normalize`; `adapter.hocr_to_text`.
- Produces:
  - `gt_path(root, session, page) -> Path` → `session_dir / "gt" / f"{stem}.gt.txt"`
  - `save_page(root, session_id, source_index, text, *, elapsed: int, active: int, nonce: str) -> tuple[dict, int]` — returns (session, conventions change count); GT written atomically FIRST, session.json second; timing accumulates unless nonce repeats
  - `mark_no_text(root, session_id, source_index, reason: str) -> dict` — reason in `{"blank","image_only","illegible"}`, deletes GT file
  - `set_flag(root, session_id, source_index, flagged: bool, note: str) -> dict`
  - `reconcile(root, session: dict) -> list[dict]` — needs-attention items `{"stem", "problem": "orphan_gt" | "missing_gt"}`
  - `resolve_attention(root, session_id, source_index, action: str)` — `"adopt"` (status→saved) or `"discard"` (delete GT, status→pending)
  - `check_version(session)` — raises `SessionError` when `session["conventions_version"] != CONVENTIONS_VERSION` (called by every mutator)
  - `draft_text(session, page) -> str` — hOCR via `adapter.hocr_to_text`, `.txt` read through, `""` when no draft
  - `page_by_index(session, source_index) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sessions_transitions.py
import json
from pathlib import Path

import pytest

from dpi_eval.sessions import (
    SessionError, create_local_session, confirm_session, gt_path,
    load_session, mark_no_text, page_by_index, reconcile, resolve_attention,
    save_page, session_dir, set_flag, transcriptions_root,
)


@pytest.fixture
def active_session(tmp_path):
    folder = tmp_path / "masters"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        (folder / name).write_bytes(b"x")
    root = transcriptions_root(tmp_path)
    session = create_local_session(root, folder, "from_scratch", "", None)
    confirm_session(root, session["id"], [0, 1])
    return root, session["id"]


def test_save_page_writes_normalized_gt_and_accumulates_timing(active_session):
    root, sid = active_session
    session, changes = save_page(root, sid, 0, "Line one   \nLine two",
                                 elapsed=30, active=20, nonce="n1")
    page = page_by_index(session, 0)
    assert page["status"] == "saved"
    assert changes == 2  # trailing spaces + missing final newline
    assert gt_path(root, session, page).read_text(encoding="utf-8") == "Line one\nLine two\n"
    session, _ = save_page(root, sid, 0, "Line one\nLine two\n",
                           elapsed=15, active=10, nonce="n2")
    page = page_by_index(session, 0)
    assert page["seconds_elapsed"] == 45   # accumulated, never replaced
    assert page["seconds_active"] == 30


def test_retried_nonce_does_not_double_count(active_session):
    root, sid = active_session
    save_page(root, sid, 0, "x\n", elapsed=30, active=20, nonce="n1")
    session, _ = save_page(root, sid, 0, "x\n", elapsed=30, active=20, nonce="n1")
    assert page_by_index(session, 0)["seconds_elapsed"] == 30


def test_no_text_requires_reason_and_deletes_gt(active_session):
    root, sid = active_session
    session, _ = save_page(root, sid, 0, "typed then retracted\n",
                           elapsed=5, active=5, nonce="n1")
    path = gt_path(root, session, page_by_index(session, 0))
    assert path.exists()
    session = mark_no_text(root, sid, 0, "image_only")
    page = page_by_index(session, 0)
    assert page["status"] == "no_text"
    assert page["no_text_reason"] == "image_only"
    assert not path.exists()  # stale GT never survives a retraction
    with pytest.raises(SessionError):
        mark_no_text(root, sid, 1, "because")


def test_flag_is_orthogonal_to_status(active_session):
    root, sid = active_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="n")
    session = set_flag(root, sid, 0, True, "unsure about ligature")
    page = page_by_index(session, 0)
    assert page["status"] == "saved" and page["flagged"] is True


def test_reconcile_finds_orphan_and_missing_gt(active_session):
    root, sid = active_session
    session, _ = save_page(root, sid, 0, "kept\n", elapsed=1, active=1, nonce="n")
    # Crash sim 1: GT written for a page whose record still says pending.
    orphan = session_dir(root, sid) / "gt" / "b.gt.txt"
    orphan.write_text("orphan\n", encoding="utf-8")
    # Crash sim 2: saved page whose GT file vanished.
    gt_path(root, session, page_by_index(session, 0)).unlink()
    problems = {(p["stem"], p["problem"]) for p in reconcile(root, load_session(root, sid))}
    assert problems == {("b", "orphan_gt"), ("a", "missing_gt")}


def test_resolve_attention_adopt_and_discard(active_session):
    root, sid = active_session
    orphan = session_dir(root, sid) / "gt" / "b.gt.txt"
    orphan.write_text("orphan\n", encoding="utf-8")
    session = resolve_attention(root, sid, 1, "adopt")
    assert page_by_index(session, 1)["status"] == "saved"
    session = resolve_attention(root, sid, 1, "discard")
    assert page_by_index(session, 1)["status"] == "pending"
    assert not orphan.exists()


def test_version_mismatch_makes_session_read_only(active_session):
    root, sid = active_session
    session = load_session(root, sid)
    session["conventions_version"] = "0-old"
    from dpi_eval.sessions import save_session
    save_session(root, session)
    with pytest.raises(SessionError):
        save_page(root, sid, 0, "x\n", elapsed=1, active=1, nonce="n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sessions_transitions.py -v`
Expected: FAIL with `ImportError: cannot import name 'save_page'`

- [ ] **Step 3: Append the implementation to sessions.py**

```python
# append to src/dpi_eval/sessions.py
from dpi_eval.adapter import hocr_to_text  # noqa: E402  (module top in practice)
from dpi_eval.conventions import normalize  # noqa: E402

NO_TEXT_REASONS = ("blank", "image_only", "illegible")


def page_by_index(session: dict, source_index: int) -> dict:
    for page in session["pages"]:
        if page["source_index"] == source_index:
            return page
    raise SessionError("No such page in this session.")


def gt_path(root: Path, session: dict, page: dict) -> Path:
    return session_dir(root, session["id"]) / "gt" / f"{page['stem']}.gt.txt"


def check_version(session: dict) -> None:
    if session["conventions_version"] != CONVENTIONS_VERSION:
        raise SessionError(
            f"This session was created under conventions "
            f"v{session['conventions_version']}; the app now runs "
            f"v{CONVENTIONS_VERSION}. The session is read-only — export "
            "what exists and start a new session."
        )


def _mutable(root: Path, session_id: str) -> dict:
    session = load_session(root, session_id)
    if session["state"] != "active":
        raise SessionError("Session is not confirmed yet.")
    check_version(session)
    return session


def save_page(
    root: Path, session_id: str, source_index: int, text: str,
    *, elapsed: int, active: int, nonce: str,
) -> tuple[dict, int]:
    session = _mutable(root, session_id)
    page = page_by_index(session, source_index)
    normalized, changes = normalize(text)
    if not normalized.strip():
        raise SessionError(
            'The transcription is empty — use "No text on this page" instead.')
    # Write order is fixed (spec): GT file first, session.json second.
    target = gt_path(root, session, page)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(normalized, encoding="utf-8")
    os.replace(tmp, target)
    page["status"] = "saved"
    page["no_text_reason"] = None
    page["saved_at"] = _now()
    if nonce != page.get("last_nonce"):
        page["seconds_elapsed"] += max(0, int(elapsed))
        page["seconds_active"] += max(0, int(active))
        page["last_nonce"] = nonce
    save_session(root, session)
    return session, changes


def mark_no_text(root: Path, session_id: str, source_index: int, reason: str) -> dict:
    if reason not in NO_TEXT_REASONS:
        raise SessionError(
            "Pick why there is no text: blank, image-only, or illegible.")
    session = _mutable(root, session_id)
    page = page_by_index(session, source_index)
    target = gt_path(root, session, page)
    if target.exists():
        target.unlink()  # a retracted page must never be graded
    page["status"] = "no_text"
    page["no_text_reason"] = reason
    page["saved_at"] = _now()
    save_session(root, session)
    return session


def set_flag(root: Path, session_id: str, source_index: int,
             flagged: bool, note: str) -> dict:
    session = _mutable(root, session_id)
    page = page_by_index(session, source_index)
    page["flagged"] = bool(flagged)
    page["note"] = note.strip()
    save_session(root, session)
    return session


def reconcile(root: Path, session: dict) -> list[dict]:
    """Compare gt/ against session.json. Grading is blocked while any
    item is returned (stage_for_grade enforces)."""
    problems = []
    gt_dir = session_dir(root, session["id"]) / "gt"
    on_disk = {p.name[: -len(".gt.txt")] for p in gt_dir.glob("*.gt.txt")} if gt_dir.exists() else set()
    for page in session["pages"]:
        if page["status"] == "saved" and page["stem"] not in on_disk:
            problems.append({"stem": page["stem"], "problem": "missing_gt"})
        if page["status"] != "saved" and page["stem"] in on_disk:
            problems.append({"stem": page["stem"], "problem": "orphan_gt"})
    return problems


def resolve_attention(root: Path, session_id: str, source_index: int,
                      action: str) -> dict:
    session = _mutable(root, session_id)
    page = page_by_index(session, source_index)
    target = gt_path(root, session, page)
    if action == "adopt":
        if not target.exists():
            raise SessionError("Nothing on disk to adopt for that page.")
        page["status"] = "saved"
        page["no_text_reason"] = None
        page["saved_at"] = _now()
    elif action == "discard":
        if target.exists():
            target.unlink()
        page["status"] = "pending"
        page["saved_at"] = None
    else:
        raise SessionError("Resolve with adopt or discard.")
    save_session(root, session)
    return session


def draft_text(session: dict, page: dict) -> str:
    if not session.get("draft_source") or not page.get("draft_file"):
        return ""
    path = Path(session["draft_source"]) / page["draft_file"]
    if not path.exists():
        return ""
    if detect_draft_format(path) == "hocr":
        return hocr_to_text(path)
    return path.read_text(encoding="utf-8", errors="replace")
```

Move the two `from dpi_eval...` imports added above to the top of `sessions.py` with the existing imports (the `# noqa` comments are only markers for this step; delete them when relocating).

- [ ] **Step 4: Amend adapter.py's deletability comment**

In `src/dpi_eval/adapter.py`, replace lines 7–8:

```python
This shim is intentionally deletable: if dinglehopper gains hOCR support
upstream (see docs/findings.md #2), remove this module and pass paths through.
```

with:

```python
Deletability contract (amended 2026-07-24): if dinglehopper gains hOCR
support upstream (docs/findings.md #2), the grading path can pass
through — BUT sessions.py now also consumes hocr_to_text/sniff_format
for correction-draft prefill, which needs actual text, not a path
dinglehopper can parse. Deleting this module requires replacing that
consumer too.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sessions_transitions.py tests/test_adapter.py -v`
Expected: all passed (adapter tests confirm the comment change broke nothing)

- [ ] **Step 6: Commit**

```bash
git add src/dpi_eval/sessions.py src/dpi_eval/adapter.py tests/test_sessions_transitions.py
git commit -m "feat: page transitions own GT files — save/no-text/flag, timing nonces, crash reconciliation"
```

---

### Task 7: sessions.py — grade staging and export bundle

**Files:**
- Modify: `src/dpi_eval/sessions.py` (append)
- Test: `tests/test_sessions_staging.py`

**Interfaces:**
- Consumes: Task 6's functions; `alignment.align`, `alignment.OCR_STAGE_EXTENSIONS`.
- Produces:
  - `stage_ocr(root, session_id, files: list[tuple[str, bytes]]) -> dict` — writes `staging/ocr/`, computes alignment (`by="index"` for iiif, `"stem"` for local), persists `staging/alignment.json`, returns the alignment dict
  - `stage_for_grade(root, session_id, overrides: dict[str, str]) -> tuple[Path, Path]` — returns `(staged_gt_dir, staged_ocr_dir)`; raises `SessionError` when reconcile is non-empty or no page is saved; GT staged **only** for `saved` pages; OCR copied as `<stem><normalized-ext>`
  - `clear_staging(root, session_id) -> None`
  - `export_session(root, session_id) -> Path` — builds `export/<collection|_unsorted>/<sid>/{gt/, transcriptions.json}` under the session dir and returns a zip path

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sessions_staging.py
import json
import zipfile
from pathlib import Path

import pytest

from dpi_eval.iiif import CanvasRecord
from dpi_eval.sessions import (
    SessionError, confirm_session, create_iiif_session, export_session,
    load_session, mark_no_text, save_page, session_dir, stage_for_grade,
    stage_ocr, transcriptions_root,
)


@pytest.fixture
def iiif_session(tmp_path):
    root = transcriptions_root(tmp_path)
    records = [
        CanvasRecord(f"https://x/c/{i}", f"Page {i}",
                     f"https://x/i/{i}/full/max/0/default.jpg", None)
        for i in range(3)
    ]
    session = create_iiif_session(root, "https://x/m", records, "from_scratch", "diamondback")
    confirm_session(root, session["id"], [0, 1, 2])
    return root, session["id"]


def test_stage_ocr_aligns_by_index_and_persists(iiif_session):
    root, sid = iiif_session
    files = [(f"page_{i}.hocr", b"<div class='ocr_page'>x</div>") for i in range(3)]
    result = stage_ocr(root, sid, files)
    assert result["matched"]["p0000-page-0"] == "page_0.hocr"
    saved = json.loads((session_dir(root, sid) / "staging" / "alignment.json").read_text())
    assert saved["matched"] == result["matched"]


def test_stage_for_grade_filters_to_saved_and_normalizes_ext(iiif_session):
    root, sid = iiif_session
    save_page(root, sid, 0, "text zero\n", elapsed=1, active=1, nonce="a")
    save_page(root, sid, 1, "text one\n", elapsed=1, active=1, nonce="b")
    mark_no_text(root, sid, 2, "blank")
    # Crash orphan: GT on disk for the no_text page — must NOT be staged.
    orphan = session_dir(root, sid) / "gt" / "p0002-page-2.gt.txt"
    stage_ocr(root, sid, [(f"page_{i}.hocr", b"x") for i in range(3)])
    orphan.write_text("orphan\n")
    with pytest.raises(SessionError):  # needs-attention blocks grading
        stage_for_grade(root, sid, {})
    orphan.unlink()
    gt_dir, ocr_dir = stage_for_grade(root, sid, {})
    assert sorted(p.name for p in gt_dir.iterdir()) == [
        "p0000-page-0.gt.txt", "p0001-page-1.gt.txt"]
    assert sorted(p.name for p in ocr_dir.iterdir()) == [
        "p0000-page-0.hocr", "p0001-page-1.hocr"]


def test_stage_for_grade_applies_manual_overrides(iiif_session):
    root, sid = iiif_session
    save_page(root, sid, 0, "text\n", elapsed=1, active=1, nonce="a")
    stage_ocr(root, sid, [("vendor-weird-name.xml", b"<x/>")])
    gt_dir, ocr_dir = stage_for_grade(root, sid, {"p0000-page-0": "vendor-weird-name.xml"})
    assert (ocr_dir / "p0000-page-0.xml").exists()


def test_stage_for_grade_requires_a_saved_page(iiif_session):
    root, sid = iiif_session
    stage_ocr(root, sid, [("page_0.hocr", b"x")])
    with pytest.raises(SessionError):
        stage_for_grade(root, sid, {})


def test_export_bundle_layout_and_sidecar(iiif_session):
    root, sid = iiif_session
    save_page(root, sid, 0, "kept\n", elapsed=9, active=5, nonce="a")
    mark_no_text(root, sid, 1, "illegible")
    zip_path = export_session(root, sid)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert f"diamondback/{sid}/gt/p0000-page-0.gt.txt" in names
        sidecar = json.loads(zf.read(f"diamondback/{sid}/transcriptions.json"))
    rows = {r["stem"]: r for r in sidecar["pages"]}
    assert rows["p0000-page-0"]["status"] == "saved"
    assert rows["p0000-page-0"]["arm"] == "from_scratch"
    assert rows["p0001-page-1"]["no_text_reason"] == "illegible"
    assert rows["p0002-page-2"]["status"] == "pending"  # every selected page
    assert sidecar["conventions_version"] == load_session(root, sid)["conventions_version"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sessions_staging.py -v`
Expected: FAIL with `ImportError: cannot import name 'stage_ocr'`

- [ ] **Step 3: Append the implementation**

```python
# append to src/dpi_eval/sessions.py
import shutil  # relocate to top-of-file imports
import zipfile  # relocate to top-of-file imports

from dpi_eval.alignment import OCR_STAGE_EXTENSIONS, align  # merge with top import


def _staging(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / "staging"


def clear_staging(root: Path, session_id: str) -> None:
    shutil.rmtree(_staging(root, session_id), ignore_errors=True)


def stage_ocr(root: Path, session_id: str, files: list[tuple[str, bytes]]) -> dict:
    session = _mutable(root, session_id)
    clear_staging(root, session_id)
    ocr_dir = _staging(root, session_id) / "ocr"
    ocr_dir.mkdir(parents=True)
    for name, data in files:
        flat = Path(name).name
        if flat.startswith("."):
            continue
        (ocr_dir / flat).write_bytes(data)
    by = "index" if session["source"]["type"] == "iiif" else "stem"
    result = align(session["pages"], [p.name for p in ocr_dir.iterdir()], by=by)
    (_staging(root, session_id) / "alignment.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    return result


def stage_for_grade(
    root: Path, session_id: str, overrides: dict[str, str]
) -> tuple[Path, Path]:
    session = _mutable(root, session_id)
    problems = reconcile(root, session)
    if problems:
        raise SessionError(
            "Some pages need attention before grading (transcriptions on "
            "disk that don't match the session record). Resolve them from "
            "the session page first.")
    alignment_file = _staging(root, session_id) / "alignment.json"
    if not alignment_file.exists():
        raise SessionError("Upload or pick the OCR folder first (preview step).")
    mapping = json.loads(alignment_file.read_text(encoding="utf-8"))["matched"]
    mapping.update({k: v for k, v in overrides.items() if v})

    saved_pages = [p for p in session["pages"] if p["status"] == "saved"]
    if not saved_pages:
        raise SessionError("No saved transcriptions to grade yet.")

    staged_gt = _staging(root, session_id) / "grade" / "gt"
    staged_ocr = _staging(root, session_id) / "grade" / "ocr"
    for directory in (staged_gt, staged_ocr):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
    ocr_src = _staging(root, session_id) / "ocr"
    for page in saved_pages:
        shutil.copy2(gt_path(root, session, page), staged_gt / f"{page['stem']}.gt.txt")
        ocr_name = mapping.get(page["stem"])
        if ocr_name and (ocr_src / ocr_name).exists():
            ext = OCR_STAGE_EXTENSIONS.get(Path(ocr_name).suffix.lower())
            if ext:
                shutil.copy2(ocr_src / ocr_name, staged_ocr / f"{page['stem']}{ext}")
    return staged_gt, staged_ocr


def export_session(root: Path, session_id: str) -> Path:
    session = load_session(root, session_id)
    problems = reconcile(root, session)
    if problems:
        raise SessionError("Resolve needs-attention pages before exporting.")
    collection = session["collection"] or "_unsorted"
    bundle_root = session_dir(root, session_id) / "export"
    shutil.rmtree(bundle_root, ignore_errors=True)
    bundle = bundle_root / collection / session_id
    (bundle / "gt").mkdir(parents=True)
    for page in session["pages"]:
        if page["status"] == "saved":
            shutil.copy2(gt_path(root, session, page), bundle / "gt" / f"{page['stem']}.gt.txt")
    sidecar = {
        "session_id": session_id,
        "collection": session["collection"],
        "arm": session["mode"],
        "conventions_version": session["conventions_version"],
        "source": session["source"],
        "pages": [
            {"stem": p["stem"], "status": p["status"], "arm": session["mode"],
             "no_text_reason": p["no_text_reason"], "canvas_id": p["canvas_id"],
             "seconds_elapsed": p["seconds_elapsed"],
             "seconds_active": p["seconds_active"], "flagged": p["flagged"],
             "note": p["note"], "saved_at": p["saved_at"]}
            for p in session["pages"]
        ],
    }
    (bundle / "transcriptions.json").write_text(
        json.dumps(sidecar, indent=2), encoding="utf-8")
    zip_path = session_dir(root, session_id) / f"dpi-eval-gt-{session_id}"
    archive = shutil.make_archive(str(zip_path), "zip", root_dir=bundle_root)
    with zipfile.ZipFile(archive):  # smoke-validate the archive
        pass
    return Path(archive)
```

Relocate the `shutil`/`zipfile`/`align` imports to the top of the module.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sessions_staging.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/sessions.py tests/test_sessions_staging.py
git commit -m "feat: staged status-filtered grading inputs and collection-labeled export bundle"
```

---

### Task 8: web.py — token gate + run-registration refactor

**Files:**
- Modify: `src/dpi_eval/web.py` (extract `_run_and_register` from `_grade_pipeline:192-206`; add `_check_token`; browser-mode token in `main`)
- Test: `tests/test_web_token.py`

**Interfaces:**
- Produces:
  - `_run_and_register(gt_dir: Path, ocr_dir: Path, base_dir: Path) -> Path` — creates `run-NNN`, runs `run_batch`, writes `result.json`, returns run dir (the existing results page serves it unchanged)
  - `_check_token(request: Request, form_token: str | None = None) -> None` — raises `HTTPException(403)` unless header `X-DPI-Eval-Token` or `form_token` equals `os.environ["DPI_EVAL_TOKEN"]`; also 403 when the env var is unset
  - `main()` sets `DPI_EVAL_TOKEN` to `secrets.token_urlsafe(24)` when unset (browser mode now always has one; desktop keeps injecting its own)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_token.py
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dpi_eval.web import _check_token, _run_and_register, create_app
from fastapi import HTTPException, Request


def _request(headers: dict) -> Request:
    scope = {"type": "http", "headers": [
        (k.lower().encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


def test_check_token_accepts_header_or_form(monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "sekrit")
    _check_token(_request({"X-DPI-Eval-Token": "sekrit"}))
    _check_token(_request({}), form_token="sekrit")
    with pytest.raises(HTTPException):
        _check_token(_request({}), form_token="wrong")


def test_check_token_denies_when_unset(monkeypatch):
    monkeypatch.delenv("DPI_EVAL_TOKEN", raising=False)
    with pytest.raises(HTTPException):
        _check_token(_request({}), form_token="anything")


def test_run_and_register_writes_result_json(tmp_path):
    gt = tmp_path / "gt"; ocr = tmp_path / "ocr"
    gt.mkdir(); ocr.mkdir()
    (gt / "page_0.gt.txt").write_text("hello world\n")
    (ocr / "page_0.txt").write_text("hello world\n")
    run_dir = _run_and_register(gt, ocr, tmp_path / "runs")
    assert run_dir.name.startswith("run-")
    assert (run_dir / "result.json").exists()


def test_existing_grade_still_works(tmp_path):
    client = TestClient(create_app(tmp_path))
    response = client.post("/grade", files=[
        ("gt_files", ("page_0.gt.txt", b"hello\n")),
        ("ocr_files", ("page_0.txt", b"hello\n"))])
    assert response.status_code in (200, 303)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_token.py -v`
Expected: FAIL with `ImportError: cannot import name '_check_token'`

- [ ] **Step 3: Implement**

In `web.py`: add `import secrets` to imports. Extract the tail of `_grade_pipeline` (from `run_dir = _next_run_dir(base_dir)` handling of the graded folders onward — lines 192–206) into:

```python
def _run_and_register(gt_dir: Path, ocr_dir: Path, base_dir: Path) -> Path:
    """Run the engine over two ready folders and register the run so the
    existing /runs/{id} results page serves it. Shared by _grade_pipeline
    and the transcription grade-confirm route."""
    run_dir = _next_run_dir(base_dir)
    if gt_dir != run_dir / "gt":
        shutil.copytree(gt_dir, run_dir / "gt")
        shutil.copytree(ocr_dir, run_dir / "ocr")
    result, code = run_batch(run_dir / "gt", run_dir / "ocr", run_dir / "reports")
    (run_dir / "result.json").write_text(
        json.dumps({"succeeded": result.succeeded, "failed": result.failed,
                    "missing": result.missing, "exit_code": code}),
        encoding="utf-8")
    return run_dir
```

Rewrite `_grade_pipeline`'s tail: after the pairing pre-check block, replace the `run_batch` + `result.json` lines with `return _run_and_register(run_dir / "gt", run_dir / "ocr", base_dir)` — **but** note `_grade_pipeline` already created its run dir; to avoid a second dir, restructure: `_grade_pipeline` keeps its own `_next_run_dir` + `_save` + pairing pre-check, then calls `run_batch` via a smaller shared helper:

```python
def _register(run_dir: Path) -> Path:
    result, code = run_batch(run_dir / "gt", run_dir / "ocr", run_dir / "reports")
    (run_dir / "result.json").write_text(
        json.dumps({"succeeded": result.succeeded, "failed": result.failed,
                    "missing": result.missing, "exit_code": code}),
        encoding="utf-8")
    return run_dir


def _run_and_register(gt_dir: Path, ocr_dir: Path, base_dir: Path) -> Path:
    run_dir = _next_run_dir(base_dir)
    shutil.copytree(gt_dir, run_dir / "gt")
    shutil.copytree(ocr_dir, run_dir / "ocr")
    return _register(run_dir)
```

and `_grade_pipeline` ends with `return _register(run_dir)`. Add the token helper:

```python
def _check_token(request: Request, form_token: str | None = None) -> None:
    token = os.environ.get("DPI_EVAL_TOKEN")
    supplied = request.headers.get("X-DPI-Eval-Token") or form_token
    if not token or supplied != token:
        raise HTTPException(status_code=403)
```

In `main()`, before `create_app` is called:

```python
    if not os.environ.get("DPI_EVAL_TOKEN"):
        # Browser mode: mint a per-launch token; forms embed it as a
        # hidden field (CSRF), matching the desktop shell's header token.
        os.environ["DPI_EVAL_TOKEN"] = secrets.token_urlsafe(24)
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -x -q`
Expected: all passed (existing `/grade`, `/grade-paths`, results tests confirm the refactor is behavior-preserving)

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/web.py tests/test_web_token.py
git commit -m "refactor: extract run registration; per-launch token in both modes"
```

---

### Task 9: transcribe routes — list, create, confirm + pages

**Files:**
- Modify: `src/dpi_eval/web.py` (new routes inside `create_app`, after the `download` route)
- Modify: `src/dpi_eval/pages.py` (append page functions)
- Modify: `src/dpi_eval/pages.py:183` `form_page` — add a link `<p><a href="/transcribe">Transcribe a sample</a></p>` near the top of the form body
- Test: `tests/test_web_transcribe.py`

**Interfaces:**
- Consumes: `sessions.*` (Tasks 5–7), `iiif.fetch_manifest`/`parse_manifest`, `_check_token`.
- Produces routes: `GET /transcribe`, `POST /transcribe/sessions`, `POST /transcribe/sessions/{sid}/confirm`, `GET /transcribe/sessions/{sid}`.
- Produces pages (all return full HTML strings via `pages._document`): `transcribe_home_page(sessions: list[dict], token: str) -> str`; `selection_page(session: dict, token: str) -> str`; `session_page(session: dict, problems: list[dict], token: str) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_transcribe.py
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dpi_eval.web import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "tok")
    return TestClient(create_app(tmp_path)), tmp_path


@pytest.fixture
def image_folder(tmp_path):
    folder = tmp_path / "masters"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"x")
    (folder / "b.png").write_bytes(b"x")
    return folder


def _create(client, folder, token="tok"):
    return client.post("/transcribe/sessions", data={
        "token": token, "source_type": "local", "folder": str(folder),
        "mode": "from_scratch", "collection": "test-coll"})


def test_transcribe_home_lists_sessions(client):
    c, _ = client
    response = c.get("/transcribe")
    assert response.status_code == 200
    assert "Transcribe" in response.text


def test_create_requires_token(client, image_folder):
    c, _ = client
    assert _create(c, image_folder, token="wrong").status_code == 403


def test_create_renders_selection_then_confirm_activates(client, image_folder):
    c, _ = client
    response = _create(c, image_folder)
    assert response.status_code == 200
    assert 'name="pages"' in response.text  # selection checkboxes
    sid = response.text.split('data-session-id="', 1)[1].split('"', 1)[0]
    confirm = c.post(f"/transcribe/sessions/{sid}/confirm",
                     data={"token": "tok", "pages": ["0", "1"]})
    assert confirm.status_code == 303
    assert confirm.headers["location"] == f"/transcribe/sessions/{sid}"
    summary = c.get(f"/transcribe/sessions/{sid}")
    assert "Page" in summary.text and "a" in summary.text


def test_create_rejects_bad_folder(client, tmp_path):
    c, _ = client
    response = _create(c, tmp_path / "nope")
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_transcribe.py -v`
Expected: FAIL — `GET /transcribe` returns 404

- [ ] **Step 3: Implement pages**

Append to `src/dpi_eval/pages.py` (uses the existing `_document` helper and `html.escape` — add `import html` at top if not present):

```python
def _hidden_token(token: str) -> str:
    return f'<input type="hidden" name="token" value="{html.escape(token or "")}">'


def transcribe_home_page(sessions: list[dict], token: str) -> str:
    rows = "".join(
        f'<li><a href="/transcribe/sessions/{s["id"]}">{s["id"]}</a>'
        f' — {html.escape(s.get("collection") or "no collection")}'
        f' — {s["mode"]} — {s["state"]}</li>'
        for s in sessions
    ) or "<li>No sessions yet.</li>"
    body = f"""
    <h1>Transcribe</h1>
    <h2>Sessions in progress</h2>
    <ul>{rows}</ul>
    <h2>Start a new session</h2>
    <form method="post" action="/transcribe/sessions">
      {_hidden_token(token)}
      <p><label>Source type
        <select name="source_type">
          <option value="local">Local image folder (desktop)</option>
          <option value="iiif">IIIF manifest URL</option>
        </select></label></p>
      <p><label>Local folder path <input name="folder"></label></p>
      <p><label>Manifest URL <input name="manifest_url" placeholder="https://…"></label></p>
      <p><label>Mode
        <select name="mode">
          <option value="from_scratch">Type from scratch</option>
          <option value="corrected">Correct a machine draft</option>
        </select></label></p>
      <p><label>Draft folder (correction mode, desktop) <input name="draft_folder"></label></p>
      <p><label>Collection / handle (optional) <input name="collection"></label></p>
      <p><button type="submit">List pages</button></p>
    </form>
    """
    return _document("Transcribe — dpi-eval", body)


def selection_page(session: dict, token: str) -> str:
    boxes = "".join(
        f'<li><label><input type="checkbox" name="pages" '
        f'value="{p["source_index"]}" checked> '
        f'{html.escape(p["stem"])} {html.escape(p.get("label") or "")}</label></li>'
        for p in session["pages"]
    )
    body = f"""
    <h1>Select the sample pages</h1>
    <p data-session-id="{session["id"]}">Untick pages that are not part of
    this sample. The queue is exactly what you tick.</p>
    <form method="post" action="/transcribe/sessions/{session["id"]}/confirm">
      {_hidden_token(token)}
      <p><button type="button" onclick="document.querySelectorAll('[name=pages]').forEach(b => b.checked = !b.checked)">Invert selection</button></p>
      <ul>{boxes}</ul>
      <p><button type="submit">Start transcribing</button></p>
    </form>
    """
    return _document("Select pages — dpi-eval", body)


def session_page(session: dict, problems: list[dict], token: str) -> str:
    problem_stems = {p["stem"]: p["problem"] for p in problems}
    rows = []
    for p in session["pages"]:
        state = p["status"] + (" ⚑" if p["flagged"] else "")
        attention = ""
        if p["stem"] in problem_stems:
            attention = (
                f' <strong>needs attention ({problem_stems[p["stem"]]})</strong>'
                f' <form style="display:inline" method="post"'
                f' action="/transcribe/sessions/{session["id"]}/pages/{p["source_index"]}">'
                f'{_hidden_token(token)}<input type="hidden" name="action" value="adopt">'
                f'<button>Adopt</button></form>'
                f' <form style="display:inline" method="post"'
                f' action="/transcribe/sessions/{session["id"]}/pages/{p["source_index"]}">'
                f'{_hidden_token(token)}<input type="hidden" name="action" value="discard">'
                f'<button>Discard</button></form>'
            )
        rows.append(
            f'<tr><td><a href="/transcribe/sessions/{session["id"]}/pages/{p["source_index"]}">'
            f'{html.escape(p["stem"])}</a></td><td>{state}{attention}</td>'
            f'<td>{p["seconds_elapsed"]}s</td></tr>')
    saved = sum(1 for p in session["pages"] if p["status"] == "saved")
    grade_bits = ""
    if problems:
        grade_bits = "<p>Grading is disabled until needs-attention pages are resolved.</p>"
    elif saved == 0:
        grade_bits = "<p>Grading is disabled until at least one page is saved.</p>"
    else:
        grade_bits = f"""
        <form method="post" action="/transcribe/sessions/{session["id"]}/grade/preview"
              enctype="multipart/form-data">
          {_hidden_token(token)}
          <p><label>OCR folder path (desktop) <input name="ocr_folder"></label>
             or upload files <input type="file" name="ocr_files" multiple></p>
          <p><button type="submit">Preview grade alignment</button></p>
        </form>"""
    body = f"""
    <h1>Session {session["id"]}</h1>
    <p>{html.escape(session.get("collection") or "No collection label")} —
       mode: {session["mode"]} — conventions v{session["conventions_version"]}.
       Timing shown below is recorded with each save and visible here — nothing
       is collected silently.</p>
    <table><tr><th>Page</th><th>Status</th><th>Time</th></tr>{"".join(rows)}</table>
    {grade_bits}
    <form method="post" action="/transcribe/sessions/{session["id"]}/clone">
      {_hidden_token(token)}
      <p><button type="submit">New session from this selection (other arm)</button></p>
    </form>
    <form method="post" action="/transcribe/sessions/{session["id"]}/export">
      {_hidden_token(token)}
      <p><button type="submit">Export for repo</button></p>
    </form>
    <p><a href="/transcribe">Back to sessions</a></p>
    """
    return _document(f"Session {session['id']} — dpi-eval", body)
```

- [ ] **Step 4: Implement routes**

Inside `create_app` in `web.py`, after the `download` route (imports at module top: `from dpi_eval import iiif, sessions as sess`; `from fastapi import Form`):

```python
    trans_root = sess.transcriptions_root(base_dir)

    def _token() -> str:
        return os.environ.get("DPI_EVAL_TOKEN") or ""

    @app.get("/transcribe", response_class=HTMLResponse)
    def transcribe_home():
        return pages.transcribe_home_page(sess.list_sessions(trans_root), _token())

    @app.post("/transcribe/sessions", response_class=HTMLResponse)
    def transcribe_create(
        request: Request,
        token: str = Form(default=None),
        source_type: str = Form(...),
        folder: str = Form(default=""),
        manifest_url: str = Form(default=""),
        mode: str = Form(default="from_scratch"),
        draft_folder: str = Form(default=""),
        collection: str = Form(default=""),
    ):
        _check_token(request, token)
        drafts = Path(draft_folder) if draft_folder.strip() else None
        try:
            if source_type == "local":
                session = sess.create_local_session(
                    trans_root, Path(folder), mode, collection, drafts)
            else:
                records = iiif.parse_manifest(iiif.fetch_manifest(manifest_url))
                session = sess.create_iiif_session(
                    trans_root, manifest_url, records, mode, collection, drafts)
        except (sess.SessionError, iiif.IIIFError) as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return pages.selection_page(session, _token())

    @app.post("/transcribe/sessions/{sid}/confirm")
    def transcribe_confirm(
        sid: str, request: Request,
        token: str = Form(default=None),
        pages_selected: list[str] = Form(default=[], alias="pages"),
    ):
        _check_token(request, token)
        try:
            sess.confirm_session(trans_root, sid, [int(i) for i in pages_selected])
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return RedirectResponse(f"/transcribe/sessions/{sid}", status_code=303)

    @app.get("/transcribe/sessions/{sid}", response_class=HTMLResponse)
    def transcribe_session(sid: str):
        try:
            session = sess.load_session(trans_root, sid)
        except sess.SessionError:
            return HTMLResponse(pages.error_page("No such session."), status_code=404)
        problems = sess.reconcile(trans_root, session)
        return pages.session_page(session, problems, _token())
```

Also add the `form_page` link (Step spec in Files above).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_web_transcribe.py tests/test_web.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/dpi_eval/web.py src/dpi_eval/pages.py tests/test_web_transcribe.py
git commit -m "feat: transcribe routes — session list, create with selection, confirm, summary"
```

---

### Task 10: editor page, save route, image endpoint

**Files:**
- Modify: `src/dpi_eval/web.py` (routes), `src/dpi_eval/pages.py` (editor page)
- Test: `tests/test_web_editor.py`

**Interfaces:**
- Consumes: `sess.save_page/mark_no_text/set_flag/resolve_attention/draft_text/page_by_index`, `derive.derive/image_dims/info_json/DeriveError`.
- Produces routes: `GET /transcribe/sessions/{sid}/pages/{n}`; `POST /transcribe/sessions/{sid}/pages/{n}` (form field `action` ∈ `save | no_text | flag | adopt | discard`); `GET /transcribe/sessions/{sid}/images/{n}/info.json`; `GET /transcribe/sessions/{sid}/images/{n}/{region}/{size}/{rotation}/{quality}.{fmt}`.
- Produces page: `editor_page(session, page, draft: str, gt_text: str, token: str, position: str, notice: str = "") -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_editor.py
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from dpi_eval.web import create_app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "tok")
    folder = tmp_path / "masters"
    folder.mkdir()
    Image.new("RGB", (60, 40)).save(folder / "a.tif")
    Image.new("RGB", (60, 40)).save(folder / "b.tif")
    client = TestClient(create_app(tmp_path))
    response = client.post("/transcribe/sessions", data={
        "token": "tok", "source_type": "local", "folder": str(folder),
        "mode": "from_scratch", "collection": ""})
    sid = response.text.split('data-session-id="', 1)[1].split('"', 1)[0]
    client.post(f"/transcribe/sessions/{sid}/confirm",
                data={"token": "tok", "pages": ["0", "1"]})
    return client, sid


def test_editor_page_has_substitution_defenses(setup):
    client, sid = setup
    response = client.get(f"/transcribe/sessions/{sid}/pages/0")
    assert response.status_code == 200
    for attr in ('spellcheck="false"', 'autocorrect="off"', 'autocapitalize="off"'):
        assert attr in response.text


def test_save_no_text_and_flag_actions(setup):
    client, sid = setup
    save = client.post(f"/transcribe/sessions/{sid}/pages/0", data={
        "token": "tok", "action": "save", "text": "Line one\nLine two",
        "elapsed": "12", "active": "8", "nonce": "n1"})
    assert save.status_code == 303  # redirects to next page
    no_text = client.post(f"/transcribe/sessions/{sid}/pages/1", data={
        "token": "tok", "action": "no_text", "reason": "blank"})
    assert no_text.status_code == 303
    flag = client.post(f"/transcribe/sessions/{sid}/pages/0", data={
        "token": "tok", "action": "flag", "flagged": "on", "note": "check ligature"})
    assert flag.status_code == 303
    bad = client.post(f"/transcribe/sessions/{sid}/pages/0", data={
        "token": "wrong", "action": "save", "text": "x"})
    assert bad.status_code == 403


def test_image_endpoint_derives_tiff_to_jpeg(setup):
    client, sid = setup
    response = client.get(
        f"/transcribe/sessions/{sid}/images/0/full/max/0/default.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    info = client.get(f"/transcribe/sessions/{sid}/images/0/info.json")
    assert info.status_code == 200
    doc = info.json()
    assert doc["profile"] == "level1" and doc["width"] == 60


def test_image_endpoint_rejects_unimplemented(setup):
    client, sid = setup
    response = client.get(
        f"/transcribe/sessions/{sid}/images/0/full/max/90/default.jpg")
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_editor.py -v`
Expected: FAIL — editor route 404

- [ ] **Step 3: Implement editor_page in pages.py**

```python
def editor_page(session, page, draft, gt_text, token, position, notice=""):
    initial = gt_text or draft
    banner = ""
    if session["mode"] == "corrected" and not gt_text:
        banner = ('<p><strong>Machine draft below — correct it faithfully; '
                  'the OCR is what’s being graded.</strong></p>')
    notice_html = f"<p><em>{html.escape(notice)}</em></p>" if notice else ""
    sid, n = session["id"], page["source_index"]
    image_src = (
        f'{page["image_service"]}/full/!1200,1200/0/default.jpg'
        if page.get("image_service")
        else page.get("image_url")
        or f"/transcribe/sessions/{sid}/images/{n}/full/!1200,1200/0/default.jpg")
    full_src = (
        f'{page["image_service"]}/full/max/0/default.jpg'
        if page.get("image_service")
        else page.get("image_url")
        or f"/transcribe/sessions/{sid}/images/{n}/full/max/0/default.jpg")
    body = f"""
    <h1>{html.escape(page["stem"])} <small>({position})</small></h1>
    {notice_html}{banner}
    <div style="display:flex; gap:1rem; align-items:flex-start">
      <div style="flex:1">
        <img id="page-image" src="{image_src}" alt="Page image for {html.escape(page["stem"])}"
             style="max-width:100%; cursor:zoom-in"
             onerror="this.alt='Image failed to load — retry or flag this page.'">
        <p><button type="button" onclick="document.getElementById('lightbox').showModal()">Enlarge</button></p>
        <dialog id="lightbox" style="max-width:95vw; max-height:95vh; overflow:auto">
          <img src="{full_src}" alt="Full resolution page image">
          <form method="dialog"><button>Close</button></form>
        </dialog>
      </div>
      <form style="flex:1" method="post"
            action="/transcribe/sessions/{sid}/pages/{n}">
        {_hidden_token(token)}
        <input type="hidden" name="action" value="save">
        <input type="hidden" name="elapsed" id="elapsed" value="0">
        <input type="hidden" name="active" id="active" value="0">
        <input type="hidden" name="nonce" value="{secrets.token_hex(8)}">
        <textarea name="text" rows="30" style="width:100%; font-family:monospace"
                  spellcheck="false" autocorrect="off" autocapitalize="off"
                  autocomplete="off">{html.escape(initial)}</textarea>
        <p>Press Enter at the end of each printed line (line-for-line).</p>
        <p><button type="submit">Save &amp; next</button></p>
      </form>
    </div>
    <form method="post" action="/transcribe/sessions/{sid}/pages/{n}">
      {_hidden_token(token)}
      <input type="hidden" name="action" value="no_text">
      <label>No text on this page:
        <select name="reason">
          <option value="">— pick why —</option>
          <option value="blank">Blank page</option>
          <option value="image_only">Image only</option>
          <option value="illegible">Illegible</option>
        </select></label>
      <button type="submit">Mark</button>
    </form>
    <form method="post" action="/transcribe/sessions/{sid}/pages/{n}">
      {_hidden_token(token)}
      <input type="hidden" name="action" value="flag">
      <label><input type="checkbox" name="flagged" {"checked" if page["flagged"] else ""}>
        Flag for supervisor</label>
      <input name="note" value="{html.escape(page["note"])}" placeholder="note">
      <button type="submit">Update flag</button>
    </form>
    <p><a href="/transcribe/sessions/{sid}">Back to session</a></p>
    <script>
    (function () {{
      var opened = Date.now(), lastInput = 0, active = 0;
      var area = document.querySelector("textarea[name=text]");
      area.addEventListener("input", function () {{
        var now = Date.now();
        if (lastInput && now - lastInput < 5000) active += now - lastInput;
        lastInput = now;
      }});
      area.form.addEventListener("submit", function () {{
        document.getElementById("elapsed").value = Math.round((Date.now() - opened) / 1000);
        document.getElementById("active").value = Math.round(active / 1000);
      }});
    }})();
    </script>
    """
    return _document(f"{page['stem']} — transcribe", body)
```

Add `import secrets` to `pages.py` imports.

- [ ] **Step 4: Implement routes in web.py**

After the Task 9 routes inside `create_app` (module imports: `from dpi_eval import derive`):

```python
    def _next_pending(session, after_index):
        for page in session["pages"]:
            if page["source_index"] > after_index and page["status"] == "pending":
                return page["source_index"]
        return None

    @app.get("/transcribe/sessions/{sid}/pages/{n}", response_class=HTMLResponse)
    def editor(sid: str, n: int, notice: str = ""):
        try:
            session = sess.load_session(trans_root, sid)
            page = sess.page_by_index(session, n)
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=404)
        gt_file = sess.gt_path(trans_root, session, page)
        gt_text = gt_file.read_text(encoding="utf-8") if gt_file.exists() else ""
        draft = sess.draft_text(session, page) if session["mode"] == "corrected" else ""
        total = len(session["pages"])
        ordinal = [p["source_index"] for p in session["pages"]].index(n) + 1
        return pages.editor_page(session, page, draft, gt_text, _token(),
                                 position=f"Page {ordinal} of {total}",
                                 notice=notice)

    @app.post("/transcribe/sessions/{sid}/pages/{n}")
    async def editor_action(sid: str, n: int, request: Request):
        form = await request.form()
        _check_token(request, form.get("token"))
        action = form.get("action", "")
        try:
            if action == "save":
                session, changes = sess.save_page(
                    trans_root, sid, n, str(form.get("text", "")),
                    elapsed=int(form.get("elapsed") or 0),
                    active=int(form.get("active") or 0),
                    nonce=str(form.get("nonce") or ""))
                nxt = _next_pending(session, n)
                target = (f"/transcribe/sessions/{sid}/pages/{nxt}"
                          if nxt is not None else f"/transcribe/sessions/{sid}")
                if changes:
                    target += f"?notice={changes}+changes+applied+by+conventions+v{session['conventions_version']}"
                return RedirectResponse(target, status_code=303)
            if action == "no_text":
                sess.mark_no_text(trans_root, sid, n, str(form.get("reason") or ""))
            elif action == "flag":
                sess.set_flag(trans_root, sid, n,
                              form.get("flagged") is not None,
                              str(form.get("note") or ""))
            elif action in ("adopt", "discard"):
                sess.resolve_attention(trans_root, sid, n, action)
            else:
                return HTMLResponse(pages.error_page("Unknown action."), status_code=400)
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return RedirectResponse(f"/transcribe/sessions/{sid}", status_code=303)

    def _local_master(session, page) -> Path:
        return Path(session["source"]["path"]) / page["image_file"]

    @app.get("/transcribe/sessions/{sid}/images/{n}/info.json")
    def image_info(sid: str, n: int, request: Request):
        try:
            session = sess.load_session(trans_root, sid)
            page = sess.page_by_index(session, n)
            width, height = derive.image_dims(_local_master(session, page))
        except (sess.SessionError, KeyError, OSError):
            return JSONResponse({"error": "no such image"}, status_code=404)
        base = f"http://{request.headers.get('host')}/transcribe/sessions/{sid}/images/{n}"
        return JSONResponse(
            derive.info_json(base, width, height),
            media_type='application/ld+json;profile="http://iiif.io/api/image/3/context.json"')

    @app.get("/transcribe/sessions/{sid}/images/{n}/{region}/{size}/{rotation}/{quality_fmt}")
    def image_request(sid: str, n: int, region: str, size: str,
                      rotation: str, quality_fmt: str):
        if "." not in quality_fmt:
            return JSONResponse({"error": "bad request"}, status_code=400)
        quality, fmt = quality_fmt.rsplit(".", 1)
        try:
            session = sess.load_session(trans_root, sid)
            page = sess.page_by_index(session, n)
            derive.parse_params(region, size, rotation, quality, fmt)
            cache = sess.session_dir(trans_root, sid) / "derivatives"
            out = derive.derive(_local_master(session, page), region, size, cache)
        except derive.DeriveError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except (sess.SessionError, KeyError, OSError):
            return JSONResponse({"error": "no such image"}, status_code=404)
        return FileResponse(out, media_type="image/jpeg")
```

Pass the `notice` query param through: change `editor`'s signature `notice: str = ""` (already shown).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_web_editor.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/dpi_eval/web.py src/dpi_eval/pages.py tests/test_web_editor.py
git commit -m "feat: editor page with lightbox and timing, page actions, level-1 image endpoint"
```

---

### Task 11: grade preview/confirm, clone, export routes

**Files:**
- Modify: `src/dpi_eval/web.py` (routes), `src/dpi_eval/pages.py` (`alignment_page`)
- Test: `tests/test_web_grade_export.py`

**Interfaces:**
- Consumes: `sess.stage_ocr/stage_for_grade/clear_staging/export_session/confirm_session/load_session`, `_run_and_register`, `_enumerate_dir` (existing), `_check_token`.
- Produces routes: `POST /transcribe/sessions/{sid}/grade/preview` (path or multipart), `POST /transcribe/sessions/{sid}/grade/confirm` (override fields named `override_<stem>`), `POST /transcribe/sessions/{sid}/clone`, `POST /transcribe/sessions/{sid}/export`.
- Produces page: `alignment_page(session, alignment: dict, token: str) -> str` — a table (page stem → matched file or `<select>` of unmatched files) plus a confirm form.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_grade_export.py
import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from dpi_eval.web import create_app


@pytest.fixture
def session_with_gt(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "tok")
    folder = tmp_path / "masters"
    folder.mkdir()
    Image.new("RGB", (10, 10)).save(folder / "page_0.png")
    client = TestClient(create_app(tmp_path))
    response = client.post("/transcribe/sessions", data={
        "token": "tok", "source_type": "local", "folder": str(folder),
        "mode": "from_scratch", "collection": "coll"})
    sid = response.text.split('data-session-id="', 1)[1].split('"', 1)[0]
    client.post(f"/transcribe/sessions/{sid}/confirm",
                data={"token": "tok", "pages": ["0"]})
    client.post(f"/transcribe/sessions/{sid}/pages/0", data={
        "token": "tok", "action": "save", "text": "hello world",
        "elapsed": "1", "active": "1", "nonce": "n"})
    return client, sid


def test_grade_preview_upload_then_confirm_redirects_to_run(session_with_gt):
    client, sid = session_with_gt
    preview = client.post(
        f"/transcribe/sessions/{sid}/grade/preview",
        data={"token": "tok", "ocr_folder": ""},
        files=[("ocr_files", ("page_0.txt", b"hello world\n"))])
    assert preview.status_code == 200
    assert "page_0.txt" in preview.text  # alignment table shows the match
    confirm = client.post(f"/transcribe/sessions/{sid}/grade/confirm",
                          data={"token": "tok"})
    assert confirm.status_code == 303
    assert confirm.headers["location"].startswith("/runs/run-")
    results = client.get(confirm.headers["location"])
    assert results.status_code == 200


def test_clone_creates_other_arm_with_same_selection(session_with_gt):
    client, sid = session_with_gt
    response = client.post(f"/transcribe/sessions/{sid}/clone", data={"token": "tok"})
    assert response.status_code == 303
    new_sid = response.headers["location"].rsplit("/", 1)[-1]
    page = client.get(f"/transcribe/sessions/{new_sid}")
    assert "corrected" in page.text  # opposite arm


def test_export_downloads_zip(session_with_gt):
    client, sid = session_with_gt
    response = client.post(f"/transcribe/sessions/{sid}/export", data={"token": "tok"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert any(name.endswith("transcriptions.json") for name in zf.namelist())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_grade_export.py -v`
Expected: FAIL — preview route 404

- [ ] **Step 3: Implement alignment_page in pages.py**

```python
def alignment_page(session, alignment, token):
    unmatched_files = alignment["unmatched_files"]
    rows = []
    for page in session["pages"]:
        if page["status"] != "saved":
            continue
        matched = alignment["matched"].get(page["stem"])
        if matched:
            cell = html.escape(matched)
        elif unmatched_files:
            options = "".join(
                f'<option value="{html.escape(f)}">{html.escape(f)}</option>'
                for f in unmatched_files)
            cell = (f'<select name="override_{html.escape(page["stem"])}">'
                    f'<option value="">— unmatched —</option>{options}</select>')
        else:
            cell = "<em>unmatched — this page will not be graded</em>"
        rows.append(f"<tr><td>{html.escape(page['stem'])}</td><td>{cell}</td></tr>")
    leftover = ", ".join(html.escape(f) for f in unmatched_files) or "none"
    body = f"""
    <h1>Check the alignment before grading</h1>
    <p>Each saved page pairs with one OCR file. Fix any mispair with the
    dropdowns — nothing is graded until you confirm.</p>
    <form method="post" action="/transcribe/sessions/{session["id"]}/grade/confirm">
      {_hidden_token(token)}
      <table><tr><th>Page</th><th>OCR file</th></tr>{"".join(rows)}</table>
      <p>Unmatched OCR files: {leftover}</p>
      <p><button type="submit">Grade</button>
         <a href="/transcribe/sessions/{session["id"]}">Cancel</a></p>
    </form>
    """
    return _document("Alignment preview — dpi-eval", body)
```

- [ ] **Step 4: Implement routes in web.py**

```python
    @app.post("/transcribe/sessions/{sid}/grade/preview", response_class=HTMLResponse)
    async def grade_preview(sid: str, request: Request):
        form = await request.form()
        _check_token(request, form.get("token"))
        files: list[tuple[str, bytes]] = []
        ocr_folder = str(form.get("ocr_folder") or "").strip()
        if ocr_folder:
            folder = Path(ocr_folder)
            if not folder.is_dir():
                return HTMLResponse(
                    pages.error_page(f"Not a readable directory: {folder}"),
                    status_code=400)
            files = [(u.filename, u.file.read()) for u in _enumerate_dir(folder)]
        else:
            for upload in form.getlist("ocr_files"):
                if getattr(upload, "filename", None):
                    files.append((upload.filename, upload.file.read()))
        if not files:
            return HTMLResponse(
                pages.error_page("Pick the OCR folder or upload OCR files."),
                status_code=400)
        try:
            session = sess.load_session(trans_root, sid)
            alignment = sess.stage_ocr(trans_root, sid, files)
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return pages.alignment_page(session, alignment, _token())

    @app.post("/transcribe/sessions/{sid}/grade/confirm")
    async def grade_confirm(sid: str, request: Request):
        form = await request.form()
        _check_token(request, form.get("token"))
        overrides = {
            key[len("override_"):]: str(value)
            for key, value in form.items() if key.startswith("override_")}
        try:
            gt_dir, ocr_dir = sess.stage_for_grade(trans_root, sid, overrides)
            run_dir = _run_and_register(gt_dir, ocr_dir, base_dir)
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        finally:
            sess.clear_staging(trans_root, sid)
        return RedirectResponse(f"/runs/{run_dir.name}", status_code=303)

    @app.post("/transcribe/sessions/{sid}/clone")
    def clone_session(sid: str, request: Request, token: str = Form(default=None)):
        _check_token(request, token)
        try:
            source = sess.load_session(trans_root, sid)
            other_mode = "corrected" if source["mode"] == "from_scratch" else "from_scratch"
            selected = [p["source_index"] for p in source["pages"]]
            if source["source"]["type"] == "local":
                clone = sess.create_local_session(
                    trans_root, Path(source["source"]["path"]), other_mode,
                    source["collection"],
                    Path(source["draft_source"]) if source.get("draft_source") else None)
            else:
                records = iiif.parse_manifest(
                    iiif.fetch_manifest(source["source"]["manifest_url"]))
                clone = sess.create_iiif_session(
                    trans_root, source["source"]["manifest_url"], records,
                    other_mode, source["collection"])
            sess.confirm_session(trans_root, clone["id"], selected)
        except (sess.SessionError, iiif.IIIFError) as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return RedirectResponse(f"/transcribe/sessions/{clone['id']}", status_code=303)

    @app.post("/transcribe/sessions/{sid}/export")
    def export(sid: str, request: Request, token: str = Form(default=None)):
        _check_token(request, token)
        try:
            archive = sess.export_session(trans_root, sid)
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return FileResponse(archive, media_type="application/zip",
                            filename=archive.name)
```

Note on clone + corrected: cloning from_scratch → corrected requires a draft source the original lacks; `create_local_session`/`create_iiif_session` raise `SessionError("Correction mode needs a draft folder.")`, which surfaces as the 400 error page telling the user to start the corrected session manually with a draft folder — acceptable v1 behavior; the clone button's primary case is corrected → from_scratch and same-arm re-runs are out of scope. **The test `test_clone_creates_other_arm_with_same_selection` must therefore seed the original session with a `draft_folder`** — update the fixture: create `drafts/page_0.txt` containing `hello world` and pass `"draft_folder": str(drafts)` — no, simpler and correct: make the fixture's original session **corrected** mode with a draft folder, and assert the clone is `from_scratch`. Adjust the fixture accordingly:

```python
# in the session_with_gt fixture, replace the create call with:
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "page_0.txt").write_text("hello world\n")
    response = client.post("/transcribe/sessions", data={
        "token": "tok", "source_type": "local", "folder": str(folder),
        "mode": "corrected", "collection": "coll",
        "draft_folder": str(drafts)})
# and in test_clone..., assert "from_scratch" in page.text
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/dpi_eval/web.py src/dpi_eval/pages.py tests/test_web_grade_export.py
git commit -m "feat: grade preview/confirm with editable alignment, clone-other-arm, export download"
```

---

### Task 12: docs, wheelhouse note, manual QA

**Files:**
- Modify: `README.md` (new "Transcribing a sample" section after the grading section: source-as-queue, line-for-line rule, no-text reasons, export)
- Modify: `docs/findings.md` (append a dated entry: transcription editor implemented per spec; pilot evidence hooks: per-page elapsed/active seconds, no-text reasons, conventions version stamping)
- Modify: `desktop/README.md` or the wheelhouse build script's dependency list (wherever `desktop/runtime/payload/` wheels are enumerated — locate with `grep -ril pillow desktop/ || grep -ril wheel desktop/*.md desktop/**/*.sh`): add Pillow and note it bundles OpenJPEG (JP2) + libtiff (TIFF)

**Interfaces:** none — documentation and packaging only.

- [ ] **Step 1: Write the README section** (prose per the spec's "What it is" and decisions 4–7; include the line-for-line instruction verbatim: "Press Enter at the end of each printed line.")

- [ ] **Step 2: Add Pillow to the wheelhouse manifest** found via the grep above; rebuild or note the rebuild command the desktop docs already prescribe.

- [ ] **Step 3: Manual QA (desktop)** — run the desktop app; create a local-folder session from a folder containing at least one JP2 master; confirm selection; transcribe one page (verify smart quotes are NOT substituted while typing "test" with quotes); mark one page no-text/illegible; grade via preview with one manual override; open the run's results page; export and inspect the zip. Then create an IIIF session from a real UMD manifest in a browser (`uv run dpi-eval-web`) and transcribe one page from scratch.

- [ ] **Step 4: Run the full suite one last time**

Run: `uv run pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add README.md docs/findings.md desktop/
git commit -m "docs: transcription editor usage, pilot evidence hooks, Pillow wheelhouse note"
```

---

## Self-review notes (already applied)

- Spec coverage: sessions (T5–T7), conventions/line-for-line (T1), IIIF v2/v3 (T2), image derivation + level-1 + JP2/TIFF (T3, T10), alignment incl. off-by-one pin and manual override (T4, T11), GT integrity + reconciliation (T6, T7), token/CSRF both modes (T8), select-at-create (T9), editor + substitution defenses + lightbox + timing (T10), grade preview/confirm + run registration (T11), clone-other-arm + export with status/no_text_reason + collection layout (T7, T11), docs/wheelhouse (T12). Anonymous sessions: satisfied by absence (no identity field anywhere).
- Known simplification, deliberate: IIIF-session editor `<img>` uses the remote service/URL directly (spec) — the local image endpoint serves local sessions only, and `image_info`/`image_request` return 404 for IIIF pages via the `KeyError` on `page["image_file"]`.
- Deferred to the pilot by spec: browser correction sessions, deep zoom/OSD, `info.json` for remote-backed pages, pyvips ladder.
