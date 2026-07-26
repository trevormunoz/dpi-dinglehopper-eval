# PAR review — PR #1 (`feat/dpi-eval-desktop`)

**Date:** 2026-07-25
**Method:** Parallel adversarial review. Two same-model reviewers, identical
inputs, dispatched simultaneously, neither seeing the other. Aggregation rule:
findings reported by both are high-confidence; single-reviewer findings are
kept, not dropped; on severity disagreement the worse rating stands.
**Briefing:** reviewers were given the artifact and the contract only. The
dispatcher's own verdict — including its conclusion about the WKWebView
question — was deliberately withheld to avoid anchoring.
**Target:** commit `df35043` (unreviewed) as primary focus; the QA record and
the whole `main..HEAD` diff also in scope.
**CI at time of review:** `desktop` workflow green (run 30166600931, 18m31s).

Findings are **logged, not fixed**. Nothing here has been actioned.

---

## Critical

### C1 — Path traversal and grade forgery via `override_*` (both reviewers; verified by dispatcher)

`sessions.py:374–384` validates an override filename with
`(ocr_src / ocr_name).exists()` plus an extension check, then
`sessions.py:398–401` copies from that same unnormalised path. `ocr_name`
arrives straight off the form (`web.py:546–548`, `override_*` keys). Both
guards constrain *what* the file is named, never *where* it lives.

Independently reproduced by the dispatcher: with `ocr_src` three levels deep,
`../../../secret.txt` passes `.exists()` **and** the suffix check, and the
file's contents are readable at the exact path the copy uses.

Three consequences, the second and third from Reviewer B:

1. **Arbitrary local file read.** The file's text is copied into
   `staged_ocr/<stem>.txt`, graded, and rendered into the diff report at
   `/runs/<id>` — which is then served with no token via the
   `StaticFiles(directory=base_dir)` mount at `web.py:275`.
2. **Absolute paths also work**, because `pathlib` join with an absolute
   right-hand side discards the left — no `..` needed.
3. **Grades can be forged.** `override_page_0=../../gt/page_0.gt.txt` stages
   the ground truth as its own OCR, manufacturing 0% CER from a form field.

The error message at `sessions.py:378–380` asserts the exact invariant the
code fails to enforce: *"which is not in the staged OCR upload."* Note
`stage_ocr` **does** flatten with `Path(name).name` (`sessions.py:346`); this
path simply doesn't. Existing coverage
(`tests/test_sessions_staging.py:88–93`) tests a *nonexistent* override name,
never a traversing one.

Fix: reject any `ocr_name` where `Path(ocr_name).name != ocr_name`, or resolve
and check containment.

Scoping, stated honestly: exploitation needs a request bearing the launch
token, and the same local user can already point the folder picker anywhere.
So this is a broken guard rather than privilege escalation — but grade forgery
is a research-integrity issue independent of that, and this is the only place
in the codebase where a submitted string becomes a filesystem path with no
containment check.

### C2 — `POST /grade` performs no token check (both reviewers; verified by dispatcher)

`web.py:295–307` is the only mutating route without `_check_token` — compare
`/grade-paths` immediately below at `:311`, and every `/transcribe/*` route.
`multipart/form-data` is CORS-safelisted, so any web page the user visits can
POST to `http://127.0.0.1:8765/grade` with no preflight, and the Host header
passes the DNS-rebinding guard at `web.py:283–289`. Effect: run directories
created under `~/dpi-eval-runs` and the engine driven by a third party.

It also contradicts the code's own stated contract. `web.py:648–651` says
*"Browser mode: mint a per-launch token; forms embed it as a hidden field
(CSRF)"* — but the `action="/grade"` form (`pages.py:211–243`) carries no
token field; the token exists only in a `<meta>` tag for the `/grade-paths`
fetch.

`tests/test_web_token.py:41–46` pins the un-tokened behaviour with
`assert status in (200, 303)` and no token set, so this looks like deliberate
back-compat — but then the comment overstates the protection and the gap is
undocumented.

### C3 — hOCR fallback grades `<title>`/`<style>` text as OCR (Reviewer B)

`adapter.py:40–44`. The XPath matches only `ocr_line`. Engines emitting
`ocrx_line` — kraken, OCRopus, several ABBYY converters — fall through to
`tree.getroot().text_content()`, i.e. the whole document including `<head>`,
collapsed onto one line. Reviewer B's verified output:

    'page_0.tif .ocr_line{color:red} Hello world Second line here\n'

