# UX findings — dpi-eval pass, 2026-07-19

Aggregated from two blind PAR critiques (A: flow/forms/copy, GOV.UK lens;
B: visual credibility) over 13 captured page states + `pages.py` +
`desktop/ui/index.html`, plus one Trevor-sourced finding. Dedupe applied;
worst severity wins; [dual] = found independently by both reviewers.
Effort: S/M/L. Areas: results-legibility | waiting-states |
picker-feedback | general | deferred-upstream.

## Critical

- **F1 · S · results-legibility** (B1) — The headline score is buried
  mid-sentence and never visually judged. "12.5%" sits inside prose;
  no color/badge/scale says whether it's good. Fix: score-display
  component (large tabular number + label + green/amber/red band)
  first on the page.

## Serious

- **F2 · S · waiting-states** (A1+B6) [dual] — Bootstrap "failed" state
  shows raw `failed: pip exited with status 1 (see sidecar.log)` with
  no recovery action. Fix: friendly fixed message ("close and reopen;
  if it persists, show this to library staff"), error-tier styling;
  raw detail de-emphasized.
- **F3 · S · general** (A2) — Footer tells desktop users to close "the
  terminal window it came from"; desktop has no terminal. Fix: gate
  the terminal sentence behind the existing `__TAURI__` check.
- **F4 · M · general** (A8+B4 seam) [dual] — Report pages are a
  different-looking product with no way back (different fonts,
  full-bleed, no back link; tab navigation strands desktop users).
  Fix: the approved wrap-at-serve-time route (styled shell +
  "Back to results").
- **F5 · S · general** (A3) — The bolded "Full batch summary" link
  drops students from plain-language percentages into raw
  `Average CER: 0.0345`. Fix: relabel "Full technical report" and
  de-emphasize; results page stays the primary artifact.
- **F6 · M · general** (A4) — Form intro is one dense
  filename-convention paragraph. Fix: lead with "Choose two folders,
  then grade."; naming rules become a short bulleted list.
- **F7 · M · waiting-states** (A5+B6) [dual] — After Run, only the
  button label changes; installing state is a static line that reads
  as frozen. Fix: page-level status region on submit ("Grading N
  pages… this can take a minute", honest static/elapsed only) +
  indeterminate affordance on the installing screen.
- **F8 · M · general** (A6) — Collision error lists identical basenames
  twice ("page_0.txt", "page_0.txt") — user can't tell which files
  collide. Fix: show relative paths. NOTE: touches pipeline message
  construction in web.py → needs the same narrow fence widening as F14.
- **F9 · S · general** (A7) — "Run" is CLI jargon. Fix: "Grade this
  batch" (also reinforces the sequence).
- **F10 · M · picker-feedback** (A9+B7) [dual] — Chosen-folder feedback
  is a raw absolute path in small gray text that will overflow on long
  paths; no file count, no change affordance. Fix: confirmation row
  per fieldset (✓ + folder name emphasized, wrapping path, file count
  if cheap client-side).
- **F11 · S · general** (B2) — Type scale inverted: `h1` 1.4rem but
  `h2` falls to UA default (~1.5rem) — H2 renders bigger than H1.
  Fix: explicit scale tokens (h1 > h2 > h3).
- **F12 · M · results-legibility** (B3) — Results is five stacked
  paragraphs before the table; sizes nearly indistinguishable. Fix:
  F1's component carries the verdict; caveats demoted to one
  small-print block; table carries detail.
- **F13 · M · general** (B5) — Two action vocabularies: native gray
  buttons vs bare blue links of equal importance. Fix: one button
  token (primary/quiet) + links reserved for navigation.
- **F14 · M · general** (Trevor, 2026-07-19) — Pairing is mechanically
  checkable before grading: call the engine's own `pairing.py` matcher
  (read-only import) on filename lists in `_grade_pipeline`; 400 with
  the specific unmatched names instead of grading into a "Nothing was
  graded" banner. NOTE: needs a narrow spec amendment widening the
  web.py fence to pipeline validation (shared with F8).

## Minor

- **F15 · S** (A10) — H1 "Run run-011" is a meaningless internal ID →
  "Grading results", run id demoted to caption.
- **F16 · S** (A11) — Zero-success state's only exit says "Grade
  another batch" — nothing was graded → "Back to the form".
- **F17 · S** (A12) — Sequence not communicated: number the fieldsets
  ("1. Ground-truth folder", "2. OCR folder").
- **F18 · S** (A13) — No on-page note of where the downloaded zip
  lands → add a line reusing the existing `dpi-eval-runs` wording.
- **F19 · S** (B8) — No warning tier: `.error`/`.banner` share one red;
  `.ok` oversized → one notice component with success/warning/error
  tiers (also used by F2).

## Deferred / upstream (recorded, not built)

- Report-page INTERNALS: raw decimals (0.125 vs the app's 12.5%),
  unexplained CER/WER acronyms, 2em headings, full-bleed layout —
  dinglehopper-generated; only the wrapper seam (F4) is in scope.

## Reviewer B's "three cheapest credibility wins" (for cut-line context)

1. Explicit type-scale block (fixes F11, enables F12) — few CSS lines.
2. Score-display component (F1).
3. Button token + three-tier notice component (F13, F19, feeds F2).

## Cut-line

_Set by Trevor at Stage 3; items below the line move to Deferred._
