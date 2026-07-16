# DPI OCR-Evaluation Demo — Design

**Date:** 2026-07-16
**Status:** Approved (brainstorming session)
**Scope posture:** REDUCE — minimum that proves OCR evaluation fits the DPI digitization workflow
**Decision:** Adopt [dinglehopper](https://github.com/qurator-spk/dinglehopper) as an unmodified pip dependency. Do not fork.

## Goal

By sprint end, OCR evaluation runs end-to-end on one real DPI batch and produces
machine-readable quality metrics:

- Per-page `report.json` — CER, WER, character/word counts (dinglehopper stock output)
- Batch-level `summary.json` via stock `dinglehopper-summarize`
- HTML reports as a free human-readable byproduct

## Background / why not fork

Code survey of dinglehopper (2026-07-16, v0.11.0):

- Apache-2.0, maintained by Mike Gerber (Staatsbibliothek zu Berlin / Qurator, OCR-D
  ecosystem). One-maintainer project but active: v0.11.0 April 2025, pushed August 2025,
  merges external PRs.
- Algorithmic core is correct and tested: CER/WER on NFC-normalized grapheme clusters
  (rapidfuzz + uniseg), 20+ test files including integration fixtures.
- Already emits machine-readable JSON (`report.json.j2`, `summary.json.j2`) rendered from
  the same variables as the HTML — the original "different format" motivation for forking
  is largely solved upstream.
- Known debt (matters only to a fork): `cli.py` couples orchestration with HTML string
  generation; confirmed latent `NameError` in `ocrd_cli.py:38-43` (`config`,
  `MissingInputFile` used but not imported) on the OCR-D missing-input path — we do not
  use the OCR-D wrapper.

Approaches considered: (A) adopt + thin glue, (B) wrap internals as a library,
(C) fork. **A chosen.** Upgrade path: a demonstrated gap in the JSON report becomes a
small upstream PR or the trigger to revisit B. Fork is last resort.

## Components

All DPI-owned code is thin glue; dinglehopper is an unmodified dependency.

1. **Ground-truth sample.** 10–20 pages from the demo batch, manually transcribed as
   plain text (dinglehopper compares plain-text GT against ALTO OCR directly; no XML
   markup needed). The sampling approach (which pages, how many) is a sprint finding,
   not a fixed input.
2. **Batch runner.** Thin script that pairs GT files with OCR files by naming
   convention, invokes `dinglehopper` per page into a reports folder, logs and skips
   pages that fail (missing pair, parse error), and exits non-zero above a failure
   threshold. dinglehopper has a directory mode; the runner may shrink to almost
   nothing.
3. **Batch rollup.** Stock `dinglehopper-summarize` over the reports folder →
   `summary.json` + `summary.html`.

## Scope fence (REDUCE)

- Demo batch: one that **already has ALTO** output.
- hOCR / PDF-embedded-text materials: **out of scope to build**; the conversion shim is
  documented as a known gap with an effort estimate in the findings note. Build only if
  the sole available real batch forces it.
- Materials with no OCR yet: out of scope entirely.
- No new metrics, no custom report formats, no dashboard.

## Data flow

DPI batch (images + ALTO) → sample pages selected → manual GT transcriptions (plain
text) → runner invokes `dinglehopper <gt> <ocr>` per page → per-page `report.json` /
`.html` → `dinglehopper-summarize` → `summary.json` for whatever pipeline/dashboard
comes later.

## Error handling

Minimal by design: skip-and-log per page; fail loudly at batch level (non-zero exit
above failure threshold). Watch plain-text GT encoding — use dinglehopper's
`--plain-encoding` option if needed.

## Testing / success criteria

- Smoke-test glue against dinglehopper's own test fixtures before touching real data.
- Done =
  1. every sampled page of one real DPI batch has metrics,
  2. `summary.json` parses,
  3. a findings note exists covering: recommended ground-truth strategy, gaps in
     dinglehopper's JSON for DPI needs (each tagged upstream-PR vs. wrapper work), and
     hOCR conversion effort estimate.

## Deliverables

- This repo (`dpi-dinglehopper-eval`): glue scripts + spec + findings note
- Demo output on real data (reports folder, summary)
- Findings note (`docs/findings.md`)

## Open questions (to resolve during sprint, not before)

- Which real batch serves as the demo batch (needs ALTO + feasible GT sampling)
- Ground-truth strategy long-term: manual samples vs. engine-vs-engine agreement vs.
  vendor-verification — the demo generates evidence for this recommendation
