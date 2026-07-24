# Transcription editor — design spec

Date: 2026-07-24 · Branch: `feat/dpi-eval-desktop` · Status: approved in brainstorm (approach A), pending spec review

## Why this exists

Decision (Trevor, 2026-07-24): students do not transcribe or get timed in external apps — data quality and outcomes both suffer. The editor is therefore **pilot infrastructure**, not a feature bet the pilot validates. It is the instrument the two-arm rekeying pilot runs on, and it kills the largest known source of phantom error (line-break handling alone doubled measured CER on one test article) by enforcing transcription conventions mechanically at save time.

Context documents: `docs/superpowers/2026-07-24-layers-scope-audit.md` (scope decision and object model), `docs/superpowers/2026-07-19-iiif-brainstorm-parked.md` (settled: canvas-centric provenance, image as optional enrichment), `docs/superpowers/2026-07-19-deep-usability-seed.md` (pilot evidence to collect: per-page rekey cost; no telemetry without a deliberate decision), revision punch list items #5 (two-arm pilot), #12 (conventions before first page), #13 (blank-page filtering).

## What it is

A student-facing transcription flow added to the existing dpi-eval web/desktop app. **Session model: source-as-queue** — picking a source creates the session; a local folder of page images becomes a queue of those images; a IIIF manifest URL becomes a queue of its canvases. The student steps page by page (image beside a plain-text editor), saves transcriptions that are normalized server-side, flags blank pages, and finishes with a one-click grade through the existing pipeline.

## Decisions settled during the brainstorm

1. **Approach A** — new routes in the existing FastAPI app (`web.py`/`pages.py` idiom), not a separate tool, not a client-heavy JS app.
2. **Editor surface is a plain `<textarea>`.** Tiptap was considered and rejected: it is a rich-text document model (ProseMirror block nodes) whose plain text is a serialization, while our artifact *is* plain text byte-for-byte; its no-build path is CDN ES modules, which the self-contained-pages rule forbids. There is no "more Tauri-native" option — Tauri's UI is the WKWebView, and all WKWebView failures to date were chrome-level (handled natively), never rendering. Upgrade path if the pilot shows need for visual affordances: CodeMirror 6 vendored into the wheelhouse. Tiptap does not become the right fit.
3. **macOS text-substitution defenses are mandatory**: the editor field ships with `spellcheck="false"`, `autocorrect="off"`, `autocapitalize="off"`, and smart-quote/dash substitution disabled. System autocorrect silently rewriting a faithful transcription (straight → curly quote) is a conventions killer.
4. **Conventions are enforced server-side in Python** (`conventions.py`), versioned, applied at save. Deterministic, testable, shared with the CLI.
5. **The app records, the protocol assigns.** A session is created in one mode (`from_scratch` or `correction`) and stamps that arm on every transcription. Crossover design — who runs which mode over which pages — lives in the pilot protocol document, not in randomization code.
6. **Correction-mode drafts are source-agnostic**: correction mode takes a draft-text folder paired by stem, normalized by the existing `adapter.py` (which already handles hOCR). Which engine produced the drafts is a pilot-protocol decision; punch-list #5's anchoring/circularity warning is documented there, not encoded here.
7. **Timing is disclosed, not silent.** Active-typing time per page is captured and shown on the session summary the student can see, consistent with the project's no-silent-telemetry precedent.
8. **IIIF rendering follows the parked option A**: plain IIIF Image API `<img>` (width-constrained, click-through to 2×), no OpenSeadragon; provenance is canvas-centric (stem → canvas ID), preserving the rail for future annotation write-back.

## Architecture

Three new modules beside the engine; the engine and the fence are untouched.

| Module | Responsibility |
|---|---|
| `src/dpi_eval/conventions.py` | Pure normalization functions applied at save; exports `CONVENTIONS_VERSION`, stamped into every session. Encodes conventions decisions; does not make them (see Open decisions). |
| `src/dpi_eval/sessions.py` | Session lifecycle: create from source, enumerate pages, save/skip/flag transcriptions, resume from disk. |
| `src/dpi_eval/iiif.py` | Server-side manifest fetch and parse, Presentation v2 (`sequences/canvases`) and v3 (`items`), producing per-canvas records (canvas ID, label, image-service or static image URL). |

Routes in `web.py`, rendered by `pages.py`:

- `GET /transcribe` — source picker: local folder (native dialog via the existing token-gated pattern on desktop; `webkitdirectory` in browser) or IIIF manifest URL; mode selection (from-scratch / correction, the latter adding a draft-folder input).
- `POST /transcribe/sessions` — create session: enumerate images or fetch+parse manifest, build the page queue, validate stem uniqueness.
- `GET /transcribe/sessions/{id}` — queue/summary: per-page status, timings, Grade now.
- `GET /transcribe/sessions/{id}/pages/{n}` — the editor.
- `POST /transcribe/sessions/{id}/pages/{n}` — save / no-text / flag.

