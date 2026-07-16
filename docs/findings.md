# Findings — DPI OCR-Evaluation Sprint

Running log of gaps and observations, each triaged **upstream-PR candidate** vs.
**wrapper work** (per the design spec's success criteria). Verified against
dinglehopper v0.11.0 source, 2026-07-16.

## 1. Heavy dependency tree from a single logging import — upstream-PR candidate

**Observation.** `uv add dinglehopper` installs the full OCR-D core stack — uvicorn,
werkzeug, Flask-adjacent web machinery — into what is conceptually a text-diffing
tool. Harmless in this repo's dedicated venv; a real cost if evaluation ever runs
inside a slim DPI pipeline container.

**Root cause.** `requirements.txt` hard-pins `ocrd >= 3.3.0`, but only
`ocrd_cli.py` (the OCR-D processor wrapper, unused by DPI) genuinely needs it
(`ocrd.Processor`, `ocrd_models.OcrdFileType`). Every other ocrd import in the
codebase is logging only:

- `extracted_text.py:12` — `from ocrd_utils import getLogger`
- `ocr_files.py:8` — `from ocrd_utils import getLogger`
- `cli.py:8`, `cli_extract.py:2`, `cli_line_dirs.py:7`, `cli_summarize.py:7` —
  `from ocrd_utils import initLogging`

The HTML renderer is NOT the weight — jinja2 + MarkupSafe are tiny. Stripping the
renderer (the tempting fork move) would save nothing.

**Proposed upstream PR.** Swap `getLogger`/`initLogging` for stdlib `logging` in
core modules; move `ocrd` to an optional extra (`dinglehopper[ocrd]`) with an
import-guarded processor wrapper. Small, focused, mergeable — upstream merges
external PRs (e.g. #145).

**Fallback if needed before upstream merges (wrapper work, Approach B).** Import
the metrics modules directly (`edit_distance`, `character_error_rate`,
`word_error_rate`). Caveat verified 2026-07-16: all three import `ExtractedText`
from `extracted_text.py`, whose `ocrd_utils.getLogger` import makes the chain
transitively ocrd-dependent — it is NOT ocrd-free as first assumed. Two escape
hatches, either is small:

1. Vendor `extracted_text.py` with a ~3-line stdlib-logging shim replacing
   `getLogger`, or
2. Depend on `ocrd_utils` alone (logging/util package; no web stack) instead of
   full `ocrd`.

**Status.** Not sprint scope — the uv venv absorbs the weight for the demo. Logged
for post-demo triage.

## 2. hOCR input support — upstream-PR candidate (shim as wrapper work meanwhile)

**Context.** [iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr) (M. Aguilar,
UMD) runs PaddleOCR over IIIF manifest canvases and emits one hOCR file per page
(`downloads/<manifest-uuid>/page_{i}.hocr`, stem = zero-based canvas index).
Grading its output with dinglehopper gives DPI real CER/WER numbers for that
pipeline — but dinglehopper reads only ALTO/PAGE/plain text (auto-detected in
`ocr_files.py`), not hOCR.

**Sprint scope (wrapper work).** Input adapter in this repo: sniff hOCR by its
`ocr_page` class markup, extract line text with a ~30-line lxml shim, pass
everything else through untouched. Spec amended 2026-07-16 to include it.

**Proposed upstream PR.** Add hOCR extraction to dinglehopper's format dispatcher
(`ocr_files.py`) alongside ALTO/PAGE detection. Would make our shim deletable and
benefit the OCR-D ecosystem generally.

**Pairing convention.** GT transcriptions for iiif_ocr output follow its stem:
`page_{i}.gt.txt` grades `page_{i}.hocr`.

**Status (implementation, 2026-07-16).** Adapter shipped in `src/dpi_eval/adapter.py`
with hOCR and ALTO end-to-end tests. Two facts pinned empirically during the build:
`dinglehopper-summarize` tolerates a non-report `_normalized/` subdirectory inside
the reports folder (regression test in `tests/test_batch.py`), and dinglehopper
accepts ALTO ns-v3 namespace fixtures without conversion.

## 3. IIIF-viewer side-by-side QC — post-sprint enhancement

**Idea (T. Muñoz, 2026-07-16).** Since inputs are IIIF manifests and hOCR carries
word/line coordinates, convert hOCR to IIIF annotations and overlay OCR text on
page images in Mirador/Universal Viewer for in-place visual QC.

**Why not now (REDUCE).** New moving parts: hOCR→annotation conversion, annotation
hosting, viewer config. Meanwhile ~90% of the QC value already exists stock:
dinglehopper's HTML report is a highlighted text side-by-side, and
`iiif_ocr --visualize` emits page images with OCR bounding boxes drawn on.

**Trigger to build.** Reviewers actually using the demo outputs ask "where on the
page is this error?" more often than the two stock views answer it.
