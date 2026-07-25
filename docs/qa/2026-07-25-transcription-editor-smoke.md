# Manual smoke test — transcription editor

**Date:** 2026-07-25
**Branch / HEAD:** `feat/dpi-eval-desktop` @ `eaaa5c4`
**Tester:** Trevor Muñoz
**Scope:** the manual QA left open by task 12 of 12 (see
`.git/sdd/task-12-report.md`). The automated suite (197 tests) was already
green and the whole-branch review verdict was "ready to merge pending this
checklist."

## Environment

| | |
|---|---|
| Machine | macOS (Darwin 25.5.0), Apple Silicon |
| Desktop app | Tauri 2 / WKWebView, launched from source (see below) |
| Browser mode | `uv run dpi-eval-web` → 127.0.0.1:8765 |
| Bundled runtime | CPython + offline wheelhouse, 84 files |
| Conventions version | v1 |

### Pre-flight: wheelhouse refresh

The bundled project wheel in `desktop/runtime/payload/wheelhouse/` dated
**Jul 19**, i.e. before the transcription editor existed (commits
`53b58c2..eaaa5c4`, Jul 24–25). The existing `.dmg` and the cached venv at
`~/Library/Application Support/edu.umd.dpi-eval/venv` therefore could not
contain the feature under test. Rather than re-download the full ~90 MB
wheelhouse, the dependency closure was diffed first:

    uv export --no-dev --no-emit-project --format requirements-txt
      vs. payload/wheelhouse/requirements.txt
    → identical except one comment line

`pillow==12.3.0` merely gained a `# via dpi-dinglehopper-eval` annotation:
declaring `pillow>=10` a direct dependency in task 3 added **zero new
wheels**, because `ocrd` already pinned that exact Pillow, whose macOS
arm64 wheel already ships OpenJPEG (JP2) and libtiff. So only the project
wheel was stale. It was rebuilt in place (`uv build --wheel`),
`requirements.txt` refreshed, and the `MANIFEST` content-hash recomputed
with the same recipe as `build_wheelhouse.sh:53`:

    79ea669d… → c34103ea…

The hash change is what makes `ensure_venv` (`lifecycle.rs:372`) discard
the stale venv and reinstall, so no manual cache clearing was needed.

**Offline-install rehearsal** (the same operation the app performs at
launch) passed: `pip install --no-index --find-links payload/wheelhouse
dpi-dinglehopper-eval` resolved the whole closure, and in the bundled
runtime `Pillow 12.3.0 jp2: True libtiff: True`, `dpi-eval-web` and
`dinglehopper` both on PATH. Unlike the earlier `--probe` payload, this
build has a real OCR engine, so grading is genuinely exercised below.

### Fixtures

Generated with Pillow (OpenJPEG-backed, real JP2) at
`~/dpi-eval-qa/2026-07-25/`:

| File | Role |
|---|---|
| `masters/page_0001.jp2` | 4 printed lines — transcribe and save |
| `masters/page_0002.jp2` | 3 printed lines — transcribe and save |
| `masters/page_0003.jp2` | no legible text — mark No text / illegible |
| `masters/page_0004.jp2` | legible — **unticked** at selection |
| `ocr/page_0001.txt` | matches `page_0001` by stem (2 deliberate OCR errors) |
| `ocr/page_0002_ocr.txt` | **deliberately misnamed** → lands unmatched, fixed by override |

Local sessions align OCR by exact stem equality (`alignment.py:46`), which
is why a single changed character in the second filename is enough to force
the unmatched/override path. All four JP2s decode through the app's own
derive path (`derive.image_dims` / `derive.derive` → JPEG, verified).

## Results

Legend: PASS / FAIL / BLOCKED / not yet run.

### Desktop app (WKWebView)

