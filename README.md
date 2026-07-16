# dpi-dinglehopper-eval

DPI glue around [dinglehopper](https://github.com/qurator-spk/dinglehopper)
(unmodified dependency — we do not fork) to grade OCR output against
ground-truth samples and emit machine-readable quality metrics.

## Setup

    uv sync

## Usage

    uv run dpi-eval GT_DIR OCR_DIR REPORTS_DIR [--max-failure-rate 0.2]

- `GT_DIR` — plain-text ground truth, one file per page, named `<stem>.gt.txt`
- `OCR_DIR` — OCR output sharing the stem: `<stem>.hocr` (e.g. from
  [iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr)), `<stem>.xml`
  (ALTO/PAGE), or `<stem>.txt`. hOCR is converted internally; everything
  else goes to dinglehopper untouched.
- `REPORTS_DIR` — receives per-page `<stem>.json` / `<stem>.html` and
  batch-level `summary.json` / `summary.html`.

Exit code is non-zero when more than `--max-failure-rate` of pages fail
or when there is nothing to grade. Pages with no matching OCR file are
logged and skipped.

## Demo runbook (iiif_ocr path)

1. Run your manifest through iiif_ocr:
   `iiif_ocr https://example.org/manifest.json`
   → hOCR lands in `downloads/<manifest-uuid>/page_{i}.hocr`
2. Pick 10–20 pages; transcribe each carefully into `gt/page_{i}.gt.txt`
   (plain text, one file per sampled page — match the stem exactly).
3. Grade: `uv run dpi-eval gt/ downloads/<manifest-uuid>/ reports/`
4. Read `reports/summary.json` (machine) or `reports/summary.html` (human);
   per-page visual diffs are in `reports/page_{i}.html`.

## Project docs

- Design spec: `docs/superpowers/specs/2026-07-16-dpi-ocr-eval-demo-design.md`
- Findings log (upstream-PR candidates, deferred ideas): `docs/findings.md`
