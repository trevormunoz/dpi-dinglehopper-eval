# Manual smoke test — transcription editor

**Date:** 2026-07-25
**Branch:** `feat/dpi-eval-desktop`. **HEAD at start:** `eaaa5c4`.
**Code actually exercised:** items 1–7 ran against the F1 fix, later
committed as `df35043` — i.e. working-tree code that no listed commit
contained at the time. Corrected after PAR review (E3); the original
header cited `eaaa5c4` alone, from which these results cannot be
reproduced.
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
| 2 | Page selection prunes the queue (untick ≥1 page) | **PASS** | Unticked `page_0004`; `session.json` holds only `page_0001`–`page_0003`. The page is absent from the record entirely, not merely deselected. (Correction, PAR E4: pruning happens at **confirm**, not create — `create_local_session` records all four images (`sessions.py:148`) and `confirm_session` filters them (`sessions.py:190`). Outcome as stated; mechanism was wrong.) Editor header confirms "Page 1 of 3". |
| 3 | Typing: straight quotes NOT replaced by smart quotes in WKWebView | **PASS** | Typed `test "straight quotes" and don't`; quotes stayed vertical and the apostrophe straight. The textarea's `spellcheck`/`autocorrect`/`autocapitalize`/`autocomplete="off"` attributes hold in WKWebView, which the unit tests cannot establish. Probe line deleted before saving so the GT stayed clean for item 6. |
| 4 | JP2 master renders as derived JPEG; Enlarge lightbox opens full-res | **PASS** | JP2 master renders legibly in the editor via the local derive endpoint — no browser decodes JP2 natively, so this exercises Pillow/OpenJPEG inside the bundled runtime. Enlarge opens the `<dialog>` showing the master at genuine full resolution; Escape closes it. Usability friction logged as F6. |
| 5 | Mark a different page No text → illegible; save; status table shows Time (elapsed) **and** Time (active) | **PASS** | `page_0003` → `status: no_text`, `no_text_reason: 'illegible'`. Session page shows both timing columns populated: `page_0001` 203s/38s, `page_0002` 71s/36s, `page_0003` 0s/0s. Collection label `qa-smoke-2026-07-25` displayed. GT verified at byte level — em dash in `page_0002` survived NFC normalization intact. |
| 6 | Grade: alignment preview, one unmatched file fixed by override, confirm, results page opens | **PASS** | Preview auto-matched `page_0001`→`page_0001.txt`, offered a dropdown for `page_0002`, listed `page_0002_ocr.txt` as unmatched, and correctly omitted the `no_text` page entirely. (Correction, PAR E5: pairing runs **first**, in `stage_ocr` → `align(session["pages"], …)` (`sessions.py:351`) over *all* pages including `no_text`; the saved-only filter lives in `alignment_page`, the renderer, and runs after. The outcome was right, the stated cause was not — and the same wrong explanation was given verbally during the run.). Override applied, `Grade` ran the real engine → `run-022`, `exit_code: 0`, `failed: []`, both pages graded, no failure section. |
| 7 | Export zip: `gt/` holds only saved pages; `transcriptions.json` covers every selected page with status, reason, arm, timings | **PASS** | Download reached `~/Downloads/dpi-eval-gt-s-20260725-163203-ca8b.zip` — **no fourth chrome failure**. Bundle rooted at `qa-smoke-2026-07-25/<sid>/`. `gt/` holds only the 2 saved pages (`page_0003` absent). `transcriptions.json` covers all 3 selected pages with `status`, `no_text_reason: "illegible"`, `arm` (per-page and top-level), and both timing fields. `page_0004` absent throughout, so the confirm-time prune holds all the way to export. Em dash preserved. |

Testing was halted at item 1 by decision of the tester — the missing native
folder picker (F1) was a blocker, not a note-and-continue — then resumed
after the fix and completed items 1–7.

### Browser mode

| # | Check | Result | Notes |
|---|---|---|---|
| 8 | `uv run dpi-eval-web`; IIIF session from a real UMD manifest (Presentation v2); transcribe one page from scratch; save; session page correct | **PASS, with two findings** | Run 2026-07-26 in Chrome against a real third-party manifest. Ingest, indexing, save, timing and export all correct. Transcription is impractical on dense paged text (F9) and the active-timer records 0s for bulk-inserted text (F10). |