| # | Check | Result | Notes |
|---|---|---|---|
| 1 | Local-folder session from a folder with a JP2 master; from-scratch; collection label | **PASS** (after F1 fix) | First attempt FAILED — a valid folder was rejected (F1, F3). After the picker was added, the native dialog supplied `source.path` cleanly and the session was created. |
| 2 | Page selection prunes the queue (untick ≥1 page) | **PASS** | Unticked `page_0004`; `session.json` holds only `page_0001`–`page_0003`. The page is absent from the record entirely, not merely deselected — pruning happens at create, as specified. Editor header confirms "Page 1 of 3". |
| 3 | Typing: straight quotes NOT replaced by smart quotes in WKWebView | **PASS** | Typed `test "straight quotes" and don't`; quotes stayed vertical and the apostrophe straight. The textarea's `spellcheck`/`autocorrect`/`autocapitalize`/`autocomplete="off"` attributes hold in WKWebView, which the unit tests cannot establish. Probe line deleted before saving so the GT stayed clean for item 6. |
| 4 | JP2 master renders as derived JPEG; Enlarge lightbox opens full-res | **PASS** | JP2 master renders legibly in the editor via the local derive endpoint — no browser decodes JP2 natively, so this exercises Pillow/OpenJPEG inside the bundled runtime. Enlarge opens the `<dialog>` showing the master at genuine full resolution; Escape closes it. Usability friction logged as F6. |
| 5 | Mark a different page No text → illegible; save; status table shows Time (elapsed) **and** Time (active) | **PASS** | `page_0003` → `status: no_text`, `no_text_reason: 'illegible'`. Session page shows both timing columns populated: `page_0001` 203s/38s, `page_0002` 71s/36s, `page_0003` 0s/0s. Collection label `qa-smoke-2026-07-25` displayed. GT verified at byte level — em dash in `page_0002` survived NFC normalization intact. |
| 6 | Grade: alignment preview, one unmatched file fixed by override, confirm, results page opens | **PASS** | Preview auto-matched `page_0001`→`page_0001.txt`, offered a dropdown for `page_0002`, listed `page_0002_ocr.txt` as unmatched, and correctly omitted the `no_text` page entirely (`pages.py:922` skips non-saved pages before pairing). Override applied, `Grade` ran the real engine → `run-022`, `exit_code: 0`, `failed: []`, both pages graded, no failure section. |
| 7 | Export zip: `gt/` holds only saved pages; `transcriptions.json` covers every selected page with status, reason, arm, timings | **PASS** | Download reached `~/Downloads/dpi-eval-gt-s-20260725-163203-ca8b.zip` — **no fourth chrome failure**. Bundle rooted at `qa-smoke-2026-07-25/<sid>/`. `gt/` holds only the 2 saved pages (`page_0003` absent). `transcriptions.json` covers all 3 selected pages with `status`, `no_text_reason: "illegible"`, `arm` (per-page and top-level), and both timing fields. `page_0004` absent throughout, so create-time pruning holds all the way to export. Em dash preserved. |

Testing was halted at item 1 by decision of the tester — the missing native
folder picker (F1) was a blocker, not a note-and-continue — then resumed
after the fix and completed items 1–7.

### Browser mode

| # | Check | Result | Notes |
|---|---|---|---|
| 8 | `uv run dpi-eval-web`; IIIF session from a real UMD manifest (Presentation v2); transcribe one page from scratch; save; session page correct | **DEFERRED** | Not run — postponed by the tester at the end of the desktop pass. No manifest URL was supplied, so nothing was attempted and nothing is known either way. |

### What deferring item 8 leaves unknown

Not blockers, but they are genuinely untested rather than assumed-fine:

1. **The whole IIIF path.** Manifest fetch (stdlib `urllib`), Presentation v2
   parsing, and the image-less-canvas rejection guard.
2. **A different alignment rule.** IIIF sessions pair OCR by *trailing
   integer* against 0-based `source_index` (`alignment.py:39–42`), pinned to
   `iiif_ocr`'s `page_{i}` naming — not the stem equality that item 6
   exercised. The off-by-one risk lives here, not in the local path.
3. **The browser-mode half of the picker fix.** With no `__TAURI__`, the
   typed-path input must stay visible and functional. Unit tests cover the
   markup; no browser has rendered it.
4. **The controlled platform comparison.** F2, F5, F6 and F7 should reproduce
   identically in a browser. Confirming that would settle empirically that
   they are platform-independent rather than WKWebView symptoms — currently
   that rests on reading the code.

## WKWebView verdict — the circuit-breaker did NOT trip

Asked during the run: do these findings justify reopening the Electron
question? On this evidence, no.

