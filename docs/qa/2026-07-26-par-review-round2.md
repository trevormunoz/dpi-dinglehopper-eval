# PAR review round 2 — the 18-finding fix-up

Date: 2026-07-26. Target: combined state of `22cd687^..5e02882` on
`feat/dpi-eval-desktop` (PR #1), plus `dba9425` and `11c4548`. Two reviewers,
identical brief, run in parallel, neither seeing the other. Aggregation rule:
findings both reviewers reached are high-confidence; singletons stay
actionable; on severity disagreement the worse assessment wins.

Round 1 (`2026-07-25-par-review-pr1.md`) produced 3 critical + 21 serious. All
were fixed across six commits. This round reviews that fix-up. CI was green on
both `macos-latest` and `windows-latest` at the time of review.

Numbering is `R2-*` to keep it distinct from round 1's `C*`/`S*`.

## Critical

### R2-C1 — a manifest with a non-string `id` is accepted, then the page it creates is permanently un-openable

`iiif.py:215`, `:164`, `:99` → `pages.py:762`. Reviewer B, confirmed by
execution.

`2d75b05` added ten `isinstance` guards for *container* shapes (`items`,
`canvases`, `images`, `body`) and none for the *scalar* values pulled out of
them. `image_url = body.get("id", "")` (v3), `resource.get("@id", "")` (v2)
and `_service_id`'s `service.get("id")` take whatever is there. A non-string
`id` is truthy, so `if not image_url: continue` does not fire, the canvas
count check at `iiif.py:226` passes, and the record is written to
`session.json`. The editor then calls `_safe_url(page["image_url"])`, which
does `.startswith()` on a `dict`.

Reviewer B drove the whole flow: `parse_manifest` accepted a v3 body with
`"id": {"evil": 1}`; `POST /transcribe/sessions` → 200; `.../confirm` → 200;
`GET .../pages/0` → **500** (`AttributeError: 'dict' object has no attribute
'startswith'`). The session exists and can never be opened.

Fix: require `isinstance(..., str)` for `@id`/`id`/service ids, and treat a
non-string as "no usable image" so the index-skew guard rejects the manifest
rather than storing it.

## Serious

### R2-S1 — the token gate still faults instead of denying, for a shape round 1 did not test

`web.py:239-241`, reached from `web.py:534`, `:569`, `:619`. Reviewer A,
confirmed by execution; Reviewer B reached the adjacent ordering issue.

The S12 fix made the comparison `(supplied or "").encode("utf-8")`, which
handles a non-ASCII `str`. It does not handle a non-`str`. `editor_action`,
`grade_preview` and `grade_confirm` all pass `form.get("token")` straight in,
and `form.get` returns an `UploadFile` when `token` arrives as a *file* part —
which has no `.encode`.

```
/transcribe/sessions/.../pages/0        -> AttributeError: 'UploadFile' object has no attribute 'encode'
/transcribe/sessions/.../grade/preview  -> AttributeError ...
/transcribe/sessions/.../grade/confirm  -> AttributeError ...
```

`multipart/form-data` is CORS-safelisted, so this is reachable from any page
with no preflight. Contract 1: a gate that raises is not a gate. The round-1
test at `tests/test_web_token.py:25` covers only the non-ASCII `str` shape.

### R2-S2 — index skew is still reachable: the skip happens before the counter increments

`iiif.py:184-186` vs the guard at `:226`. Reviewer A rated serious and
confirmed by execution; Reviewer B reached it and rated minor. Worst wins.
Verified independently at source.

`if canvas.get("type") != "Canvas": continue` runs *before* `canvas_count +=
1`, so a malformed item is removed from **both** sides of the `len(records) !=
canvas_count` comparison and the guard cannot see it. Every other malformed
shape in this function raises; only this one silently continues.

Three canvases with the middle one missing `type`:

```
ACCEPTED, n=2
  index 0 -> https://x/i/0.jpg
  index 1 -> https://x/i/2.jpg   <-- canvas 2's image at index 1
```

Contract 3 exactly. Page 1's hand transcription would be graded against
canvas 2's `page_1` OCR, and nothing in the output would say so.

### R2-S3 — a rejected `grade/confirm` deletes the upload its own error message tells the student to fix

`web.py:628-629`. Both reviewers, both confirmed by execution.

`sess.clear_staging(...)` sits in a bare `finally`, so it runs on every error
path out of `stage_for_grade` — bad override name, unresolved needs-attention
pages, no saved transcriptions. After a successful preview, a confirm with a
rejected override returns 400 saying *"Override for … which is not a plain
filename from the staged OCR upload"* — and the staged OCR upload has just
been deleted. Retrying gives *"Upload or pick the OCR folder first (preview
step)."* The student must re-pick the whole folder.