That string is handed straight to dinglehopper (`runner.py:82–83`) and scored
against line-for-line ground truth: silently, wildly wrong CER/WER, no
warning. Zero test coverage.

Worse in the mixed case: a document containing both `ocr_line` and
`ocrx_line` elements takes the normal path (`if not lines` is false) and
**silently drops** every `ocrx_line`, counting them as OCR deletions.

Related: `sniff_format` inspects only the first 4096 bytes
(`adapter.py:19, 23–28`), so an hOCR file with a long head is classified as
plain text and its raw markup is graded as if it were transcription.

This is a correctness bug in the measurement itself — the thing the whole
project exists to produce.

---

## Serious

### S1 — The `tauri#12990` guard test passes against the implementation it forbids (both reviewers)

`tests/test_pages.py:626–637` asserts only that the *first* textual offset of
`addEventListener('load'` is less than the first offset of `__TAURI__`. That
verifies ordering, not nesting. Reviewer B ran the counterexample: a script
whose body is `window.addEventListener('load', …);` followed by a top-level
`if (window.__TAURI__) { … }` — precisely the regression — still yields
`load 10197 < tauri 10269`, test green.

This matters beyond the test: the QA record's claim *"Injection timing
holds … guarded by a test"* rests entirely on it, and injection timing is one
of the three chrome-level failures already paid for on this branch. The guard
on the branch's most expensive known failure class does not guard it.

It also anchors on `page.index("<script>")` — the document's first script,
which is the picker script only by today's coincidence.

### S2 — Dialog-error handler swallows the error and permanently disables the picker (both reviewers)

`pages.py:784–788`. The reject callback binds `err` and never uses it: no
message, no `console.error`. It un-hides the typed field and sets
`btn.hidden = true`.

- The user clicks "Choose OCR folder…", the button vanishes, a text box
  appears, and nothing explains why.
- The pattern it claims to mirror does the opposite: `wirePicker`'s reject arm
  calls `showError('Could not open the folder picker: ' + err)`
  (`pages.py:345–347`) into a live region that takes focus.
- Hiding the button is irreversible in-page, so a transient dialog failure
  costs the picker until reload.

Contract item 5 ("must not strand the user behind a dead button") is met in
the letter only, and the commit message's "a dialog error restores it rather
than stranding the user" describes half of what the code does.

### S3 — `df35043`'s tests do not constrain the behaviours they name (both reviewers)

None of the eight tests executes the generated JavaScript; every assertion is
a substring match on HTML. Beyond S1:

- `tests/test_pages.py:648` asserts `"input.value = selected" in page`. A
  typo'd identifier, a commented-out line, or that statement placed outside
  the `.then` all pass.
- `tests/test_pages.py:600` is named `..._pickers_are_...` (plural) but checks
  only `folder`, not `draft_folder` or `ocr_folder`.
- **Contract item 2's first half** (typed input hidden when the dialog is
  available, `pages.py:771`) has **no test**.
- **Contract item 5** (the error-restore path) has **no test** — the
  behaviour the commit message argues hardest for.
- `..._has_no_iframe` is vacuous; no plausible implementation adds an iframe.

### S4 — `ocr_folder` silently defeats `ocr_files` (both reviewers)

`web.py:519–530` gives `ocr_folder` unconditional precedence; uploads are read
only in the `else`. `df35043` made this less legible, splitting the original
single `<p>` into a picker block plus a separate `<p>or upload files …</p>`
(`pages.py:892–893`), and in desktop mode the path input is hidden while the
file input stays visible. A user who picks a folder *and* attaches files has
the files silently discarded, with the copy still implying an either/or the
server resolves without telling anyone.

### S5 — `stage_ocr` silently overwrites colliding basenames (both reviewers)

`sessions.py:345–349` writes `Path(name).name` with no collision detection.
`_enumerate_dir` (`web.py:113–129`) returns paths *relative* to the picked
folder, so `batch-a/page_0.txt` and `batch-b/page_0.txt` both land as
`page_0.txt`; one silently wins and is graded against `page_0`'s ground
truth. Reviewer B confirmed: 200 preview, no warning.