Seven of the eight findings below are ordinary application defects that a
different runtime would have shipped unchanged — a missing link (F8), a
hardcoded heading (F2), CSS overlap (F5), lightbox markup (F6), an
un-itemized notice (F7), an uncalled helper (F1), and sidecar/venv
supervision (F4, which an Electron app bundling Python would hit
identically). Electron supplies Chromium and Node; it does not supply links,
labels, or layout.

**Zero new chrome-level failures were found.** The three already paid for on
this branch were folder-upload POSTs, downloads, and injection timing. This
run exercised all three areas and they held:

- **Downloads work.** The export `FileResponse` landed in `~/Downloads`
  (item 7) — the single test most likely to produce a fourth failure.
- **Native folder dialog works.** Driven from a loopback-served page via the
  `remote-dialog` capability, working on first wiring — the hard case for a
  webview.
- **Injection timing holds.** The new picker script probes `__TAURI__` only
  inside a `load` listener, guarded by a test.
- **Token injection works** — no 403 anywhere in the run.
- Also confirmed: JP2→JPEG derive, `<dialog>`/`showModal()` + Escape, and
  every form POST.

Note too that the design has already absorbed the earlier lessons: the
`ocr_folder` path field exists so OCR bytes never cross the webview
boundary, and `remote-dialog` was written in advance for precisely the
picker this run wired up.

One caveat: **F3 remains unexplained.** If its cause is WKWebView mangling
typed text, that would be a genuine chrome finding, since it would implicate
the transcription textarea. Item 3 passed cleanly (straight quotes and
apostrophes survived, em dash survived to disk), which is evidence against
that mechanism, but it is not closed.

## Findings

### F1 — Transcription forms make humans type file paths; the native picker was never wired to them (blocker)

**Severity:** blocker (tester stopped the run here).

The grading form has a real native folder picker. `pages.py` ships a
`wirePicker()` helper that calls
`window.__TAURI__.dialog.open({directory: true})`, hides the raw input, and
reveals a picker button (`pages.py:326–349`). It is invoked exactly twice,
for the grading form's two fields:

    pages.py:353  wirePicker('gt',  'gt_files',  'gt-picker-btn',  'gt-picker-path')
    pages.py:354  wirePicker('ocr', 'ocr_files', 'ocr-picker-btn', 'ocr-picker-path')

That script lives inside `form_page()` (the grade form). **None** of the
transcription pages — `transcribe_home_page`, `selection_page`,
`session_page`, `alignment_page`, `editor_page` — include it. So all three
transcription path fields are bare text inputs the human must type:

| Page | Field | Control shipped |
|---|---|---|
| `/transcribe` | `folder` (local image folder) | typed text |
| `/transcribe` | `draft_folder` (correction mode) | typed text |
| grade preview | `ocr_folder` | typed text |

The Tauri side is already fully provisioned for the picker on these pages.
`capabilities/` contains a purpose-built `remote-dialog` capability granting
`dialog:allow-open` to the loopback origin — with a comment explaining it is
scoped `local: false` precisely so the *sidecar-served form pages* can open
the native dialog, and wildcarding the port because `_pick_port` may fall
back off 8765. `tauri_plugin_dialog::init()` is registered in `main.rs:43`.
So this is an omission in the new pages, not a missing capability and not a
platform limitation: the permission, the plugin, and the helper function all
already exist and went unused.

**Tester's position (recorded verbatim in substance):** if we are selecting
files it should always be a picker; there is no reason to make humans type
file paths.

**This is NOT a fourth WKWebView chrome failure.** The webview did not
misbehave — the picker code was simply not included on these pages. The
Electron circuit-breaker is not tripped by F1.

### F2 — Shared error page is headed "Can't grade this batch" during transcription flows

`error_page()` hardcodes `<h1>Can't grade this batch</h1>` and a "Back to
the form" link to `/` (`pages.py:710–718`). Every transcription failure
renders through it, so a session-creation error is announced as a grading
failure and the recovery link leaves the transcription flow entirely. Cosmetic
but user-facing and misleading. Observed in the item 1 screenshot.

### F3 — Unresolved: a folder the sidecar can read was rejected through the form

Not root-caused, and deliberately left open rather than guessed at.

