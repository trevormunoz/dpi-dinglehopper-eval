# Transcription editor — design spec

Date: 2026-07-24 · Branch: `feat/dpi-eval-desktop` · Status: revised after PAR round 1 (3 critical / 9 serious findings incorporated), pending PAR round 2 and Trevor's review

## Why this exists

Decision (Trevor, 2026-07-24): students do not transcribe or get timed in external apps — data quality and outcomes both suffer. The editor is therefore **pilot infrastructure**, not a feature bet the pilot validates. It is the instrument the two-arm rekeying pilot runs on, and it kills the largest known source of phantom error (line-break handling alone doubled measured CER on one test article) by enforcing transcription conventions mechanically at save time.

Context documents: `docs/superpowers/2026-07-24-layers-scope-audit.md` (scope decision and object model), `docs/superpowers/2026-07-19-iiif-brainstorm-parked.md` (settled: canvas-centric provenance, image as optional enrichment), `docs/superpowers/2026-07-19-deep-usability-seed.md` (pilot evidence to collect: per-page rekey cost; no telemetry without a deliberate decision), revision punch list items #5 (two-arm pilot), #12 (conventions before first page), #13 (blank-page filtering).

## What it is

A student-facing transcription flow added to the existing dpi-eval web/desktop app. **Session model: source-as-queue with selection at create** — picking a source (a local folder of page images, desktop only; or a IIIF manifest URL, desktop or browser) lists the source's pages with checkboxes and a select-all; the session's queue is the selected subset. This is the sample-presentation mechanism: which pages to select stays protocol, presenting them is the app's job. The student steps page by page (image beside a plain-text editor), saves transcriptions normalized server-side, marks blank pages, and finishes with a one-click grade through the existing engine.

## Decisions settled during the brainstorm and PAR round 1

1. **Approach A** — new routes in the existing FastAPI app (`web.py`/`pages.py` idiom), not a separate tool, not a client-heavy JS app.
2. **Editor surface is a plain `<textarea>`.** Tiptap was considered and rejected: it is a rich-text document model (ProseMirror block nodes) whose plain text is a serialization, while our artifact *is* plain text byte-for-byte; its no-build path is CDN ES modules, which the self-contained-pages rule forbids. There is no "more Tauri-native" option — Tauri's UI is the WKWebView, and all WKWebView failures to date were chrome-level (handled natively), never rendering. Upgrade path if the pilot shows need for visual affordances: CodeMirror 6 vendored into the wheelhouse. Tiptap does not become the right fit.
3. **macOS text-substitution defenses are mandatory**: the editor field ships with `spellcheck="false"`, `autocorrect="off"`, `autocapitalize="off"`, and smart-quote/dash substitution disabled. System autocorrect silently rewriting a faithful transcription (straight → curly quote) is a conventions killer.
4. **Conventions are enforced server-side in Python** (`conventions.py`), versioned, applied at save. Deterministic, testable, shared with the CLI.
5. **The app records, the protocol assigns.** A session is created in one mode (`from_scratch` or `correction`) and stamps that arm on every transcription. Crossover design — who runs which mode over which pages — lives in the pilot protocol document, not in randomization code.
6. **Correction-mode drafts: hOCR or plain text only in v1.** Drafts are paired to pages and normalized via the existing `adapter.py` (hOCR → text) or passed through (`.txt`). ALTO/PAGE XML draft folders are **rejected at session creation** with a clear message: `adapter.py` deliberately passes XML through for dinglehopper to auto-detect downstream, and the editor has no dinglehopper downstream — prefilling raw XML into a textarea is worse than refusing. Which engine produced the drafts is a pilot-protocol decision; punch-list #5's anchoring/circularity warning is documented there. **Blessed pilot path for IIIF sessions (Trevor, 2026-07-24): [iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr)** — feed the same manifest to both tools; its PaddleOCR hOCR is what `adapter.py` normalizes, and PaddleOCR's independence from vendor engines contains the anchoring risk for vendor batches. Two stated limits: circularity bites precisely when the OCR under evaluation is itself iiif_ocr output (protocol, not software), and iiif_ocr is v2-only, so **v3-manifest sessions have no blessed draft source** until that changes.
7. **Timing records two numbers, disclosed, accumulated.** Per page: `seconds_elapsed` (sum of page-open-to-save stints) and `seconds_active` (input-heartbeat time). Both **accumulate** across visits and re-saves — never replaced. The pilot's headline rekey-cost number is **elapsed** time, because the correction arm's dominant cost is reading the draft against the image, which active-typing time structurally undercounts. Known accepted loss: a stint abandoned before any save posts nothing. Timing is shown on the session summary the student can see — no silent telemetry.
8. **IIIF rendering follows the parked option A**: plain IIIF Image API `<img>` (width-constrained), no OpenSeadragon; provenance is canvas-centric (stem → canvas ID), preserving the rail for future annotation write-back. The enlarged view is an **in-page lightbox overlay** (CSS/JS, self-contained) — never a navigation, which in the chromeless Tauri window would strand the student with no back button (the exact chrome-level WKWebView failure class already hit three times).
9. **Browser scope (Trevor, PAR round 1)**: local-folder sessions are **desktop-only** — browsers cannot supply server-readable paths via `webkitdirectory`. Browser mode fully supports IIIF sessions (remote images render from URLs; the server runs locally in both modes).