`_grade_pipeline` rejects this exact shape with a 400 reading *"grading could
silently use the wrong page"* (`web.py:162–169`). The transcription path
bypasses its own project's protection.

### S6 — `clone_session` can never clone *into* the corrected arm (Reviewer B)

`web.py:558–579`. The local branch forwards `source["draft_source"]`, which is
`None` for a `from_scratch` source (`:569`); the IIIF branch passes no draft
folder at all (`:573–575`). Both creators then raise *"Correction mode needs a
draft folder."* (`sessions.py:151–153`, `:174–176`) → 400. Only
`corrected → from_scratch` works, and `test_web_grade_export.py:51` tests only
that direction.

**The two-arm comparison this feature exists for is half-broken**, and the
"New session from this selection (other arm)" button was exercised in neither
the automated suite nor the manual QA.

### S7 — The sidecar inherits a blocked signal mask, so graceful shutdown is impossible (Reviewer B; verified by dispatcher)

`main.rs:35` → `lifecycle.rs:643–649` calls
`pthread_sigmask(SIG_BLOCK, {SIGTERM, SIGINT})` on the main thread. Signal
masks survive `fork`+`execve`, and `pre_exec` (`lifecycle.rs:525–530`) calls
`setsid()` but **never restores the mask** — dispatcher confirmed: line 649
blocks, line 525's `pre_exec` contains only `setsid`.

So `dpi-eval-web`, and every `dinglehopper` it forks, starts with both signals
blocked. `shutdown()`'s `killpg(pgid, SIGTERM)` (`:605`) is ignored, the
3-second `TERM_GRACE` loop always expires, and every quit ends in `SIGKILL`
(`:615`). uvicorn's graceful shutdown never runs and `Ctrl+C` cannot stop the
sidecar.

**This is the mechanism behind QA finding F4**, which the QA record left
unexplained — and it means F4's orphan is reachable through the *instrumented*
shutdown path, not only through ungraceful exits.

### S8 — Bootstrap subprocesses escape the process-tree kill (Reviewer B)

`lifecycle.rs:389–423`. `python -m venv` and up to two `pip install` runs go
through `run_step` → `Command::output()`: no process group, no Windows Job
Object, never registered in `SIDECAR`. Quit during a cold-start `pip install`
— the longest window in the lifecycle — and `shutdown()` finds
`SIDECAR == None` and returns, orphaning a process still writing into
`<app_data>/venv`. The marker is written last (`:425`), so the next launch's
`remove_dir_all` can run while that orphan is still writing — the same
interleaving F4 describes, one phase earlier.

### S9 — A real IIIF v3 `Choice` body produces empty image URLs *and* defeats the index-skew guard (Reviewer B; verified by dispatcher)

`iiif.py:79–94` handles a JSON array body but not
`{"type":"Choice","items":[…]}`, so `body.get("id","")` returns `""` while the
canvas still increments `canvas_count`. The guard at `iiif.py:97–101` — whose
entire purpose is refusing manifests that would skew `page_{i}` numbering —
therefore **passes**, and the session is created with imageless pages.
Nothing validates `image_url`. Dispatcher confirmed: no `Choice` handling
exists in the module.

`test_iiif.py:60–66` is named `test_parse_v3_choice_body_uses_first_choice`
but builds a plain array, so it passes against the broken code.

**This directly qualifies the QA record's "expected non-bug" note** that
image-less canvases are rejected by design: the guard has a hole, and the
0-based alignment it protects is exactly what item 8 (deferred) would have
exercised.

### S10 — Malformed manifests raise 500, not the intended 400 (Reviewer B)

`iiif.py:57–71` iterates `doc.get("sequences"/"items")` and indexes
`images[0]` with no type checks. Verified: `{'items': {'a': 1}}` →
`AttributeError`; `{'sequences':[{'canvases':[{'images':{'a':1}}]}]}` →
`KeyError: 0`. Callers catch only `(SessionError, IIIFError)` (`web.py:431`,
`:577`). The module's stated contract — *"every failure is a create-time
error"* (`iiif.py:33`) — holds for fetch but not parse.

### S11 — `fetch_manifest`: https-only is redirect-bypassable; read is unbounded (Reviewer B)

