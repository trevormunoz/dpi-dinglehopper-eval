# Transcription editor — design spec

Date: 2026-07-24 · Branch: `feat/dpi-eval-desktop` · Status: revised after PAR rounds 1 and 2, pending Trevor's review

## Why this exists

Decision (Trevor, 2026-07-24): students do not transcribe or get timed in external apps — data quality and outcomes both suffer. The editor is therefore **pilot infrastructure**, not a feature bet the pilot validates. It is the instrument the two-arm rekeying pilot runs on, and it kills the largest known source of phantom error (line-break handling alone doubled measured CER on one test article) by enforcing transcription conventions mechanically at save time.

Context documents: `docs/superpowers/2026-07-24-layers-scope-audit.md` (scope decision and object model), `docs/superpowers/2026-07-19-iiif-brainstorm-parked.md` (settled: canvas-centric provenance, image as optional enrichment), `docs/superpowers/2026-07-19-deep-usability-seed.md` (pilot evidence to collect: per-page rekey cost; no telemetry without a deliberate decision), revision punch list items #5 (two-arm pilot), #12 (conventions before first page), #13 (blank-page filtering).

## What it is

A student-facing transcription flow added to the existing dpi-eval web/desktop app. **Session model: source-as-queue with selection at create** — picking a source (a local folder of page images, desktop only; or a IIIF manifest URL) lists the source's pages with checkboxes and a select-all; the session's queue is the selected subset. This is the sample-presentation mechanism: which pages to select stays protocol, presenting them is the app's job. The student steps page by page (image beside a plain-text editor), saves transcriptions normalized server-side, marks blank pages, and finishes with a one-click grade through the existing engine.

**Crossover support**: a session summary offers **"New session from this selection (other arm)"** — cloning the source and exact page selection with the opposite mode. The two-arm design runs the same pages through both arms; re-ticking an identical subset by hand is the mechanism most likely to silently break that, so the app provides the clone.

## Decisions settled during the brainstorm and PAR rounds

1. **Approach A** — new routes in the existing FastAPI app (`web.py`/`pages.py` idiom), not a separate tool, not a client-heavy JS app.
2. **Editor surface is a plain `<textarea>`.** Tiptap was considered and rejected: it is a rich-text document model (ProseMirror block nodes) whose plain text is a serialization, while our artifact *is* plain text byte-for-byte; its no-build path is CDN ES modules, which the self-contained-pages rule forbids. There is no "more Tauri-native" option — Tauri's UI is the webview, and all webview failures to date were chrome-level (handled natively), never rendering. Upgrade path if the pilot shows need for visual affordances: CodeMirror 6 vendored into the wheelhouse.
3. **macOS text-substitution defenses are mandatory**: `spellcheck="false"`, `autocorrect="off"`, `autocapitalize="off"`, smart-quote/dash substitution disabled. System autocorrect silently rewriting a faithful transcription is a conventions killer.
4. **Conventions are enforced server-side in Python** (`conventions.py`), versioned, applied at save.
5. **The app records, the protocol assigns.** A session is created in one mode (`from_scratch` or `corrected`) and stamps that arm on every transcription. (Vocabulary matches the layers-audit object model.) Who runs which mode over which pages lives in the pilot protocol document; the clone-session affordance keeps the paired selection exact.
6. **Correction-mode drafts: hOCR or plain text only in v1.** Drafts pair to pages **by the same alignment rules as grading** (below) and are normalized via `adapter.py` (hOCR → text) or passed through (`.txt`). ALTO/PAGE XML draft folders are **rejected at session creation**: detection is by XML root element (`alto`, `PcGts`) with extension as a hint only, so hOCR delivered as `.xml` still passes; the rejection logic lives in `sessions.py`, not the adapter. Rationale: `adapter.py` deliberately passes XML through for dinglehopper to auto-detect downstream, and the editor has no dinglehopper downstream. Which engine produced the drafts is a pilot-protocol decision; punch-list #5's anchoring warning is documented there. **Blessed pilot path for IIIF sessions (Trevor, 2026-07-24): [iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr)** — feed the same manifest to both tools. Verified against its source: it writes `page_{i}.hocr`, **0-based over all canvases**, and is functionally v2-only (its v3 traversal extracts no images), so **v3-manifest sessions have no blessed draft source**, and circularity bites when the OCR under evaluation is itself iiif_ocr output (protocol, not software).
7. **Timing records two numbers, disclosed, accumulated.** Per page: `seconds_elapsed` (page-open-to-save stints) and `seconds_active` (input heartbeat), both accumulating across visits — never replaced. Each posted stint carries a client nonce; a retried POST does not double-count. The pilot's headline rekey-cost number is **elapsed**, because the correction arm's cost is dominated by reading, which active-typing time undercounts. Accepted loss: a stint abandoned before any save posts nothing. Timing appears on the session summary the student can see.
8. **IIIF rendering follows the parked option A**: plain IIIF Image API `<img>` (width-constrained), no OpenSeadragon; provenance is canvas-centric. The enlarged view is an **in-page lightbox overlay** — never a navigation, which in the chromeless Tauri window would strand the student (the chrome-level webview failure class already hit three times). The lightbox serves **full resolution** — the full-res local derivative, or the largest size the image service offers — with native scroll/pinch pan-zoom, since the material is dense newspaper masters and reading small print is the transcriber's job. **Named upgrade path (considered 2026-07-24, deferred): a local IIIF Image API endpoint over session masters + vendored OpenSeadragon**, if the pilot shows the full-res lightbox insufficient; adopt-not-build — evaluate the `iiif` PyPI package (the Pillow-based Image API reference implementation) before writing a server. A tile cutter has no consumer until that viewer exists.
9. **Browser scope (Trevor, PAR round 1; narrowed in round 2)**: local-folder sessions are desktop-only (`webkitdirectory` yields uploads, not paths). Browser mode supports **from-scratch IIIF sessions only** in v1; correction mode is desktop-only (a browser draft-folder upload is mechanically possible — same multipart pattern as grading — but deferred: the pilot runs on desktop). Stated plainly: the two-arm pilot cannot run in browser mode, by design.