Established facts:

- The folder exists, is mode 755, holds the four JP2s, and its path is
  plain ASCII (hexdump-verified — no look-alike characters).
- The **same running sidecar** accepts that exact path: posting
  `folder=/Users/trevormunoz/dpi-eval-qa/2026-07-25/masters` with the token
  header returned HTTP 200 and the "Select the sample pages" list with all
  four pages. So the rejection is not a permissions or TCC/sandbox issue,
  and not a fixture problem.
- Therefore the string that reached `create_local_session` differed from
  the string on screen, which renders identically after `escape()`.

Hypotheses tested and **eliminated**:

- *Trailing whitespace* — posting the path with a trailing space still
  succeeded, so it is tolerated.
- *macOS smart-dash substitution (en dashes)* — reproduces an error, but
  renders visibly wider dashes than the screenshot shows. (Also, macOS
  smart dashes convert `--` to an em dash; they leave single hyphens
  alone.)

Outstanding evidence needed: the exact bytes of the field's contents at
submit time. Note that `folder` is passed to `Path()` unstripped
(`web.py:425`), whereas `collection` *is* stripped (`sessions.py:123`) — an
asymmetry worth a look when this is diagnosed.

A picker (F1) would supply this value programmatically and so would mask F3
rather than explain it. Worth keeping the distinction: F1 is the blocker,
F3 is an unexplained input-handling defect that a picker would hide.

### F4 — An orphaned sidecar makes the next launch fail setup with SIGKILL

Triggered accidentally during this session while restarting the app, but the
sequence is reachable without a developer present, so it is recorded.

What happened: a `dpi-eval-web` sidecar from a previous launch was still
running, with its interpreter at `…/edu.umd.dpi-eval/venv/bin/python3`. The
wheelhouse hash had changed, so `ensure_venv` took its rebuild branch and
ran `remove_dir_all(&venv)` (`lifecycle.rs:380`) — deleting the tree the
live process was executing from. The subsequent `python3 -m venv` was killed
by the OS:

    [dpi-eval-desktop] (re)building venv at …/edu.umd.dpi-eval/venv
    [dpi-eval-desktop] startup failed: create venv failed (signal: 9 (SIGKILL))

The user-facing result is the "Setup didn't finish / show this screen to
library staff" panel, and it does **not** self-heal on the retry the panel
advises while the orphan survives.

Why it matters beyond this session: `tauri_plugin_single_instance` guards a
second *app* instance but nothing reaps an orphaned *sidecar*. So "app
exited without reaping its sidecar, then the payload was updated" — an app
upgrade being the obvious real-world trigger — dead-ends a non-technical
user on a managed lab machine with no terminal, which is precisely the
failure class `desktop/PROBE-CHECKLIST.md` exists to catch. Candidate
mitigations (not implemented): refuse to delete a venv that has a live
process, or reap a stale sidecar before rebuilding.

Not a WKWebView chrome failure.

### F5 — Editor page controls overlap at the bottom of the window

Observed in the item 3/4 screenshot (desktop, default window size). Below the
"Save & next" button:

- the **Mark** button (for "No text on this page") overlaps the "Flag for
  supervisor" row beneath it;
- the **Update flag** button overlaps the `note` text input to its left.

The buttons appear oversized relative to their rows, so the two secondary
control rows collide rather than stacking. Both controls are still reachable,
so this is presentation rather than function — but the overlapping row is
exactly the "mark a page no-text" control a typist uses constantly, and it
is the control item 5 depends on.

Not yet checked at a taller window size or in browser mode, so it is not
established whether this is a viewport-dependent layout collapse or
unconditional. Logged for a layout pass, not fixed.

### F6 — Enlarge lightbox: no fit-to-window, and Close is below a full-height image

Functionally passing (item 4), recorded as friction.

`pages.py:979–981` renders the lightbox as a `<dialog>` capped at
`95vw × 95vh` with `overflow:auto`, containing an `<img>` with **no**
`max-width` — intentionally, since that is what makes "full resolution"
literal. Two consequences on a 1700×2200 master:

1. **Both axes scroll and there is no fit-to-window control.** Observed:
   lines clipped mid-word at the right edge, so reading a full line means
   scrolling horizontally and back.