`sessions.py:450-453` states the principle verbatim: "do the check ahead of
`clear_staging`, or a rejected upload would also destroy the staging that was
already there." The violation is one file over, in the commit titled "honest
errors." `clear_staging` belongs on the success path.

### R2-S4 — staging and export are the only session mutators left outside `session_lock`

`sessions.py:445`, `:480`, `:525-527`, `:551-553`. Both reviewers; A confirmed
by execution.

Contract 5 is satisfied for `session.json` and not for `staging/`. `stage_ocr`
does `clear_staging` → `mkdir(parents=True)` (no `exist_ok`) → write →
`align(ocr_dir.iterdir())`, unserialised — and these are the paths that decide
which OCR file grades which page. Two concurrent `stage_ocr` calls produce
`FileExistsError` out of the route as an unhandled `OSError` (500), not a
`SessionError`. The same window lets one request's `clear_staging` land
between another's write and its `align()`, so the alignment table shown can
describe files that are no longer staged. `stage_for_grade` and
`export_session` have the identical unguarded `rmtree` + `mkdir` pair.

### R2-S5 — `session_lock`'s stale break can put two writers in the critical section, and it has no tests

`sessions.py:118-126`, `:137-145`. Reviewer B rated serious; Reviewer A
reached the same release-path asymmetry and rated it minor. Worst wins.

A waiter that judges a lock stale `unlink()`s it and acquires — but cannot
tell the original holder it lost the lock. The holder's `depths[key]` is still
`1`, so (a) holder and breaker are both inside the critical section, which is
the lost update `74b9667` was written to prevent, and (b) when the holder
exits, `sessions.py:143` unlinks the **breaker's** lock file, admitting a
third caller mid-write.

Reachability is worse than the 10s-timeout-vs-60s-stale gap suggests:
staleness uses `time.time()` (wall clock) while the acquire deadline uses
`time.monotonic()`. A laptop sleep or an NTP step during a save makes `age >
60` for a lock a millisecond old.

`grep -rn "session_lock\|LOCK_STALE\|LOCK_TIMEOUT" tests/` → no matches. The
concurrency primitive added to fix a data-loss finding has zero direct tests.

Minimum fix: write a nonce into the lock file; the holder verifies it still
owns the file before unlinking.

### R2-S6 — an empty flattened basename writes to the directory itself (two call sites)

`sessions.py:457-472` (Reviewer B) and `web.py:40-49` → `:77` (Reviewer A).
Both confirmed by execution.

`Path(name).name` is `""` for `"."`, `".."` and `"/"`. Both hidden-file guards
test `flat.startswith(".")`, which is False for `""`, so `(dir / "")` resolves
to the directory and `write_bytes` raises `IsADirectoryError`.

- `stage_ocr(root, sid, [(".", b"x")])` → `IsADirectoryError`; end-to-end
  `POST .../grade/preview` with filename `.` → 500. The collision check runs
  before `clear_staging` but this write runs after, so the request destroys
  existing staging on its way to the traceback.
- `/grade` with `filename="/"` → `IsADirectoryError` after `run-001/gt` was
  already populated, leaving a partial run directory.

Guard on `if not flat or flat.startswith(".")`.

### R2-S7 — `info.json` advertises `level1` while rejecting level-1-required forms

`derive.py:154-164`, `:42-45`. Both reviewers, both confirmed by execution.

Per the IIIF Image API 3.0 compliance table, level 1 requires `regionByPx`,
`regionSquare`, `sizeByW`, `sizeByH`, `sizeByWh`, `baseUriRedirect` and
`cors`. This service rejects `region=square`, has no regex accepting a bare
`w,h` (so `sizeByWh` 400s), has no bare-`{n}` → `info.json` redirect, and sets
no CORS headers.