`iiif.py:27–34`. `urlopen` follows redirects and `HTTPRedirectHandler` permits
`http`, so an `https://` manifest that 302s to
`http://169.254.169.254/…` is followed — the guarantee in the error string is
not enforced on the request that actually returns bytes. That is an SSRF
shape. `resp.read()` has no size cap and no Content-Type check.
`test_iiif.py:42–44` checks the URL prefix only, and the happy path
monkeypatches `urlopen` with a `BytesIO`, so neither behaviour is exercised.

### S12 — `_check_token` raises 500 instead of denying, on a non-ASCII token (Reviewer B)

`web.py:231`: `secrets.compare_digest` raises
`TypeError: comparing strings with non-ASCII characters is not supported` for
non-ASCII `str`. Reachable via a latin-1-decoded header or a UTF-8 form field;
Reviewer B got an unhandled traceback out of `transcribe_create`
(`web.py:421`). **The auth gate faults rather than denying** — it should
return 403.

### S13 — `confirm_session` will activate a session with zero pages (Reviewer B)

`sessions.py:187–197` checks only `if not selected_indices`, never that any
index matches a real page; `web.py:443` passes
`[int(i) for i in pages_selected]` unvalidated. `pages=9999` → 303,
`state: "active"`, `pages: []` — permanently unusable, and `export_session`
emits an empty bundle because `reconcile` finds no problems for zero pages.

### S14 — `run_batch`'s `summarize()` is unguarded, discarding successful work (Reviewer B)

`runner.py:92–93`. Per-page failures are deliberately downgraded (`:85`), but
`summarize()` runs with `check=True` outside any `try`. A malformed per-page
report raises `CalledProcessError` instead of returning
`(BatchResult, int)`, losing the whole run including per-page reports already
written to disk. Neither subprocess call has a `timeout=` (`:18`, `:37`), so a
hung engine pins a threadpool worker indefinitely.

### S15 — `session.json` is read-modify-write with no locking (Reviewer B)

`sessions.py:54–59` writes atomically via `os.replace`, but every mutator
(`:184, :236, :263, :277, :301`) does load → mutate whole dict → save. These
are `def` routes, so FastAPI runs them in a threadpool and two in-flight
requests genuinely interleave — two editor tabs, or a flag submit racing a
save. The loser's record is discarded, **including `seconds_elapsed` and
`seconds_active`**, i.e. the pilot's actual measurement.

### S16 — Unbounded, unauthenticated image derivation (Reviewer B)

`derive.py:50–53, 91–96` accept any `\d+` width/height and upscale;
`web.py:606` has no `_check_token`. `GET …/full/100000,/0/default.jpg` asks
Pillow for roughly a 15 GB RGB buffer, and every distinct size string mints a
permanent file in `session_dir/derivatives` that is never cleaned.

Also a spec break: IIIF Image API 3.0 requires the `^` prefix for upscaling
and `info_json` advertises bare `level1`, while `derive.py:9–11` asserts
*"Declared capability = implemented capability."* Implemented is broader than
declared, in the one direction the docstring promises it isn't — and `!w,h`
correctly refuses to upscale, so it is internally inconsistent too.

### S17 — `wrapped_report`'s name regex rejects names the app itself generates (Reviewer B)

`web.py:368` requires `[A-Za-z0-9_-]+`, but stems come from GT filenames
(`runner.py:80`) and are rendered into links verbatim (`pages.py:436`).
Grading `img.0001.gt.txt` writes `reports/img.0001.html` and links to
`/runs/…/reports/img.0001` → 404 "No such report." Any stem containing a dot,
space, or non-ASCII character — routine in scan filenames, and reachable for
local sessions since `create_local_session` takes stems straight from
`Path.stem` — is a permanently dead "View diff" link.

### S18 — Files the alignment preview discards are never shown (Reviewer B)

`align()` computes an `ignored` list for files with unrecognised extensions
(`alignment.py:28–33, 57`), asserted in `test_alignment.py:37` — but no page
renders it. `alignment_page` shows only `matched` and `unmatched_files`
(`pages.py:918–949`). On a screen headed "Check the alignment before
grading", files silently dropped from the batch are invisible.

### S19 — `/files` serves the entire runs tree with no token (Reviewer B)

`web.py:275` mounts `StaticFiles(directory=base_dir)`, exposing every run's
GT, OCR, and reports to any local process — and it is what makes C1's
exfiltration reachable.