## Architecture

Three new modules beside the engine.

| Module | Responsibility |
|---|---|
| `src/dpi_eval/conventions.py` | Pure normalization functions applied at save; exports `CONVENTIONS_VERSION`, stamped into every session. Encodes conventions decisions; does not make them (see Open decisions). |
| `src/dpi_eval/sessions.py` | Session lifecycle: create from source with page selection, save/no-text/flag transitions (which own the GT files — see Data integrity), resume with reconciliation, OCR alignment for grading, export bundle. |
| `src/dpi_eval/iiif.py` | Server-side manifest fetch (https only) and parse, Presentation v2 (`sequences/canvases`) and v3 (`items`), producing per-canvas records (canvas ID, label, image-service and/or static image URL). Drafts on iiif_ocr's `iiif_models.py` (v2 dataclasses) as prior art; iiif_ocr is not a dependency — its PaddleOCR/OpenCV chain is far too heavy for the offline wheelhouse, and it is v2-only. |

**Fence statement, stated precisely**: the transcription layer never imports dinglehopper. It imports `run_batch` (grading), `discover_pairs` conventions implicitly via file layout, and `normalize_ocr_input` from `adapter.py` for draft prefill — that last is a **new, second consumer of the adapter**, which amends the adapter's "deletable when dinglehopper gains hOCR support" contract: deletion would now also require replacing the editor's draft extraction. A comment in `adapter.py` records this.

Routes in `web.py`, rendered by `pages.py`. **Every mutating `/transcribe` route requires the per-launch token in both modes** — desktop injects it as today; browser mode now also generates one at startup and embeds it as a hidden form field, which doubles as the CSRF token. The Host guard alone does not stop cross-site form POSTs, and these routes write pilot ground truth and fetch URLs server-side; unauthenticated they would be a CSRF/SSRF surface.

- `GET /transcribe` — source picker: local folder (desktop native dialog, token-gated path) or IIIF manifest URL; mode selection (from-scratch / correction, the latter adding a draft-folder input, desktop path or rejected-in-browser for v1).
- `POST /transcribe/sessions` *(token)* — fetch/enumerate source, render page-selection list.
- `POST /transcribe/sessions/{id}/confirm` *(token)* — create the session from the selection; validate stems; validate draft folder (format + pairing) in correction mode.
- `GET /transcribe/sessions/{id}` — queue/summary: per-page status, flags, timings, export, Grade now (disabled with an explanatory message when no page is `saved`).
- `GET /transcribe/sessions/{id}/pages/{n}` — the editor. Images: local files served by a session-scoped file route (path-validated against the session record, mirroring the `RUN_ID`-guard pattern); IIIF images loaded client-side from the recorded URL.
- `POST /transcribe/sessions/{id}/pages/{n}` *(token)* — save / no-text / flag transitions.
- `POST /transcribe/sessions/{id}/grade` *(token)* — the grade handoff (below).