**Engine fence:** the transcription layer imports nothing from dinglehopper. It writes `.gt.txt` files; one-click grading calls the existing `_grade_pipeline`/`run_batch` with the session's GT folder prefilled and the OCR folder chosen through the existing picker. The desktop shell is unchanged except the landing page gaining a second entry point.

## Data shapes

A session is a directory: `~/dpi-eval-transcriptions/<id>/` containing `session.json` and `gt/`. GT files are **pure normalized text** — all metadata lives in `session.json` — so `gt/` is directly the pairing-convention input and the private ground-truth-repo contribution.

```json
{
  "id": "…", "created": "…",
  "mode": "from_scratch | correction",
  "source": {"type": "local", "path": "…"},
  "conventions_version": "1",
  "draft_source": "path (correction mode only)",
  "pages": [
    {"stem": "p0007-masthead",
     "status": "pending | saved | no_text | flagged",
     "canvas_id": "https://… (iiif only)", "label": "…",
     "note": "flag note, if any",
     "seconds_active": 312, "saved_at": "…"}
  ]
}
```

For `iiif` sources, `source` is `{"type": "iiif", "manifest_url": "…"}`. Stems: local = filename stem; IIIF = deterministic `p<index>-<label-slug>`, collision-checked at session creation (mirroring `_grade_pipeline`'s collision handling), with the full canvas ID recorded. Deliberately **not** modeled in v1: rights fields (the private-repo default covers the pilot) and the `draft → audited → accepted` transcription lifecycle (auditing is TCP-style protocol outside the app for now). Both remain in the layers-audit object model as later work.

## Editor page and flow

Image left, editor right. The textarea is monospace with the substitution defenses from settled decision 3. The image is a width-constrained IIIF Image API sized request (or the local file served by the app), click-through to 2×. Correction mode pre-fills the textarea with the adapter-normalized draft under a banner preserving the whose-error framing: "Machine draft — correct it faithfully; the OCR is what's being graded."

Controls: **Save & next** · **No text on this page** (flags, writes no GT file, excluded from grading) · **Flag for supervisor** (with a note). Progress reads "Page 4 of 12." Timing: small vanilla JS accumulates active-typing time (focus + input heartbeat), posted with each save.

Session summary: per-page status and timings, then **Grade now** → existing pipeline → existing results page.

## IIIF handling and failure modes

Manifest fetch and parse are server-side. Prefer the image service for sized requests; fall back to a static image URL when a canvas has no service. This path is online-only and lab-machine reachability of UMD IIIF servers is unverified, so failures are first-class states: manifest unreachable → create-time error naming the URL and reason; image failure mid-session → page-level error with retry, and the student can flag-and-skip rather than stall. Public manifests only in v1. No image caching — the canvas ID makes every image re-resolvable.

## Error handling

Saves are atomic (temp file + rename). Re-saving a page overwrites its GT file and updates its record; no partial states on disk. Sessions resume from `session.json` as the single source of truth; the landing page lists sessions in progress. Normalization is transparent: the save response reports how many normalizations the conventions module applied ("3 changes applied by conventions v1"), so the system never silently rewrites typing beyond its versioned, inspectable rules.

## Testing

- `conventions.py`: pure per-rule unit tests, plus a guard test that rule changes force a version bump.
- `iiif.py`: fixture manifests — one real UMD manifest plus a synthetic manifest for the other Presentation version; parser tests for service-vs-static image resolution.
- `sessions.py`: tmpdir lifecycle tests — create → save → resume → no-text → flag → stem-collision rejection.
- Routes: TestClient tests in the existing web-test pattern, including correction-mode prefill, the no-text path, and grade handoff prefill.
- Manual QA: desktop smoke test with one real UMD manifest and one local folder, through to a graded run.

## Out of scope for v1 (refusals, not oversights)

OpenSeadragon/deep zoom · authenticated IIIF · rights fields · transcription audit states · supervisor sample-authoring · annotation write-back (rail preserved via canvas IDs) · client-side session state · image caching.

## Open decisions (tracked, not blocking implementation start)

1. **Conventions content** (punch-list #12): line breaks, Unicode form, end-of-line hyphenation, ligatures, long s. Needs Trevor's sign-off before the first pilot page is typed; the module versions whatever is decided, and v1 ships a minimal proposed set for that review.
2. **Correction-arm seed engine**: which engine/model fills the draft folder — pilot protocol document, with the circularity warning.
3. **HTTP fetch dependency** for `iiif.py`: stdlib `urllib` avoids growing the offline wheelhouse; a nicer client adds a wheel. Implementation-time call; wheelhouse impact must be stated in the PR either way.