### S20 — `grade_preview` 500s on an unreadable OCR tree (Reviewer A)

`web.py:526` calls `_enumerate_dir(folder)` *outside* the `try` that begins at
`:535`, and only `sess.SessionError` is caught (`:538`). One permission-denied
file anywhere under the picked folder → unhandled `OSError` → 500 with a
traceback instead of a friendly page. `grade_paths` gets this right
(`web.py:326–329`).

### S21 — Desktop lifecycle: four orphan/misreport paths (Reviewer A)

- **Two spawn-path returns orphan a live sidecar with no handle to kill it.**
  `std::process::Child` has no killing `Drop`. `lifecycle.rs:179–183` returns
  before `*SIDECAR.lock() = Some(sidecar)` on `:184`; `lifecycle.rs:546–548`
  (Windows) returns after a successful spawn. A listening, token-bearing
  server survives with nothing recorded.
- **`check_alive()` reports healthy when no sidecar is recorded**
  (`lifecycle.rs:275–283` returns `Ok(())` on `None`). Quit during bootstrap
  and the handshake loop (`:232–240`) polls a dead port for the rest of the
  60 s budget, then raises a modal after exit was requested. It also swallows
  `try_wait()` errors, so a failing `waitpid` reads as alive.
- **Startup failure never cleans up.** `run()` (`:130–144`) reports and
  dialogs but never calls `shutdown()`, so on any post-`:184` failure the user
  is told "dpi-eval could not start" while the sidecar keeps serving loopback
  with the launch token.
- **One non-UTF-8 byte on sidecar stdout aborts startup with a false
  diagnosis.** `lifecycle.rs:197–198`: `lines()` yields `Err(InvalidData)`,
  the `let Ok(line) = line else { break }` ends the reader thread, and the
  sentinel loop reports *"closed stdout before announcing its URL"* about a
  healthy process. The same `break` voids the stated guarantee at `:187–188`
  that draining prevents the pipe filling.

---

## Errors in this session's own work

Reported by the reviewers against artifacts produced during the QA session
and verified by the dispatcher. Recorded here rather than quietly amended.

### E1 — F4's mechanism was asserted, not established (Reviewer A; confirmed)

The QA record states that `remove_dir_all(&venv)` deleted the tree the
running interpreter was executing from, and that the following
`python3 -m venv` was killed as a result. **That is wrong.** Venv creation
does not run from the venv: `lifecycle.rs:385` uses
`bundled_python(resource_dir)`, resolving inside the app bundle
(`lifecycle.rs:320–328`), untouched by the delete.

The two observations — the SIGKILL and the orphan — are real. The causal link
between them was an assumption stated as fact. F3 was correctly marked
"unexplained"; F4 deserved the same. The actual mechanism for the orphan half
is now identified as **S7** (blocked signal mask).

### E2 — F4's reproduction contradicts its own conclusion (Reviewer A)

The record concludes the orphan happens "whenever the app dies *without a
graceful quit*". But the graceful path is fully instrumented —
`main.rs:155–159` calls `shutdown()` on both `ExitRequested` and `Exit`,
`lifecycle.rs:595–621` does `killpg(SIGTERM)` then `SIGKILL`. Per S7 that
`SIGTERM` is ignored, so the orphan is reachable on the instrumented path
too. The conclusion generalises to the one case those paths cannot cover,
understating the defect.

### E3 — The record's stated HEAD predates the code the results came from (Reviewer B)

Header says `@ eaaa5c4`, but items 1–7 were run against the F1 fix, which is
`df35043` — after both `eaaa5c4` and the record's own commit `6df44b8`. The
results cannot be reproduced from the SHA cited.

### E4 — Wrong mechanism: pruning happens at confirm, not create (both reviewers)

The record says "pruning happens at create, as specified".
`create_local_session` records **all** images (`sessions.py:148`);
`confirm_session` filters them (`sessions.py:190`) via a separate route
(`web.py:443`). Outcome right, mechanism wrong.

### E5 — Wrong attribution: the `no_text` page is skipped at render, not before pairing (both reviewers)

The record says `pages.py:922` "skips non-saved pages before pairing".
Pairing runs *first*, in `stage_ocr` → `align(session["pages"], …)`
(`sessions.py:351`), over **all** pages including `no_text`. The cited filter
lives in `alignment_page`, the renderer, and runs after. The dispatcher also
told the tester this during the run, so the correction stands against the
conversation as well as the document.