## Grading handoff and OCR alignment

The existing pipeline pairs GT to OCR by **stem equality** (`pairing.py`), and no external OCR source will ever name files to match session stems — iiif_ocr writes `{page}.hocr`; vendors use their own conventions. Grading therefore goes through an **alignment step** in `sessions.py`, outside the engine:

1. The user supplies the OCR folder (desktop: native dialog path; browser: multipart upload, mirroring the existing `/grade` / `/grade-paths` dual pattern).
2. `sessions.py` maps OCR files to session pages — **by canvas index** for IIIF sessions (session stems embed the index; iiif_ocr output is index-named), **by stem equality** for local sessions — and materializes a stem-aligned staging folder (copies/links named `<stem>.<ext>`).
3. The staging folder and the session's `gt/` go to `run_batch` exactly as any other pair of folders. The engine is untouched.
4. The session summary displays the alignment table (page → OCR file) before grading runs, so a mispair is visible, and reports unmatched files on both sides.

## Data shapes

A session is a directory: `~/dpi-eval-transcriptions/<id>/` containing `session.json` and `gt/`. GT files are pure normalized text; all metadata lives in `session.json`.

```json
{
  "id": "…", "created": "…",
  "mode": "from_scratch | correction",
  "source": {"type": "local", "path": "…"},
  "conventions_version": "1",
  "draft_source": "path (correction mode only)",
  "pages": [
    {"stem": "p0007-masthead",
     "status": "pending | saved | no_text",
     "flagged": false, "note": "flag note, if any",
     "canvas_id": "https://… (iiif only)",
     "image_url": "https://… (iiif only)",
     "image_service": "https://… or null (iiif only)",
     "label": "…", "source_index": 7,
     "seconds_elapsed": 512, "seconds_active": 312,
     "saved_at": "…"}
  ]
}
```

For `iiif` sources, `source` is `{"type": "iiif", "manifest_url": "…"}`. `image_url`/`image_service` are **persisted at creation** because a canvas ID is an identifier, not a dereferenceable image endpoint — without stored URLs a resumed IIIF session could not re-render after a restart. `flagged` is orthogonal to `status`: a page can be transcribed *and* flagged ("unsure about this ligature"). Stems: local = filename stem; IIIF = `p<index>-<label-slug>` (v3 language-map labels slug from the first value of the first language, missing labels fall back to index only); `source_index` carries the alignment key.

**Not modeled in v1** (in the layers-audit object model as later work): rights fields (the private-repo default covers the pilot) and the `draft → audited → accepted` lifecycle (auditing is TCP-style protocol outside the app).

## Data integrity — the GT folder never lies

Grading reads the filesystem, so the filesystem must agree with the session record at all times:

- **Status transitions own the GT file.** `saved` writes it (temp + rename); `no_text` — including re-marking a previously saved page — **deletes it**; `pending` means no file.
- **Write order is fixed**: GT file first, `session.json` second (also temp + rename).
- **Reconciliation at session load**: `gt/` is compared against `session.json`. A GT file for a non-`saved` page, or a `saved` page with no file (the crash-between-writes cases), surfaces as a "needs attention" state on the queue — never silently graded, never silently dropped.
- Grade-now runs only over pages that are `saved` at grade time.

## Editor page and flow

Image left, editor right. The textarea is monospace with the substitution defenses from decision 3. The image renders width-constrained (IIIF: Image API sized request when the service supports it — level-0 services and serviceless canvases fall back to the static image URL; local: the session-scoped file route); clicking opens the in-page lightbox at larger size. Correction mode pre-fills the textarea with the normalized draft under a banner preserving the whose-error framing: "Machine draft — correct it faithfully; the OCR is what's being graded."