`parse_params("full", "300,200", ...)` → 400 `Unsupported size`;
`parse_params("square", "max", ...)` → 400 `Unsupported region`;
`info_json(...)["profile"] == "level1"`.

Note both reviewers reached separately: `derive.py:154-164` is byte-identical
to pre-fix — `git diff` on `derive.py` touches only the docstring and the size
path — yet `b3525b4` is titled "stop advertising level1 while upscaling." The
commit title claims a change that was not made. Refusing upscaling is correct
(level 1 does not require it); the false advertisement is the defect. Fix:
advertise `level0` + `extraFeatures`, or implement `w,h` and `square`.

### R2-S8 — the derivative cache is unbounded, and the docstring uses that bound to justify having no eviction

`derive.py:20-30`, `:54-59`, `:70-79`, `:104`. Both reviewers; A confirmed by
execution.

`_check_dim` is applied to parsed *size* values only. Two gaps:

- `region` is never bounded **and is part of the cache key**. 40 requests for
  `0,0,{100..139},…` against a 100×50 master produced **40 distinct cache
  JPEGs**, all clamping to identical pixels. `region=0,0,999999999,999999999`
  is accepted.
- `size=max`/`full` skips the bound entirely, so the stated worst case
  ("4000x4000x3 bytes ~= 48MB") is false: `full/max` decodes the master at
  native resolution.

`derive.py:26-30` claims "every cached derivative is now bounded in both
count-of-possible-sizes … so no separate cache-eviction scheme is added."
Both halves are false. Both image routes are token-free GETs (`web.py:681`,
`:696`) and `new_session_id` (`sessions.py:52`) has 16 bits of randomness plus
a near-known timestamp, so an untrusted local page can drive this with
`<img src>`.

### R2-S9 — a batch with both failed pages and a failed rollup reports that the pages graded normally

`pages.py:500-524`, with `runner.py:123-126`. Reviewer A.

`elif summary_error:` precedes the failure-rate branch. A batch with 5 of 10
pages failing *and* a failed rollup renders "**The pages graded normally**,
but the batch summary could not be produced. The per-page scores below are
still valid" and suppresses "Too many pages failed" entirely. `run_batch`
returns 1 for `summary_error` before evaluating `failure_rate`, so the two
conditions genuinely co-occur. On a tool whose numbers drive purchasing
decisions this is a wrong verdict, not a cosmetic one.

### R2-S10 — every transcription-side error renders under the grading form's heading with a dead-end link

`pages.py:744-752`. Reviewer A, rendered output confirmed.

`error_page` hardcodes `<h1>Can't grade this batch</h1>` and `<a href="/">Back
to the form</a>`. It is now the error surface for `transcribe_confirm`,
`editor`, `editor_action`, `clone_session`, `export` and `grade_preview`:

```
<h1>Can't grade this batch</h1>...<p>The correction arm shows a machine draft
to correct, so it needs its own folder of hOCR or .txt drafts</p>...
<a href="/">Back to the form</a>
```

The R1-S6 message says "Go back, choose the draft folder" and the only link
goes to the *grading* form, not the session. Contract 9, in the commit titled
"honest errors."

### R2-S11 — the picker test asserts the opposite of correct browser behaviour, and is vacuous

`tests/test_picker_script.py:155-159`, harness `:74-79`. Reviewer B, confirmed
by execution.

`_picker_field` renders the button with the `hidden` attribute
(`pages.py:784`), so in browser mode (no `__TAURI__`) the correct state is
`btn.hidden === true` — it must stay hidden. The node harness's `makeEl`
initialises every element with `hidden: false`, and in the `no-tauri` scenario
the script returns at `pages.py:799` without touching anything, so `assert
result["btnHidden"] is False` reads the stub's default.

Changing the stub to `hidden: id.endsWith('-picker-btn')` — matching the
rendered HTML — makes exactly this assertion fail; the other seven tests still
pass. The test would also pass with the entire picker script deleted.
Contract 10, in the commit titled "verify the picker script by running it, not
by grepping it."

### R2-S12 — `desktop/ui/index.html:97` probes `__TAURI__` at IIFE top level

Reviewer A. Pre-existing, not in this diff.

