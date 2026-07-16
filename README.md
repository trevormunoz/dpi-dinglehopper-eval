# dpi-dinglehopper-eval

DPI glue around [dinglehopper](https://github.com/qurator-spk/dinglehopper)
(unmodified dependency — we do not fork) to grade OCR output against
ground-truth samples and emit machine-readable quality metrics.

## Quick start (no install)

With [uv](https://docs.astral.sh/uv/) installed, run directly from GitHub —
no clone, no setup, no elevated permissions:

    uvx --from git+https://github.com/trevormunoz/dpi-dinglehopper-eval dpi-eval GT_DIR OCR_DIR REPORTS_DIR

## Setup (working copy)

    uv sync

## Usage

    uv run dpi-eval GT_DIR OCR_DIR REPORTS_DIR [--max-failure-rate 0.2]

- `GT_DIR` — plain-text ground truth, one file per page, named `<stem>.gt.txt`
- `OCR_DIR` — OCR output sharing the stem: `<stem>.hocr` (e.g. from
  [iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr)), `<stem>.xml`
  (ALTO/PAGE), or `<stem>.txt`. hOCR is converted internally; everything
  else goes to dinglehopper untouched.
- `REPORTS_DIR` — receives per-page `<stem>.json` / `<stem>.html` and
  batch-level `summary.json` / `summary.html`. The tool owns this directory:
  stale reports from prior runs are cleared at the start of each run so
  re-grading never mixes old and new results.

Exit code is non-zero when more than `--max-failure-rate` of pages fail
or when there is nothing to grade. Pages with no matching OCR file are
logged and skipped.

## Quickstart: you already have OCR files (vendor collections)

1. Your OCR lives in a folder, e.g. `ocr/` with files like `issue-042-p001.xml`
   (ALTO/PAGE XML, hOCR, or plain text — all fine as-is).
2. Make a `gt/` folder. Pick 10–20 pages to sample; for each, type what the
   page actually says into a plain-text file named after the OCR file with
   `.gt.txt` in place of its extension: `ocr/issue-042-p001.xml` is graded by
   `gt/issue-042-p001.gt.txt`. Only sampled pages need GT files.
3. Grade and read the results:

       uvx --from git+https://github.com/trevormunoz/dpi-dinglehopper-eval dpi-eval gt/ ocr/ reports/

   Batch scores: `reports/summary.html` (or `summary.json` for machines);
   per-page side-by-side diffs: `reports/<page>.html`.

If you only have *images* (no OCR yet), an OCR step has to run first — see
[iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr) and the runbook below.

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