### E6 — "Injection timing holds … guarded by a test" is unsupported (both reviewers)

See **S1**: that test passes against the very implementation it forbids. The
claim asserts a runtime property on the strength of a source-shape check. The
record draws this distinction correctly elsewhere (for browser mode) and then
drops it here. This claim also appears in the PR body.

### E7 — "OCR bytes never cross the webview boundary" overstates (Reviewer A)

`pages.py:818–820` shipped the path field *and*
`<input type="file" name="ocr_files" multiple>`, and `web.py:526–530` reads
whichever arrives, the upload branch pulling bytes from the multipart body.
The path field *permits* avoiding the boundary; "never" is wrong — and the
claim is load-bearing in the record's WKWebView verdict.

### E8 — Phantom file reference in shipped code, tests, and commit message (both reviewers; confirmed)

`pages.py:739` and `tests/test_pages.py:584` cite
`capabilities/remote-dialog.json`. Confirmed: the directory holds only
`default.json` and `remote.json`; `remote-dialog` is an *identifier* inside
`remote.json`. Repeated in `df35043`'s commit message. The grant itself is
correct and the new code stays inside it, so this misleads readers rather
than breaking behaviour.

### E9 — Screenshot evidence is not in the repository (Reviewer A)

F2 and F5 cite "the item 1 screenshot" and "the item 3/4 screenshot" as their
record. `docs/qa/` contains only markdown; `6df44b8`/`bdfe4e8` added no
images. F5's substance is additionally unreproducible from source — the
controls it says overlap are ordinary sibling block `<form>` elements in
normal flow (`pages.py:926–945`) and `_STYLE` has no absolute/fixed
positioning, negative margins, or floats. F5 does hedge, so treat this as
evidence unavailable rather than the finding disproved.

### E10 — Line-number citations off by one or stale (both reviewers)

`lifecycle.rs:380` cited for `remove_dir_all(&venv)`; it is `:381`. Several
`pages.py` citations were taken from the post-fix working tree while the
document declares `eaaa5c4` (see E3). Reviewer B confirmed the remaining
citations resolve: `alignment.py:39–42`/`:46`, `pages.py:326–349`/`:353–354`/
`:392–404`/`:528–529`/`:710–718`, `conventions.py:18–48`, `sessions.py:123`,
`main.rs:43`, `build_wheelhouse.sh:53`, and the 197 → 205 test count.

---

## Tests that pass against a broken implementation

Reviewer B's audit, beyond S1 and S3. Each was checked by constructing the
break and observing the test stay green.

- `test_web.py:273`, `:342` — httpx normalises dot segments before sending,
  so the requests arrive as `/etc/download` and `/runs/run-001/secret` and
  404 because *no route matches*. The `RUN_ID` regex (`web.py:251`) and the
  report-name regex (`:368`) are never exercised; deleting both leaves these
  green.
- `test_web_token.py:41–46` — the only coverage of `/grade`'s auth posture,
  and it ratifies **C2**.
- `test_grade_paths.py:287–302` — asserts on `pathlib.Path.rglob` directly,
  never touching `_enumerate_dir`; would stay green if `_enumerate_dir` began
  following symlinked directories.
- `test_derive.py:55–58` — asserts only `max(img.size) == 100`; deleting the
  entire region-crop block (`derive.py:84–88`) passes. Nothing asserts crop
  content or the non-square dimension.
- `test_runner.py:27–31, 56–60` — `fake_run` discards kwargs and hardcodes
  `returncode=0`. Removing `check=True` from `runner.py:29` — turning every
  engine crash into a silent success with a nonexistent report path — passes
  both.
- `test_web_transcribe.py:54` — `assert "Page" in summary.text and "a" in
  summary.text`. `"a"` appears in any HTML document.
- `test_conventions.py:15–18` — uses `"a\r\nb\r\n"` only; deleting
  `.replace("\r", "\n")` from `conventions.py:25` passes.
- `test_iiif.py:60–66` — named for a `Choice` body, builds a plain array
  (see **S9**).
- `test_sessions_staging.py:88–93` — tests a nonexistent override name, never
  a traversing one (see **C1**).
- `lifecycle.rs:799` `bootstrap_marker_roundtrip` — writes to a fixed
  `temp_dir()` path; concurrent suite runs collide.