## Item 8 — run 2026-07-26

Deferred on 2026-07-25 for want of a manifest URL; run the next day against
**UMD's own repository**, in a real browser (Chrome), not the desktop shell.

Target: *AFL-CIO Labor Studies Center, 1975* — 6 canvases, Presentation v2,
from the AWR collection. A 1975 typescript, so genuinely dense paged text.
Full target list and the search API that finds more:
`docs/qa/item-8-iiif-targets.md`.

```
https://iiif.lib.umd.edu/manifests/fcrepo:dc:2023:1:b3:7f:3e:17:b37f3e17-f230-4da8-a472-e95584112ebd/manifest
```

### Prerequisite discovered before the run could start

UMD fronts `iiif.lib.umd.edu` with a WAF that filters on `User-Agent`, so
`fetch_manifest` could not reach any UMD manifest at all — item 8 would have
died at the first request. Measured: `Mozilla/5.0 (Macintosh…)` → 200,
`Python-urllib/3.11` → 400, an honest `dpi-eval/0.1.0` → **400**, no
User-Agent → 403. Fixed by `DPI_EVAL_USER_AGENT` (`7791588`), which keeps the
honest value as the default and makes the failure self-explaining, since the
honest value is the one rejected.

### What passed

- **Manifest fetch and parse** — 6 canvases from a manifest neither we nor an
  agent wrote. This is what most needed testing: R2-C1 and R2-S2 both lived in
  this parser.
- **Canvas indexing** — stems `p0000-page-1` … `p0005-page-6`; 0-based indices
  against 1-based labels, which is precisely what R2-S2 was about.
- **Selection as queue** — 2 of 6 ticked, and only those 2 appeared.
- **Image loading in a real browser.** The page image loaded directly from
  `iiif.lib.umd.edu` even though the Python-side fetch needed the override —
  the predicted asymmetry (WKWebView/Chrome send their own browser UA for
  `<img>`) held. Editor request `full/!1200,1200/0/default.jpg` → 922x1200
  JPEG; service reports level2 at 3324x4324.
- **Timing accumulates across visits.** `sessions.py:416-417` uses `+=`, so a
  re-edit adds rather than replaces: 192s+32s elapsed, 0s+25s active. Both
  columns visible on the session page — no silent telemetry.
- **Export asymmetry.** `gt/` held only the saved page; `transcriptions.json`
  covered both, page 2 as `pending`. UTF-8, LF, trailing newline. Each page
  records its `canvas_id` (`/canvas/0`, `/canvas/1`) — the audit trail that
  would have made an R2-S2 skew visible after the fact.
- **Browser-mode picker.** The typed-path input stayed visible and usable with
  no `__TAURI__` present, which unit tests asserted but no browser had shown.

### F9 — no usable reading size for dense paged text (blocker for paged media)

Two views, neither usable:

| View | Delivered | Displayed | Problem |
|---|---|---|---|
| Inline pane | 922x1200 | ~315px wide | Too small to read |
| Enlarge | 3324x4324 | 1:1, scroll only | Too big to navigate |

`body { max-width: 44rem }` (`pages.py:24`) with a two-column split leaves the
image ~315px, and the lightbox `<img>` (`pages.py:1147-1148`) has no
`max-width`, so it renders at natural size inside a `95vw` dialog with
`overflow:auto` — scroll-only at 1:1, landing on blank margin. Tester's words:
*"Goes too big with only scroll controls not zoom. So not very practicable to
use."*

This **supersedes F6**, which logged the lightbox half as cosmetic polish. Same
code, blocker severity, because the material changed: items 1–7 used synthetic
fixtures whose text survived a 315px pane. Real archival typescript does not.

The capability is already paid for — the IIIF Image API serves any region at
any size and `derive.py` implements `regionByPx`. The tool requests one fixed
size and then discards most of it.

Two candidate fixes, not yet chosen: cap the lightbox image
(`object-fit:contain`) and widen the inline pane; or adopt a zoom-and-pan
viewer driven by the Image API, which is a build-vs-adopt decision.

### F10 — the active-time metric measures keystroke count, not effort (high)