2. **The Close button follows the image in DOM order**, putting it roughly
   an image-height below the fold. A mouse-only user scrolls the whole page
   image to reach it.

Escape does close the dialog (verified), so the keyboard path is fine and
this is not a trap. But Enlarge exists so a typist can decipher difficult
text, and that is exactly the task that pays the scrolling cost. A
fit-to-window default (with an opt-in to 1:1) and a Close control that stays
in view would address it.

### F7 — "N changes applied by conventions v1" never says which changes

After saving `page_0002` the editor reported *"2 changes applied by
conventions v1"*. `normalize()` counts **rules that fired**, not characters
(`conventions.py:18–48`), and the notice names neither the rules nor the
affected lines. The typist is told their transcription was rewritten but
cannot see what changed, so they cannot check the result against the page —
in a tool whose output is ground truth, and which elsewhere makes a point of
showing rather than silently recording (the timing disclosure), that is an
inconsistency.

In this run the changes were benign whitespace normalization (the missing
final newline certainly fired; one whitespace rule fired alongside it) and
the em dash survived, verified by reading the GT bytes. But that verification
took a hexdump — it is not available to a student.

Naming the rules that fired, or showing them, would close the gap. Not fixed.

### F8 — Grading from a session dead-ends: the results page cannot get back to the session

Hit immediately after item 6. Having graded from within a session, there is
no control on the results page that returns to that session.

`results_page` appends exactly one exit link — `<a href="/">`, labelled
"Grade another batch" or "Back to the form" (`pages.py:528–529`). It offers
no link to `/transcribe/sessions/{sid}`, and none to `/transcribe` either.
The cause is structural rather than an oversight in the markup:
`results_page` is never given the session id. `grade_confirm` has `sid`, but
calls `_run_and_register(gt_dir, ocr_dir, base_dir)`, which knows only about
run directories — the session identity is dropped at that boundary.

**Severity is higher in the desktop app than it would be on the web.** A
browser user would press Back or edit the URL; a WKWebView has no address
bar, so a missing in-page link makes the page genuinely unreachable rather
than merely inconvenient. This is the "renderer, not a browser" rule biting
from the unfamiliar direction: with no chrome to fall back on, in-page
navigation is the *only* navigation.

And the unreachable page is the one holding **Export for repo**, "New
session from this selection (other arm)", and the remaining transcription
queue — i.e. the workflow the README documents as transcribe → grade →
export.

Reachable only by an indirect three-hop route: results → "/" (grading form)
→ "Transcribe a sample" → sessions list → the session. Nothing signposts it.

Threading `sid` through to `results_page` and rendering a "Back to session
<id>" link would close it. Not fixed.

### Open question (not a defect) — is ≤10% WER "Strong" for the accessibility use case?

`run-022` scored 8.4% aggregate WER and the verdict block rendered green
**STRONG**. That is specified behaviour, not a glitch: `_band()`
(`pages.py:392–404`) documents green ≤10%, amber ≤25%, red above, and
attaches a word to every band because colour alone fails accessibility.

Raising it because the same run shows why the number is delicate: page_0001
scored **CER 3.4% against WER 9.1%** — the character rate flatters by nearly
3×. Headlining WER rather than CER is the right instinct and matches the
lesson of Trevor's 2009 D-Lib work. But 8.4% WER is about one word in twelve
wrong. For a discovery index that may be strong; for a screen-reader user
consuming this as the text alternative to a paged object it reads
differently, and a wrong proper noun or number costs far more than a wrong
function word (the significant-word-accuracy question).

Whether the green band should sit at ≤10% for this charter is a domain
judgment for Trevor, so it is recorded here rather than filed as a bug.

### Positive observation — timing separation does the work it was designed to do

Recorded because it is the pilot's central evidence claim, and it held:
`page_0001` was 203s elapsed against 38s active (5.3×, inflated by
conversation between keystrokes), `page_0002` 71s against 36s (2×). A single
"time per page" figure would have reported page 1 as 3.4 minutes of labour
when 38 seconds of it was typing. `active` also scaled with text length
(38s/4 lines, 36s/3 lines) rather than defaulting, so the 5-second idle
cutoff is tracking real keystrokes.

