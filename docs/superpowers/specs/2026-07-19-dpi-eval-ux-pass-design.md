# dpi-eval UX pass — design

**Date:** 2026-07-19
**Status:** Approved in brainstorm (Trevor, 2026-07-19) — pending spec review
**Trigger:** Task 9/9b closed the desktop tracer; Trevor: the app "will need a
real UX pass before we can put it in front of colleagues." Runs before the
Task 11 write-up. Task 10 (CI/release) proceeds in parallel — it never
inspects page content.

## Goal and bar

Make the app credible and self-explanatory for HDC colleagues and student
workers. Bar chosen: **clean and credible** — professional typography,
spacing, hierarchy, and consistent components in the existing pages. Not a
branding project, not UMD/HDC institutional alignment.

Scope chosen (Trevor, multi-select): visual credibility, flow and
affordances, copy and guidance. Explicitly deferred: a deep WCAG/Title II
audit (the 2026-07-18 amendment's a11y-parity requirements remain binding
as built; this pass may only improve the baseline).

Friction areas named from Trevor's own walkthroughs, in priority:

1. **Results legibility** — the scores page buries the verdict in
   explanatory prose; hard to scan for "is this good or bad?"
2. **Waiting states** — Run → "Grading…" with no progress signal; the
   first-launch bootstrap shows the static placeholder page
   (`desktop/ui/index.html`) with no sense of what is happening or how
   long it takes (measured: ~10 s cold, ~1 s warm).
3. **Picker/selection feedback** — raw filesystem paths as confirmation;
   no explicit "both chosen, ready to run" state.

"After-grading guidance" was considered and not selected.

## Process: review first, then targeted fixes

Approach A chosen over a direct design sprint and a CSS-only dress-up:
critique the real pages before changing them, so every change traces to an
identified problem and the pass has a natural cut-line.

### Stage 1 — Capture

Screenshot every user-visible surface as actually rendered:

- Form page, browser variant (file inputs) and desktop variant (native
  picker buttons + path displays; reviewable by serving the page with a
  token and stubbing `window.__TAURI__` before load — no dialog clicks
  needed).
- Results page (real grade of `tests/fixtures/text`), per-page diff view,
  the `error_page` shapes (no-gt-files, empty-OCR, collisions), and the
  batch-failure page.
- The shell placeholder `desktop/ui/index.html` (bootstrap wait state).

### Stage 2 — Critique (PAR)

Two blind parallel reviewers per the standing PAR discipline, same inputs
(screenshots + page markup/copy), different lenses:

- **Flow/forms/copy** — government-design-system (GOV.UK-style) review of
  the interaction shape and language: button states and labels, error
  presentation and placement, instructional copy register, disabled-state
  and validation patterns, one-thing-per-page pressure tested against the
  two-pickers-one-Run shape.
- **Visual credibility** — hierarchy, type scale, spacing rhythm, table
  treatment, scannability; "does this look intentional at a glance."

Aggregation: dedupe, worst severity wins, every finding tagged to one of
the three friction areas or "general," each with severity and an effort
size (S/M/L — story-point style, never time units). No fixes implemented
at this stage.

### Stage 3 — Cut-line (human gate)

Trevor reviews the aggregated findings list and sets the cut-line. Items
below the line are recorded, not built. This gate is what keeps "UX pass"
from becoming "redesign."

**Visual companion (Trevor, 2026-07-19): mockups and design directions —
at this gate and during Stage 4 design decisions — are presented in the
browser-based visual companion, not as prose.** Findings lists and text
decisions stay in the terminal.

### Stage 4 — Implement

Via the normal pipeline: writing-plans → subagent implementation with
orchestrator review, model tiers per the desktop plan header.

Shape of the work (directions to be validated by Stage 2 findings, not
pre-decided):

- A small neutral design system inside `pages.py`'s single `_STYLE`
  stylesheet: type scale, spacing tokens, a notice/status component,
  button and table treatment, a score-display treatment. No external
  assets, no CSS frameworks (pages must stay self-contained localhost
  HTML).
- The cut-line findings applied through that system. Candidate directions
  the critique will confirm or kill: verdict-first results page (large
  score + plain-language judgment, methodology prose collapsed below);
  explicit ready-states for the two pickers; honest progress messaging
  for the grading wait and the bootstrap placeholder.

### Final gate

One more human walkthrough by Trevor in the desktop app (also produces
the screenshots for the Task 11 write-up).

## Invariants (binding on Stage 4)

- Pages remain shared: one codebase serves uvx browser users and the
  desktop webview; no desktop-only page forks beyond the existing
  feature-detected picker variant.
- The webview stays a renderer (standing rule): no new reliance on
  browser chrome; anything OS-adjacent goes to the shell.
- Accessibility baseline may only improve. The amendment's mechanisms
  (aria-live error region, focus management, aria-describedby path
  displays, aria-busy) survive any markup change.
- Engine files (`runner.py`, `cli.py`, `pairing.py`, `adapter.py`)
  untouched.
- `tests/test_pages.py` asserts on markup strings and will break with
  markup changes: updating those tests alongside is in-scope, expected
  work, not a deviation.
- The desktop placeholder (`desktop/ui/index.html`) is in scope (it is a
  page students stare at); the Rust shell is not, except as already
  committed.

## Out of scope

- New user-facing features (spec fence from the desktop design holds).
- Branding/identity work; UMD/HDC visual alignment.
- Deep WCAG/Title II audit (candidate for a later pass; fits the sprint
  lens but deliberately deferred by Trevor).
- After-grading guidance changes (not selected; revisit only if a Stage 2
  finding is severe).

## Review record

Brainstormed and approved interactively (Trevor, 2026-07-19): scope
multi-select, clean-and-credible bar, approach A (review-first), and the
four-stage shape. Spec PAR: pending.
