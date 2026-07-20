# IIIF integration — parked brainstorm (2026-07-19)

Status: PARKED by Trevor mid-brainstorm ("Record these options for me
to think about") in favor of improving the display/usability of what
dinglehopper already produces. Resume from here; the clarifying
answers below are settled, the approach choice is not.

## Settled by Trevor during the brainstorm

1. **Image availability is mixed** — some collections behind these
   OCR batches have IIIF endpoints, some don't. Any design treats the
   image as optional enrichment; batches without it behave as today.
2. **Both jobs, sequenced** — first sub-project serves student
   adjudication at grading time (image beside diff); the provenance
   model must be **canvas-centric** (stem → IIIF canvas + image
   service), so the later accessibility pipeline (corrected text back
   onto the object as IIIF/W3C annotations) reuses the same mapping.
3. **Provenance authoring is unknown** — depends on HDC batch-prep
   practice nobody has verified. Discovery gate: check how batches
   are actually prepared (same channel as the desktop spec's
   workflow-tour items) before committing to an authoring mechanism.

## The three approaches (recommendation was A)

**A. Provenance-optional enrichment at the wrapper seam
(recommended).** Internal interface `resolve(stem) → canvas record |
None`; first source = staff-droppable sidecar mapping file in the
batch folder; manifest-URL matching addable later as a second source
behind the same interface. On resolution, the wrapped report (the F20
transform surface) gains the page image as a plain IIIF Image API
`<img>` (width-constrained; click-through to a larger size). No
OpenSeadragon until deep zoom has a hirer (would need vendoring —
self-contained-pages rule). Graceful absence everywhere. Survives all
three settled answers.

**B. Manifest-URL-first.** Optional form field; match canvases to
stems by order/label heuristics. Zero batch-prep burden but bets on
naming/ordering practice we declined to assume (answer 3).

**C. Local-images-first.** Show image files sitting alongside
transcription folders; IIIF becomes a later provenance source type.
Covers non-IIIF collections but defers the IIIF leverage that
motivated the idea and widens the picker surface.

## Standing constraints (from the project's own rules)

- Webview stays a renderer: embedding `<img>` over HTTP is fine;
  anything OS-adjacent goes to the shell.
- Self-contained pages: no CDN scripts; a viewer library would have
  to be vendored into the wheel.
- Lab-machine network reachability of UMD IIIF servers is unverified
  — the enhancement is online-only by nature; degrade gracefully.
- Sprint lens (accessibility): the annotation pipeline (settled
  answer 2's second job) is the strategic payoff; rung 1 is the
  stepping stone that builds the provenance rail.