---

## Verified clean

Recorded so it is not re-audited: no shell injection or stdout deadlock in
`runner.py`; no traversal in `derive.derive`'s cache key, `stage_ocr`'s upload
flattening, `_local_master`, or `dedupe_download_path`; `killpg`'s target is
correct (`setsid` makes pid == pgid); extension-case handling survives
end-to-end; `normalize` is idempotent; `confirm_session` preserves original
`source_index` values; `save_session` is atomic; and `df35043`'s generated
JavaScript is syntactically valid in every case either reviewer could
construct (`/[/\\]/` renders correctly; `_picker_script`'s `.replace()` output
is never re-parsed as an f-string).

---

## Minor

Both reviewers flagged `_picker_field`/`_picker_script` (`pages.py:743–799`)
interpolating `field`/`label`/`button` into HTML attributes and a JS string
literal with **no escaping** — latent only, since all call sites pass
literals today, but every other builder in the file escapes.

Further items, condensed: `results_page` prints "Too many pages failed (1 of
100)" for any non-zero exit with partial success (`pages.py:490–496`);
`derive.py:104–106` relabels client errors as 500 with a false message and
leaves `.tmp` files on failed saves; `main.rs:118–127` says "Report saved to
Downloads" even when it wasn't, and says "Report" for the GT bundle;
`alignment.py:29, 39–48` prefers `.txt` over `.xml`, inverting
`pairing.OCR_EXTENSIONS`' documented precedence and silently discarding a
supplied ALTO/PAGE file; `iiif.py:66` `str()`s v2 labels so a spec-legal
`{"@value":…}` becomes a Python `repr` that is shown to students and slugged
into the page stem; `iiif.py:116–121`'s docstring calls the embedded index
"the alignment key" while `align(by="index")` reads the OCR filename's
trailing int, so OCR named by this project's own label-suffixed stems
misattaches by one page; `web.py:554–555`'s `finally: clear_staging(...)` runs
on the error path, so a rejected override destroys the staged alignment and
the retry fails with a misleading message; `web.py:627–636` `_pick_port`
TOCTOU with the sentinel printed before uvicorn binds; `lifecycle.rs:36–39`
claims absent env ⇒ endpoint refused, but `web.py:648–651` mints a token when
unset so `/grade-paths` is fully available in uvx mode and `web.py:228`'s
"403 when unset" branch is unreachable from `main()`;
`lifecycle.rs:275–283` never reaps a sidecar that dies after the handshake;
`lifecycle.rs:484`'s `.expect()` panics on the spawned thread, bypassing
`run()`'s error dialog; `conventions.py:43–46` collapses trailing blank lines
against a docstring whose cornerstone is that newlines are data, and has no
BOM/zero-width handling so a paste from Word writes U+FEFF into the GT and
scores as a character error; `_enumerate_dir`/`_save`/`sessions.py:86` read
whole trees, uploads, and files into RAM; `list_sessions` silently drops a
corrupt session (`sessions.py:72–75`); `_load_result`'s unguarded
`json.loads` 500s (`web.py:256`) where its neighbour guards the same call;
`web.py:390–394` and `sessions.py:441–445` each leave an uncleaned zip;
`rmtree(ignore_errors=True)` followed by `mkdir` without `exist_ok`
(`sessions.py:337/344, 393–394, 418–420`) converts a suppressed failure into
an undiagnosable 500; `aria-describedby` on the new picker buttons points at a
`hidden` div and the chosen path lands in a non-live region so it is never
announced (inherited from `wirePicker`, not introduced by `df35043`); and the
new labels dropped their "(desktop)" qualifier, removing the only hint that
the value is a path on the sidecar's machine.

---

## Aggregation notes

- **No severity disagreements** arose between the reviewers on shared
  findings; both rated C1 and C2 critical and the shared `df35043` findings
  serious.
- **Reviewer overlap was substantial on `df35043`'s weaknesses** — the
  primary focus — and divergent across the branch, which is the intended
  benefit of the paired structure: Reviewer B carried the branch-wide sweep
  (C3, S6–S19), Reviewer A carried the Rust lifecycle in depth (S21) and was
  first to catch E1/E2.
- **Nothing here is actioned.** Neither reviewer modified the repository, and
  no fix has been applied.