Controls: **Save & next** · **No text on this page** · **Flag for supervisor** (toggle + note, independent of save state). Progress reads "Page 4 of 12." Timing per decision 7. Failures are page-level states: an image that won't load offers retry and flag-and-skip; the student is never stalled.

Session summary: per-page status, flags, timings; **Export for repo**; **Grade now** → alignment table → existing pipeline → existing results page.

## Export for the ground-truth repo

Bare `gt/` would strip the metadata the pilot requires (arm, conventions version, canvas provenance, timings) and — because the crossover design runs the same pages through both arms — two sessions would produce **identical GT filenames** that collide in a shared repo. Export therefore produces a bundle: `<session-id>/` containing `gt/`, and `transcriptions.json` (per page: stem, arm, conventions version, canvas ID, elapsed/active seconds, flags/notes, saved_at). Session-ID namespacing makes cross-arm twins coexist; the sidecar makes them analyzable.

## IIIF handling and failure modes

Manifest fetch is server-side, https-only. Prefer the image service for sized requests where its profile allows; fall back to the static image URL for level-0 services and serviceless canvases. Local-folder enumeration is non-recursive over `{jpg, jpeg, png, tif, tiff}` (case-insensitive). Failure states: manifest unreachable → create-time error naming the URL and reason; image failure mid-session → page-level retry / flag-and-skip. Public manifests only in v1. No image caching; stored URLs plus canvas IDs make images re-resolvable, and re-fetching the manifest is never required for resume.

## Conventions versioning across time

A session is stamped with `CONVENTIONS_VERSION` at creation. If the module's version has changed when a session is resumed, saves are **refused** with a message (finish under the matching app version, or start a new session) — a session must never contain pages normalized under two different rule sets.

## Testing

- `conventions.py`: pure per-rule unit tests, plus a guard test that rule changes force a version bump.
- `iiif.py`: fixture manifests — one real UMD manifest plus a synthetic manifest for the other Presentation version; parser tests for service-vs-static resolution, level-0 profiles, v3 language-map labels.
- `sessions.py`: tmpdir lifecycle tests — create with selection → save → resume → re-mark no_text (asserts GT deletion) → flag independence → crash-simulation reconciliation (orphan GT, missing GT) → OCR alignment by index and by stem, including unmatched-file reporting → export bundle shape.
- Routes: TestClient tests in the existing web-test pattern — token enforcement on every mutating route (desktop and browser modes), correction-mode prefill (hOCR and `.txt`), ALTO/PAGE draft rejection, grade handoff both variants, Grade-now gating with zero saved pages.
- Manual QA: desktop smoke test with one real UMD manifest and one local folder, through alignment table to a graded run; browser smoke test of an IIIF session.

## Out of scope for v1 (refusals, not oversights)

OpenSeadragon/deep zoom · authenticated IIIF · rights fields · transcription audit states · supervisor sample-authoring beyond select-at-create · annotation write-back (rail preserved via canvas IDs) · client-side session state · image caching · browser local-folder sessions · ALTO/PAGE correction drafts.

## Open decisions (tracked, not blocking implementation start)

1. **Conventions content** (punch-list #12): line breaks, Unicode form, end-of-line hyphenation, ligatures, long s. Needs Trevor's sign-off before the first pilot page is typed; the module versions whatever is decided, and v1 ships a minimal proposed set for that review.
2. **Correction-arm seed engine**: which engine/model fills the draft folder per batch — pilot protocol document, with the circularity warning.
3. **HTTP fetch dependency** for `iiif.py`: stdlib `urllib` avoids growing the offline wheelhouse; a nicer client adds a wheel. Implementation-time call; wheelhouse impact must be stated in the PR either way.

## Review record

PAR round 1 (2026-07-24, two independent same-model reviewers): 3 critical (IIIF grade pairing dead-end; stale-GT/source-of-truth integrity; unauthenticated mutation surface) and 9 serious findings, all incorporated above; browser scope, timing metric, and sampling mechanism resolved by Trevor. Round 2 pending.