`pages.py:1189-1195` accumulates only the *gap between consecutive* `input`
events, guarded by `if (lastInput && …)`. N events yield N-1 intervals, so any
edit completed in a **single** input event records **0s active** — and nothing
distinguishes that from a page nobody touched. Observed directly: a pasted
transcription saved as `192s elapsed / 0s active`; typing on the same page then
added `32s / 25s`, confirming the tracker is fine for character-by-character
input.

Because timing accumulates, this is permanently lossy: the paste visit's
elapsed seconds stay in the total while its active seconds never arrive, so the
two columns describe different sets of visits for the same page. Any
active-to-elapsed ratio — the natural way to read them together — is then wrong
in the direction that makes the work look easier than it was.

The consequence that matters for this project: **the metric under-reports for
exactly the input methods the accessibility charter cares about.** Dictation,
an IME, and assistive tech that inserts text in chunks all fire far fewer
`input` events than typing. A student using a Japanese IME, where composition
commits whole phrases, would show much lower "active" time than a QWERTY typist
doing identical work — directly relevant to the Japanese-books CER flag.
"Tell students not to paste" is not the fix; the metric should distinguish
*pasted*, *dictated* and *untouched* instead of collapsing all three to 0s.

### Data hygiene note

The GT saved in this session must not be treated as pilot data. The first save
was a paste of text the assistant had read off a screenshot; the tester then
typed three lines themselves (visible in the export as `Leonard Lewis Jr.`,
without the comma the assistant's reading had). Discard the session before any
real collection.

### Still not covered by item 8

- **The IIIF OCR alignment rule.** Grading was not exercised: these documents
  have vendor OCR upstream (`has_ocr` in the search API) but the tool does not
  fetch it, and no OCR folder was supplied. Pairing by *trailing integer*
  against 0-based `source_index` (`alignment.py:39-42`) therefore remains
  untested against real IIIF material.
- **The controlled platform comparison** for F5 and F7. F9's inline-pane half
  did reproduce in Chrome, confirming it is not a WKWebView symptom.

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
- **Injection timing.** The new picker script probes `__TAURI__` only inside
  a `load` listener. *Correction (PAR E6/S1): this was originally written as
  "holds … guarded by a test". The guard compared textual offsets and passed
  against the very regression it forbade, so no runtime property had been
  established. Real containment and behavioural coverage were added
  afterwards in `tests/test_picker_script.py`, which execute the script and
  record when `__TAURI__` is first read.*
- **Token injection works** — no 403 anywhere in the run.
- Also confirmed: JP2→JPEG derive, `<dialog>`/`showModal()` + Escape, and
  every form POST.

Note too that the design has already absorbed the earlier lessons: the
`ocr_folder` path field *permits* avoiding the webview boundary for OCR
bytes (corrected, PAR E7: "never" was wrong — the same form also ships
`<input type="file" name="ocr_files" multiple>`, and at the time of this
smoke test `web.py:526–530` read whichever arrived), and `remote-dialog`
was written in advance for precisely the picker this run wired up.
**Since fixed:** as of round-2 review finding S4, `web.py:574–586` rejects
the request with a 400 — "Two OCR sources arrived together" — when both
the folder field and an upload are present, rather than silently picking
one. (Line numbers per the committed HEAD at the time of this correction;
a separate uncommitted edit in progress elsewhere in this file may shift
them further.)

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

**Corrected after PAR review (E1). The mechanism first written here was
wrong, and was asserted rather than established.** The original text claimed
`remove_dir_all(&venv)` deleted the tree the running interpreter was
executing from, and that this caused the SIGKILL. It cannot have:
`ensure_venv` creates the venv with `bundled_python(resource_dir)`
(`lifecycle.rs:385`), which resolves inside the app bundle
(`lifecycle.rs:320–328`) and is untouched by that delete. F3 was correctly
marked "unexplained"; this deserved the same treatment and did not get it.

What is actually observed: a `dpi-eval-web` sidecar from a previous launch
was still running out of `…/edu.umd.dpi-eval/venv/bin/python3`. The
wheelhouse hash had changed, so `ensure_venv` took its rebuild branch and ran
`remove_dir_all(&venv)` (`lifecycle.rs:381`). The subsequent
`python3 -m venv` was then killed by the OS:

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

**Reproduced at the end of the session.** On shutting the app down, the
sidecar was left running again (`…/venv/bin/dpi-eval-web --no-browser`, still
alive after the app process was gone) and had to be killed by PID.

**The orphan half now has a verified mechanism — PAR S7, and it is worse than
what was written here.** The original conclusion was that the orphan happens
"whenever the app dies *without* a graceful quit". That understated it
(PAR E2): the graceful path is fully instrumented — `main.rs:155–159` calls
`shutdown()` on both `ExitRequested` and `Exit`, and `lifecycle.rs:595–621`
does `killpg(SIGTERM)` then `SIGKILL`. The reason it fails anyway is that
`lifecycle.rs:649` blocks `SIGTERM`/`SIGINT` with `pthread_sigmask`, and
`pre_exec` (`lifecycle.rs:525–530`) calls only `setsid()` — it never restores
the mask. Signal masks survive `execve`, so the sidecar inherits both signals
blocked, `killpg(SIGTERM)` is ignored, the `TERM_GRACE` loop always expires,
and every quit ends in `SIGKILL` with uvicorn's graceful shutdown never
running. The orphan is therefore reachable on the *instrumented* path, not
only through crashes.

What remains genuinely unexplained is the **SIGKILL of the freshly spawned
`python3 -m venv`**, since that interpreter lives in the app bundle. A
plausible neighbouring class is the signing/quarantine behaviour catalogued
in `desktop/PROBE-CHECKLIST.md`, but that is a hypothesis, not a finding.

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

## Corrections applied after PAR review

This record was adversarially reviewed (see
`docs/qa/2026-07-25-par-review-pr1.md`). Ten errors were found in it and in
the session's other output. Corrections are inline above rather than silently
amended; in summary:

- **E1/E2** — F4's causal chain was asserted, not established, and its
  conclusion understated the defect. Both corrected; the verified mechanism
  is PAR S7.
- **E3** — the stated HEAD predated the code the results came from.
- **E4** — pruning happens at confirm, not create.
- **E5** — the `no_text` page is skipped at render, not before pairing.
- **E6** — "injection timing holds, guarded by a test" was unsupported; the
  guard passed against the regression it forbade.
- **E7** — "OCR bytes never cross the webview boundary" overstated.
- **E8** — `capabilities/remote-dialog.json` does not exist; the file is
  `remote.json`. Fixed in code, tests, and this record.
- **E9** — F2 and F5 cite screenshots that live only in the QA conversation,
  not in the repository, so neither finding is reproducible from what is
  committed here. F5's substance is additionally unverified against source:
  the controls it describes as overlapping are ordinary sibling block
  `<form>` elements in normal flow (`pages.py:926–945`) and `_STYLE` has no
  absolute/fixed positioning, negative margins, or floats. Treat F5 as
  "evidence unavailable", not as an established defect.
- **E10** — several line citations were taken from the post-fix working tree
  while this document declared `eaaa5c4`; `lifecycle.rs:380` should be `:381`.

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

- IIIF manifests whose canvases lack images are **rejected by design** —
  protecting the 0-based alignment that `iiif_ocr`'s `page_{i}` naming
  depends on. At the time of this smoke test, PAR review (S9) had found a
  hole: a Presentation v3 `Choice` body was unhandled, so `image_url`
  became `""` while the canvas still counted, and the guard passed anyway.
  **That hole is fixed as of `2d75b05`** — `_resolve_v3_body` now unwraps
  `Choice` and array bodies, and an empty resolved id is treated as "no
  usable image" for every v2/v3 shape, so it routes through the existing
  canvas-count guard (`tests/test_iiif.py::test_parse_rejects_manifest_with_empty_image_url_in_v3_body`
  passes at HEAD). Round 2 then found a separate gap in the same guard — a
  non-`Canvas` `items` entry was skipped *before* the counter incremented,
  removing it from both sides of the comparison and skewing every later page
  index. That is R2-S2, and it is also fixed: `parse_manifest` now raises
  `IIIFError` for any `items` entry whose `type` is not exactly `Canvas`,
  rather than skipping it. Neither gap is the hole this note originally
  described.
- Unmatched pages in the alignment preview are **not graded**; they count
  as neither pass nor failure.
