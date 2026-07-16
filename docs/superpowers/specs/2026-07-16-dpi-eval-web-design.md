# dpi-eval-web — Design

**Date:** 2026-07-16
**Status:** Approved (brainstorming session)
**Scope posture:** REDUCE — minimum that lets an HDC student worker grade a
batch and view reports without a terminal
**Charter:** docs/findings.md #5 (Kate Dohe, UMD Libraries): HDC runs on
student workers who need "a straightforward web interface... rather than
anything that requires more sophisticated CLI skills or elevated local
permissions."
**Decision:** Localhost web UI served by a new `dpi-eval-web` console script
in this same package, launched via the same uvx mechanism as the CLI. Built
on FastAPI. Files never leave the student's machine; no hosting, no IT
involvement, no elevated permissions.

## Goal

A student runs one pinned command:

    uvx --from git+https://github.com/trevormunoz/dpi-dinglehopper-eval dpi-eval-web

A browser tab opens. The student picks a ground-truth folder and an OCR
folder through native folder dialogs, clicks Run, and reads the batch
summary and per-page diff reports. A zip download preserves the results
after the server stops.

## Platform decision (pressure-tested)

Rejected alternatives, each fatal on its own terms:

- **GitHub Pages / Val Town** — static-only and Deno/TS respectively; the
  engine is Python and shells out to dinglehopper's console scripts.
  Hosted options also violate the constraint that unpublished scans never
  leave the student's machine.
- **Pyodide in the browser** — triple-blocked. WASM has no subprocess, so
  the console-script path (`runner.py`) cannot run. The import path
  violates the hard constraint against importing `dinglehopper.*`, and its
  metrics chain is transitively ocrd-dependent anyway (findings #1) — a
  tree Pyodide cannot install. Report rendering is coupled into
  dinglehopper's `cli.py`, so even an ocrd-free future yields no reports
  without the console scripts. Logged as a contingent far-future idea only.
- **Gradio / NiceGUI** — framework widgets add a heavy dependency tree and
  telemetry questions while fighting the design's core move: serving
  dinglehopper's existing self-contained HTML reports as-is.

Chosen: a thin hand-built server. uvx installs every script in
`[project.scripts]` together, so `dpi-eval-web` rides the CLI's existing
distribution and trust story.

## Stack

FastAPI + uvicorn + python-multipart, declared in `pyproject.toml`.

- Folder intake arrives as multipart form data. The stdlib lost `cgi` in
  Python 3.13, so parsing multipart by hand is the worst place to spend the
  line budget. A path-typing form would keep the stdlib viable but demands
  exactly the CLI-shaped skill the charter rules out.
- Do NOT lean on the uvicorn/werkzeug that ocrd drags in transitively
  (findings #1) — that is a phantom dependency on an unmodified
  dependency's internals. Declare what we import.
- FastAPI's `TestClient` keeps web tests in-process under plain pytest.

## Hard constraints (inherited)

- dinglehopper stays an unmodified dependency — never import
  `dinglehopper.*`.
- The web layer builds on `dpi_eval.runner.run_batch` / `BatchResult` and
  imports nothing else from the engine; `runner.py`, `cli.py`,
  `pairing.py`, and `adapter.py` are untouched.
- Existing CLI behavior and all 22 tests stay green.
- Server binds `127.0.0.1` only. No elevated permissions, nothing leaves
  localhost.

## Components

1. **Entry point.** `dpi-eval-web = "dpi_eval.web:main"` in
   `[project.scripts]`. `main()` binds uvicorn to `127.0.0.1` on an
   ephemeral port, opens the browser via `webbrowser.open`, and prints the
   URL as a fallback.
2. **Form page (`GET /`).** One self-contained HTML document — inline CSS,
   no CDN, no external requests (lab machines may be offline). Two folder
   inputs (`webkitdirectory`): ground truth and OCR. One Run button that
   disables itself with a "grading…" state on submit. Inline instructions
   cover the naming convention (`<stem>.gt.txt` grades `<stem>.hocr/.xml/.txt`)
   so the page teaches itself.
3. **Grade endpoint (`POST /grade`).** Receives both file sets as
   multipart. Flattens filenames to basenames — matching the flat-directory
   convention `pairing.py` expects — into a per-run working directory under
   the session tempdir: `run-NNN/gt/`, `run-NNN/ocr/`. Pre-flight: if the
   GT selection contains no `*.gt.txt` files, return a friendly error with
   a naming hint before running anything. Otherwise call
   `run_batch(gt, ocr, reports)` synchronously and redirect to the results
   page. Per-run directories keep earlier runs viewable all session.
4. **Results page (`GET /runs/{id}`).** Rendered from `BatchResult`:
   graded/failed/missing counts; failed and missing stems listed by name so
   the student knows which pages to fix; a prominent link to
   `summary.html`; per-page report links; a "Download reports (.zip)" link.
5. **Report serving.** `StaticFiles` mount per run — dinglehopper's
   self-contained HTML served byte-for-byte as-is. The reports ARE the UI
   for results; this design adds no report rendering of its own.
6. **Zip download (`GET /runs/{id}/download`).** `shutil.make_archive` over
   the run's reports directory + `FileResponse`. Results must outlive the
   tempdir: students hand them to supervisors or attach them to request
   tickets.

## Data flow

Browser folder dialogs → loopback multipart POST → tempdir `gt/` + `ocr/`
→ `run_batch` → per-page reports + `summary.{json,html}` → redirect to
results page → student reads summary and per-page diffs, downloads zip.
Everything lives under one session tempdir the OS reclaims.

## Error handling

Reuse the engine's verdicts; add plain language, not new logic.

- `run_batch` exit code ≠ 0 (nothing to grade, or failure rate above
  threshold) → failure banner on the results page, never a stack trace.
- Empty or `.gt.txt`-free GT upload → immediate friendly error with a
  naming hint.
- `--max-failure-rate` keeps its engine default (0.2); no UI knob.

## Testing

FastAPI `TestClient`, in-process, reusing existing fixtures. Existing suite
untouched.

- Form page renders (200, folder inputs present).
- **Tracer bullet:** one fixture pair POSTs through `/grade` end-to-end;
  redirect lands on a results page; `summary.html` is served.
- Empty and mismatched uploads produce the friendly errors.
- A failing batch produces the banner, not a 500.
- Zip download returns a well-formed archive containing the reports.

## Scope fence (REDUCE)

Out, each logged in `docs/findings.md` with its trigger to build:

- **GT transcription in the UI** (textarea beside the page image). Trigger:
  an HDC pilot shows transcribing in a separate editor is the bottleneck.
- **Progress streaming** during long batches. Synchronous request plus a
  disabled-button state suffices at 10–20 GT pages.
- **GitHub Pages instructions site.** The form page carries its own
  instructions.
- **Auth / multi-user.** Localhost, one student, one machine.

## Deliverables

- `src/dpi_eval/web.py` + entry point + declared dependencies
- Web test suite alongside the existing 22 tests
- README section: the pinned `dpi-eval-web` command and a student-facing
  walkthrough
- Findings entries for the scope-fence items above

## Open questions (resolve during implementation, not before)

- Whether `webkitdirectory` needs a per-browser fallback note in the form
  instructions (verify against the browsers HDC machines actually run).
- Zip layout: flat reports only, or include the run's `gt/`/`ocr/` inputs
  for provenance.