`var tauri = window.__TAURI__;` inside a `(function(){…})()` that runs at parse
time — the exact tauri#12990 race that `pages.py:793-799` documents as a rule
and that `tests/test_picker_script.py` now enforces for sidecar-served pages.
If the init script loses the race, `bootstrap-status` is never subscribed and
the bootstrap window shows no progress for the entire cold-start install.

The rule was established for one surface and not applied to the other.

### R2-S13 — two QA-record claims are stale in the present tense

`docs/qa/2026-07-25-transcription-editor-smoke.md`. Reviewer A found the
first, Reviewer B the second.

- The non-bug-behaviour note still says a v3 `Choice` body "is unhandled, so
  `image_url` becomes `""` while the canvas still counts, and the guard
  passes … the guard is incomplete." `3efce64` predates `2d75b05`; at HEAD
  `_resolve_v3_body` handles `Choice` and arrays, and the empty-`id` case *is*
  caught by `canvas_count` (passing test at `tests/test_iiif.py:260`). A
  present-tense claim now points a reader at a closed hole — while the real
  open hole is R2-S2.
- Lines 157-159 say "`web.py:526–530` reads whichever arrives" for
  folder-vs-uploads. `web.py:574-586` now rejects that request with a 400.

Reviewer B noted, correctly, that the pre-fix descriptions in
`2026-07-25-par-review-pr1.md` are **not** errors — that document is a dated
snapshot of `df35043`, so describing the unfixed code is right for what it is.

## Minor

Reported, not individually expanded: `session_lock` leaves an orphan lock file
if `os.write` fails (`sessions.py:134-136`) and creates a phantom session
directory for a nonexistent sid (`:108`); `/grade-paths` 500s on a malformed
body instead of 400 (`web.py:364`); `_safe_url` admits `http://`
(`pages.py:762`), so a manifest-supplied `image_service` can load page images
over plaintext; `fetch_manifest`'s redirect guard checks scheme only
(`iiif.py:46-51`), so an https redirect to a link-local host is followed, while
the docstring frames this as the SSRF fix; the token gate runs after the body
is parsed, so an unauthenticated cross-origin multipart POST is fully spooled
before rejection, and `POST /transcribe/sessions` returns 422 rather than 403;
`run_step` never consults `shutdown_requested()` before spawning
(`lifecycle.rs:532-538`); editor `no_text`/`flag` forms are siblings of the
transcription form (`pages.py:1083-1102`), so submitting either discards
unsaved textarea text plus accumulated `elapsed`/`active`.

Three round-1 tests are weaker than they read, all verified by deleting the
code they cover and watching them stay green: `test_derive_rejects_oversized_width`
(`tests/test_derive.py:86-89`) passes on the upscale refusal, not the
dimension bound; `_report_file`'s containment re-check (`web.py:300`) can be
deleted with all 263 tests still passing, because the regex and the
resolve-check each independently catch every case exercised — the symlinked
report the check exists for has no coverage; and `tests/test_derive.py:229`'s
`.tmp` assertion is vacuous because `parse_params` raises before the cache
directory is created.

## Verified sound by both reviewers

Token coverage of all nine mutating routes (each enumerated from source, not
from a list, and exercised — all 403 on a wrong token); `_report_file`'s
rejection of every reachable traversal shape including a symlinked report,
`%2F`, `..%5C`, dot-only and NAME_MAX; the OCR-override plain-filename check
(load-bearing — removing it fails three tests); the `/files` mount removal,
with no surviving consumer in code, templates, tests, Rust or CI;
`session_lock` genuinely serialising all nine `save_session` mutators;
`configure_child`'s `setsid` + `pthread_sigmask(SIG_SETMASK)` pre-exec pair
and its async-signal-safety; `run_step`/`spawn_sidecar` create-job-before-spawn
ordering; `drain_lines`; `runner.py`'s partial-success contract and forced
exit 1; the `iiif.py` redirect handler and body cap; and the `remote.json`
capability identifier.

Reviewer A additionally checked the new `derive`, `iiif` size/redirect,
`runner` timeout, `confirm_session`, `stage_ocr` collision, `hocr_to_text` and
non-ASCII-token tests against pre-fix source and confirmed each genuinely
fails without its fix.

## Note on the brief

Both reviewers flagged that `.github/workflows/desktop.yml` was listed as in
scope but is absent from `22cd687^..HEAD` — it changed in `11c4548`. My error
in the brief, not a finding.