## Fix applied during this session (scope change agreed mid-run)

The tester's instruction changed from "log, don't fix" to a hard block on
F1, and the fix scope was then confirmed explicitly: **all three** path
fields, **picker-only** mirroring the grade form (raw typed input hidden
when the native dialog is available, retained in browser mode where there is
none).

Implemented test-first in `pages.py`:

- `_picker_field(field, label, button)` renders the typed input wrapped in a
  `<p id="{field}-typed">`, plus a `hidden` `<button type="button">` and the
  `.picked` confirmation row, matching the grading form's markup contract
  (`aria-describedby` pointing at the path row).
- `_PICKER_SCRIPT` / `_picker_script(fields)` reveals the button and wires
  `window.__TAURI__.dialog.open({directory: true})`, writing the chosen path
  straight into the input the form already posts. No new endpoint was needed
  — unlike the grading form, these fields were always text paths, so the
  existing POST carries the value unchanged.
- Wired to `folder` + `draft_folder` (`transcribe_home_page`) and
  `ocr_folder` (`session_page`).
- On dialog error the typed field is restored rather than leaving the user
  with a dead button.

The `__TAURI__` probe sits inside a `load` listener, guarded by a test, because
init-script ordering racing page scripts (tauri#12990) was one of the three
chrome-level failures already paid for on this branch.

Eight tests were written first and watched fail; suite went **197 → 205
passing**. Labels lost their now-misleading "(desktop)" hints, since the
typed field is the browser-mode control.

**Still outstanding:** F3 is unexplained. The picker supplies the path
programmatically and so routes around it; it does not explain it. If
something is mangling typed text in this webview, the transcription textarea
(item 3) is the next place it would show up — which the remaining checklist
still needs to establish.

Other bugs here are recorded, not fixed.

## Summary

**Desktop items 1–7: all PASS.** Item 1 failed on first attempt and was
unblocked by fixing F1. Item 8 (browser/IIIF) deferred.

Eight findings, one fixed:

| # | Finding | Severity | Status |
|---|---|---|---|
| F1 | Transcription forms made humans type file paths; native picker unwired | blocker | **fixed** |
| F8 | Grading from a session dead-ends — no route back to the session | high (unreachable in a webview) | logged |
| F4 | Orphaned sidecar → setup fails with SIGKILL, no self-heal | medium | logged |
| F3 | A folder the sidecar can read was rejected through the form | medium, **unexplained** | logged |
| F5 | Editor controls overlap at the bottom of the window | low | logged |
| F7 | "N changes applied" never says which | low | logged |
| F6 | Lightbox: no fit-to-window, Close below a full-height image | low | logged |
| F2 | "Can't grade this batch" heading on transcription errors | cosmetic | logged |

Plus one open domain question (is ≤10% WER "Strong" for the accessibility
charter?) and one positive confirmation (elapsed-vs-active timing separation
does the work it was designed for).

**The WKWebView circuit-breaker did not trip** — zero new chrome-level
failures; downloads, the native dialog, injection timing, and token
plumbing all held.

### Remaining step

Merge/PR decision. Per the repo's Ship / Show / Ask rule this branch is
"Ask"-shaped: it is a large feature, and the manual QA it was gated on has
now surfaced seven unfixed findings plus a mid-run behaviour change (the F1
fix) that arrived after the "ready to merge" review verdict.

The PR body must state the wheelhouse impact. Evidence gathered during this
session sharpens the usual claim: declaring `pillow>=10` a direct dependency
added **zero** new wheels, because `ocrd` already pinned that exact
`pillow==12.3.0`, whose macOS arm64 wheel already bundles OpenJPEG (JP2) and
libtiff. Manifest fetching is stdlib `urllib`, so also zero extra wheels. The
dependency closure was diffed against the previously built wheelhouse and was
identical but for one `# via` comment.

## Notes on expected (non-bug) behaviour

- IIIF manifests whose canvases lack images are **rejected by design**,
  protecting the 0-based alignment that `iiif_ocr`'s `page_{i}` naming
  depends on. A rejection is correct behaviour, not a defect.
- Unmatched pages in the alignment preview are **not graded**; they count
  as neither pass nor failure.