## Architecture

| Module | Responsibility |
|---|---|
| `src/dpi_eval/conventions.py` | Pure normalization at save; exports `CONVENTIONS_VERSION`, stamped per session. Encodes conventions decisions; does not make them (Open decisions #1). |
| `src/dpi_eval/sessions.py` | Session lifecycle (draft → active), save/no-text/flag transitions that own the GT files, resume with reconciliation, draft-format detection/rejection, OCR alignment and staging, grade registration, export bundle, clone-with-selection. |
| `src/dpi_eval/iiif.py` | Server-side manifest fetch (https only) and parse, Presentation v2 and v3, producing per-canvas records (canvas ID, label, image-service and/or static image URL). Drafts on iiif_ocr's `iiif_models.py` as prior art; iiif_ocr is not a dependency (PaddleOCR/OpenCV chain far too heavy for the wheelhouse; v2-only). |

**Fence statement**: the transcription layer never imports dinglehopper. It imports `run_batch` (grading) and `normalize_ocr_input` from `adapter.py` (draft prefill) — a **new, second consumer of the adapter**, which will amend the adapter's "deletable when dinglehopper gains hOCR support" comment as part of implementation: deletion would now also require replacing the editor's draft extraction.

**Storage**: sessions live under a `transcriptions/` root sibling to the runs dir, both derived from the app's single `base_dir` (test-injectable exactly as runs are today). Session IDs are server-generated `s-<timestamp>-<random4>`; they appear in URLs and namespace exports.

Routes in `web.py`, rendered by `pages.py`. **Every mutating `/transcribe` route requires the per-launch token in both modes** — desktop injects it as today; browser mode also generates one at startup, embedded as a hidden form field (doubling as CSRF protection). The Host guard alone does not stop cross-site form POSTs; these routes write pilot ground truth and fetch URLs server-side.

- `GET /transcribe` — **existing sessions list** (with per-session status and needs-attention marks — this is the resume entry point; the chromeless desktop window has no address bar, so resume must be reachable by click from the root) above the new-session picker (local folder via desktop native dialog; IIIF manifest URL; mode; draft folder in correction mode).
- `POST /transcribe/sessions` *(token)* — enumerate/fetch the source, **create the session in `draft` state** (persisting the full enumeration), render the page-selection list.
- `POST /transcribe/sessions/{id}/confirm` *(token)* — prune to the selection, validate stems and (correction mode) draft format + pairing, set state `active`. Draft-state sessions older than a cleanup horizon are offered for deletion on the sessions list; reconciliation skips them.
- `GET /transcribe/sessions/{id}` — queue/summary: per-page status, flags, timings, clone-other-arm, export, Grade.
- `GET /transcribe/sessions/{id}/pages/{n}` — the editor.
- `GET /transcribe/sessions/{id}/images/{n}/{region}/{size}/0/default.jpg` — **parametric local-image serving, Image API-shaped** (see Image derivation below), path-validated against the session record (`RUN_ID`-guard pattern); IIIF images load client-side from recorded remote-service URLs, which already speak the same semantics.
- `POST /transcribe/sessions/{id}/pages/{n}` *(token)* — save / no-text / flag transitions.
- `POST /transcribe/sessions/{id}/grade/preview` *(token)* — receive the OCR folder (desktop: path; browser: multipart upload, stashed under the session's `staging/`), compute and display the alignment table. Nothing is graded.
- `POST /transcribe/sessions/{id}/grade/confirm` *(token)* — run the grade from staged inputs; `staging/` is cleared on confirm or cancel.

## Grading: alignment, staging, registration

The engine pairs by stem equality (`pairing.py`) and consults no session record, so grading never touches `gt/` directly:

1. **GT staging**: grade-confirm materializes a staged GT folder containing **only pages whose status is `saved`** at that moment. Crash-orphaned GT files (present on disk, page not `saved`) are therefore structurally excluded from grading — the needs-attention state (below) governs them; a `saved` page missing its file blocks grading with a needs-attention message rather than silently vanishing from the report.
2. **OCR alignment**: OCR files map to pages — IIIF sessions by canvas index, local sessions by stem equality — into a stem-aligned staging folder. **The index convention is pinned: `source_index` is 0-based over all canvases of the manifest, matching iiif_ocr's `page_{i}` exactly; the extraction rule is the trailing integer of the filename stem.** (An off-by-one here would produce a plausible-looking table that mispairs every page — the one failure the preview can't catch on look-alike pages, hence pinning it in the spec and testing it explicitly.) Staged copies are renamed `<stem>.<normalized-ext>`, where recognized OCR extensions map into the set `discover_pairs` accepts (`.hocr`, `.xml`, `.txt`); unrecognized and non-OCR files (e.g. the `page_N.jpeg` images iiif_ocr leaves beside its hOCR) are filtered out before the unmatched-files report, not listed as noise.
3. **Manual re-pairing**: the alignment preview is editable — each page row offers the unmatched OCR files as an override. This is what makes **vendor OCR of IIIF-sourced objects** gradeable (vendor filenames carry no extractable canvas index; auto-alignment will leave them unmatched, and the supervisor pairs them once in the preview). Auto-alignment is a convenience; the preview is the contract.
4. **Registration**: grade-confirm reuses the run-registration tail of `_grade_pipeline` (refactored into a shared helper) so the run lands as `run-NNN/result.json` under the runs dir and the **existing results page serves it unchanged**.

## Data shapes

`~/…/transcriptions/<id>/` contains `session.json`, `gt/`, and transiently `staging/`.

```json
{
  "id": "s-20260724-142212-x7qk", "created": "…",
  "state": "draft | active",
  "mode": "from_scratch | corrected",
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

For `iiif` sources, `source` is `{"type": "iiif", "manifest_url": "…"}`. In `draft` state, `pages` holds the full source enumeration; `confirm` prunes it to the selection. `image_url`/`image_service` are persisted at creation — a canvas ID is an identifier, not a dereferenceable image, and a resumed IIIF session must re-render without re-fetching the manifest. `flagged` is orthogonal to `status`. Stems: local = filename stem; IIIF = `p<index>-<label-slug>` (0-based index, zero-padded to 4; label slugs from the first value of the first language in a v3 language map; a missing label **or a label that slugs to nothing** — e.g. non-Latin labels in the Japanese-books material — falls back to the index-only stem). GT files are named `<stem>.gt.txt`, the pairing convention grading depends on.

**Not modeled in v1**: rights fields; the `draft → audited → accepted` transcription lifecycle (protocol outside the app).

## Data integrity — the GT folder never lies

- **Status transitions own the GT file**: `saved` writes it (temp + rename); `no_text` — including re-marking a saved page — deletes it; `pending` means no file.
- **Write order fixed**: GT file first, `session.json` second (temp + rename).
- **Reconciliation at session load**: mismatches (GT file for a non-`saved` page; `saved` page without a file) become a **needs-attention** state on the queue. Resolution is explicit: opening a needs-attention page shows the orphan text (or the absence) and the student **saves (adopts) or discards** it; no other action clears the state.
- **Grading and export read only staged, status-filtered copies** — never raw `gt/` (see Grading; Export). Grade is blocked while any needs-attention state exists.
- **Conventions-version guard covers all mutating actions** (save, no-text, flag, grade, export): a session resumed under a different `CONVENTIONS_VERSION` is read-only with a message. (Desktop app updates rebuild the venv, so "finish under the matching version" usually means: export what exists, start a new session.)
- Multi-tab editing of one page (browser mode) is last-write-wins and out of scope to prevent; the pilot is single-student-per-session by protocol.

## Editor page and flow

Image left, editor right; textarea per decisions 2–3. Images render width-constrained (IIIF: Image API sized request where the service profile allows; level-0 and serviceless canvases use the static URL; local: the session-scoped image route); click opens the lightbox. Correction mode pre-fills the normalized draft under the banner "Machine draft — correct it faithfully; the OCR is what's being graded." Controls: **Save & next** · **No text on this page** · **Flag for supervisor** (toggle + note). Progress displays 1-based ("Page 4 of 12") over the 0-based `source_index` — display and alignment key are distinct by design. Image failures are page-level: retry / flag-and-skip; the student is never stalled.

Session summary: per-page status, flags, timings; **New session from this selection (other arm)**; **Export for repo**; **Grade** (disabled, with the reason shown, when no page is `saved` or any page needs attention).

## Export for the ground-truth repo

Export produces `<session-id>/` containing a **staged `gt/` filtered to `saved` pages** and `transcriptions.json` covering **every selected page**: stem, `status` (so a deliberate blank is distinguishable from a page never finished — blank-rate is sample-design evidence), arm, conventions version, canvas ID, elapsed/active seconds, flags/notes, saved_at. Session-ID namespacing lets cross-arm twins of the same pages coexist in the shared repo; the sidecar makes them analyzable.

## IIIF handling and failure modes

Manifest fetch server-side, https-only; create-time failure names the URL and reason. Prefer the image service where its profile allows sized requests. Local-folder enumeration is non-recursive over `{jpg, jpeg, png, tif, tiff, jp2}` (case-insensitive). Public manifests only. No remote-image caching; stored URLs make resume self-sufficient.

**Image derivation (decided — Trevor, 2026-07-24: JP2s are in the collection; the capability that matters is producing JPEGs of specific size and region from whatever master)**: local masters are served through a **parametric derivation endpoint shaped like the IIIF Image API** — `…/images/{n}/{region}/{size}/0/default.jpg`, with region `full` or `x,y,w,h` and size `max`, `w,`, or `!w,h` — backed by **Pillow** (official wheels bundle OpenJPEG, so JP2 decoding ships in one wheel; TIFF likewise — one stated wheelhouse addition) over `jpg/jpeg/png/tif/tiff/jp2` masters, with a `derivatives/` cache inside the session directory keyed by (page, region, size). v1's own consumers use two calls (editor: `full/!1200,/`; lightbox: `full/max/`), but the parametric form is deliberate: region requests are the rail for the roadmap's evidence crops (diffs-at-scale and significant-word review can show the exact crop where an error sits — hOCR carries coordinates), and both image paths — local endpoint and remote IIIF services — now speak the same semantics. Honesty note: this is Image API-*shaped*, not Image API-*compliant* — no `info.json`, rotation, or quality variants in v1, because no external viewer consumes it; `info.json` arrives with the OpenSeadragon upgrade path if the pilot ever hires it. Adopt-vs-subset is an implementation call: the `iiif` PyPI package's URL-parsing/PIL-manipulation components vs a hand-rolled ~80-line subset (the package drags Flask/ConfigArgParse into the wheelhouse; the subset drags nothing) — decided in the PR alongside open decision #3 as one wheelhouse statement. **Engine choice is Pillow in Python, not Rust-side code (considered 2026-07-24)**: the shell is deliberately two files of lifecycle/dialog plumbing with all application logic in the Python sidecar — shell-side derivation would duplicate session/token validation in Rust, split serving across processes, and escape the Python test suite — and Rust has no native JP2 decoder anyway (the `image` crate lacks JPEG 2000; Rust JP2 means binding the same C OpenJPEG that Pillow's wheels already bundle prebuilt). Decode latency is unmeasured; the endpoint logs per-derivation timing, so the pilot measures it for free, and the ladder if first-view decode measurably exceeds tolerance is **pyvips/libvips** (the engine production IIIF servers use) behind the same endpoint — another wheel, not shell code. The webview stays a renderer: no codec workarounds client-side.

## Testing

- `conventions.py`: per-rule unit tests; version-bump guard.
- `iiif.py`: fixture manifests (one real UMD, one synthetic for the other version); service-vs-static and level-0 resolution; v3 language-map and empty-slug labels.
- `sessions.py`: draft→confirm lifecycle (including abandoned drafts); save/no-text GT deletion; flag orthogonality; crash-simulation reconciliation both directions and its resolution flow; **alignment: 0-based index extraction against literal `page_0.hocr`…`page_11.hocr` fixtures (regression-pins the off-by-one), extension normalization, non-OCR file filtering, manual override**; staged-GT filtering (orphan excluded, missing-file blocks); clone-other-arm selection identity; export bundle including `no_text` rows; stint-nonce idempotency.
- Routes: token enforcement on every mutating route in both modes; correction prefill (hOCR and `.txt`), ALTO/PAGE rejection incl. hOCR-as-`.xml` acceptance; grade preview→confirm (path and upload variants) and staging cleanup; run registration lands `result.json` the results page can serve; Grade gating (zero saved; needs-attention).
- Image serving: conversion tests with small TIFF and JP2 fixtures (derivative created once, cached, served as JPEG; web-safe formats served untouched).
- Manual QA: desktop smoke — real UMD manifest and local folder (including at least one JP2 master) through preview, override one pairing, grade, export; browser smoke — from-scratch IIIF session.

## Out of scope for v1 (refusals, not oversights)

OpenSeadragon/deep zoom · authenticated IIIF · rights fields · transcription audit states · supervisor sample-authoring beyond select-at-create and clone-other-arm · annotation write-back (rail preserved via canvas IDs) · client-side session state · image caching · browser local-folder sessions · browser correction sessions · ALTO/PAGE correction drafts · multi-user concurrency control.

## Open decisions (tracked, not blocking implementation start)

1. **Conventions content** (punch-list #12): line breaks, Unicode form, end-of-line hyphenation, ligatures, long s. Needs Trevor's sign-off before the first pilot page is typed; v1 ships a minimal proposed set for that review.
2. **Correction-arm seed engine** per batch — pilot protocol document, with the circularity warning.
3. **HTTP fetch dependency** for `iiif.py`: stdlib `urllib` vs a wheel. Wheelhouse impact stated in the PR either way, alongside the Pillow addition (image conversion, decided above).

## Review record

PAR round 1 (2026-07-24, two independent same-model reviewers): 3 critical / 9 serious — all incorporated; browser scope, timing metric, and sampling mechanism resolved by Trevor. PAR round 2 (fresh pair, same protocol): 1 critical (orphan-GT grading/export leak → staged, status-filtered grading and export) and 9 serious after dedup (vendor-OCR alignment → editable preview with manual override; 0-based index pinned with extraction rule; two-phase create → explicit `draft` state; preview/confirm grade routes with staging lifecycle; sessions list as resume entry point; export gains `status`; browser-scope contradiction resolved by narrowing decision 9; ALTO/PAGE detection assigned to `sessions.py` by root-element sniff; TIFF/Windows → open decision #4; clone-other-arm added for the crossover) — all incorporated, plus minors (run registration via shared helper, stint nonces, conventions guard over all mutations, empty-slug labels, storage root from `base_dir`, arm vocabulary aligned to the audit).
