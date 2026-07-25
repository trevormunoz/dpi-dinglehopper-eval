# Findings — DPI OCR-Evaluation Sprint

Running log of gaps and observations, each triaged **upstream-PR candidate** vs.
**wrapper work** (per the design spec's success criteria). Verified against
dinglehopper v0.11.0 source, 2026-07-16.

## 1. Heavy dependency tree from a single logging import — upstream-PR candidate

**Observation.** `uv add dinglehopper` installs the full OCR-D core stack — uvicorn,
werkzeug, Flask-adjacent web machinery — into what is conceptually a text-diffing
tool. Harmless in this repo's dedicated venv; a real cost if evaluation ever runs
inside a slim DPI pipeline container.

**Root cause.** `requirements.txt` hard-pins `ocrd >= 3.3.0`, but only
`ocrd_cli.py` (the OCR-D processor wrapper, unused by DPI) genuinely needs it
(`ocrd.Processor`, `ocrd_models.OcrdFileType`). Every other ocrd import in the
codebase is logging only:

- `extracted_text.py:12` — `from ocrd_utils import getLogger`
- `ocr_files.py:8` — `from ocrd_utils import getLogger`
- `cli.py:8`, `cli_extract.py:2`, `cli_line_dirs.py:7`, `cli_summarize.py:7` —
  `from ocrd_utils import initLogging`

The HTML renderer is NOT the weight — jinja2 + MarkupSafe are tiny. Stripping the
renderer (the tempting fork move) would save nothing.

**Proposed upstream PR.** Swap `getLogger`/`initLogging` for stdlib `logging` in
core modules; move `ocrd` to an optional extra (`dinglehopper[ocrd]`) with an
import-guarded processor wrapper. Small, focused, mergeable — upstream merges
external PRs (e.g. #145).

**Fallback if needed before upstream merges (wrapper work, Approach B).** Import
the metrics modules directly (`edit_distance`, `character_error_rate`,
`word_error_rate`). Caveat verified 2026-07-16: all three import `ExtractedText`
from `extracted_text.py`, whose `ocrd_utils.getLogger` import makes the chain
transitively ocrd-dependent — it is NOT ocrd-free as first assumed. Two escape
hatches, either is small:

1. Vendor `extracted_text.py` with a ~3-line stdlib-logging shim replacing
   `getLogger`, or
2. Depend on `ocrd_utils` alone (logging/util package; no web stack) instead of
   full `ocrd`.

**Status.** Not sprint scope — the uv venv absorbs the weight for the demo. Logged
for post-demo triage.

## 2. hOCR input support — upstream-PR candidate (shim as wrapper work meanwhile)

**Context.** [iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr) (M. Aguilar,
UMD) runs PaddleOCR over IIIF manifest canvases and emits one hOCR file per page
(`downloads/<manifest-uuid>/page_{i}.hocr`, stem = zero-based canvas index).
Grading its output with dinglehopper gives DPI real CER/WER numbers for that
pipeline — but dinglehopper reads only ALTO/PAGE/plain text (auto-detected in
`ocr_files.py`), not hOCR.

**Sprint scope (wrapper work).** Input adapter in this repo: sniff hOCR by its
`ocr_page` class markup, extract line text with a ~30-line lxml shim, pass
everything else through untouched. Spec amended 2026-07-16 to include it.

**Proposed upstream PR.** Add hOCR extraction to dinglehopper's format dispatcher
(`ocr_files.py`) alongside ALTO/PAGE detection. Would make our shim deletable and
benefit the OCR-D ecosystem generally.

**Pairing convention.** GT transcriptions for iiif_ocr output follow its stem:
`page_{i}.gt.txt` grades `page_{i}.hocr`.

**Status (implementation, 2026-07-16).** Adapter shipped in `src/dpi_eval/adapter.py`
with hOCR and ALTO end-to-end tests. Two facts pinned empirically during the build:
`dinglehopper-summarize` tolerates a non-report `_normalized/` subdirectory inside
the reports folder (regression test in `tests/test_batch.py`), and dinglehopper
accepts ALTO ns-v3 namespace fixtures without conversion.

## 3. IIIF-viewer side-by-side QC — post-sprint enhancement

**Idea (T. Muñoz, 2026-07-16).** Since inputs are IIIF manifests and hOCR carries
word/line coordinates, convert hOCR to IIIF annotations and overlay OCR text on
page images in Mirador/Universal Viewer for in-place visual QC.

**Why not now (REDUCE).** New moving parts: hOCR→annotation conversion, annotation
hosting, viewer config. Meanwhile ~90% of the QC value already exists stock:
dinglehopper's HTML report is a highlighted text side-by-side, and
`iiif_ocr --visualize` emits page images with OCR bounding boxes drawn on.

**Trigger to build.** Reviewers actually using the demo outputs ask "where on the
page is this error?" more often than the two stock views answer it.

## 4. Stakeholder context — DPI content streams and users

**Source (2026-07-16).** Josh, Kate Dohe, Pamela McClanahan (UMD Libraries).

Two distinct content streams:

- **Vendor-OCR'd repository collections** — Student Newspapers, Advancing
  Workers' Rights, Katherine Anne Porter. Existing OCR from vendors.
- **Hornbake Digitization Center (HDC)** — scan-by-request plus project
  digitization (print media, archival documents, photography, microfilm),
  staffed by student workers. Wants OCR (and eventually alt text) incorporated
  into request/project workflows.

**Implications for this tool:**

- **Demo batch candidates are now named.** The vendor collections are the
  natural first target: existing OCR exercises the passthrough path with zero
  extra work, and grading vendor deliverables against a GT sample is the
  "vendor verification" ground-truth strategy from the design spec — now with
  named stakeholders.
- **Engine-vs-engine comparison needs no new code.** One GT sample + two
  `dpi-eval` runs (vendor OCR dir; iiif_ocr/PaddleOCR output dir) answers
  "would in-house re-OCR beat the vendor OCR?" — directly relevant to the
  "bulk OCR on repository collections" question.

## 5. Web interface for student workers — adoption requirement, post-sprint

**Source.** Kate Dohe: HDC relies on student workers; "a straightforward web
interface for students to use would be preferable to anything that requires
more sophisticated CLI skills or elevated local permissions."

**Reading.** The `dpi-eval` CLI is the engine, not the interface. For HDC
adoption, a thin web wrapper (choose files → run → view reports) is the
natural next project — a separate spec/plan cycle, not an extension of this
one. The CLI's exit codes and JSON outputs are already the right substrate
for it.

**Trigger to build.** An HDC pilot is actually scheduled (take Pamela up on
the workflow tour first).

**Status (2026-07-16).** Built ahead of the pilot as `dpi-eval-web` (spec:
`docs/superpowers/specs/2026-07-16-dpi-eval-web-design.md`) — localhost
FastAPI wrapper over `run_batch`, launched by the same uvx mechanism.

## 6. Alt text generation — separate workstream, log only

**Source.** Pamela McClanahan: eventually incorporate OCR *and alt text
generation* into student digitization workflows.

**Reading.** Generation, not evaluation — adjacent to iiif_ocr's model stack,
not to dinglehopper. Out of scope for this tool; recorded so the roadmap
conversation has a home.

## 7. GT line-wrapping inflates CER ~2x — GT-authoring convention (wrapper), possible upstream flag

**Source (2026-07-17).** First real grade of Library of Congress NDNP output
([ndnp-open-ocr](https://github.com/LibraryOfCongress/ndnp-open-ocr) 1.2.0,
Tesseract 5.4.1): one article ("More Troops for Gen. Shafter", *N.Y. Daily
Tribune*, 1898-06-21, ALTO `block_4`–`block_13`), GT transcribed by hand from the
`0424.jp2` scan, OCR pruned to the same blocks.

**Observation.** dinglehopper's default CER counts every character, **newlines
included**. GT authored as reflowed paragraphs (one `\n` per paragraph, 17 total)
graded against ALTO extracted one `\n` per `TextLine` (75 total) is penalized for
line structure it shares no responsibility for. Both metrics are affected, by
**different mechanisms**. Measured with dinglehopper's own `character_error_rate`
/ `word_error_rate` (538 GT words, 3,157 chars):

| Variant | CER | WER |
|---|---|---|
| Raw — as graded (pipeline) | 0.0402 | 0.0948 |
| Whitespace collapsed to single space, both sides | 0.0210 | 0.0948 |
| **Layout-neutral** (CER: strip all whitespace; WER: token-aware de-wrap) | **0.0199** | **0.0688** |

**~half of both metrics was line-layout, not recognition.** Recognition CER ≈
2.0%, recognition WER ≈ 6.9%.

- **CER mechanism — newline *characters*.** OCR has 75 newlines to GT's 17; each
  counts as an edit. Collapsing/stripping whitespace symmetrically removes it.
- **WER mechanism — word *splitting*.** A word wrapped across a line
  (`an\nnounced`, `addi\ntiongl`) tokenizes as two OCR words vs one GT word,
  costing ~2 word-edits each. **14 of the 51 word-edits were this splitting**
  (8 phantom head-fragment insertions + 6 splits that were otherwise perfect
  words).

**Correction to an earlier note in this section's history:** WER is *not* "immune
to line-wrapping." It is immune only to the newline-vs-space swap (that is why the
whitespace-collapse row leaves WER unchanged — it never rejoins a wrap). Isolating
recognition WER needs a **token-aware de-wrapper**, not whitespace normalization.

**Not hyphenation.** The OCR text contains **no** end-of-line hyphens (they are
dropped), so the driver is newline/token structure alone, never hyphen handling.

**The de-wrapper that works.** Merge two OCR fragments across an original line
boundary iff the merge moves *closer* to a real GT word
(`min-edit-dist(A+B, GT) < min-edit-dist(A,GT)+min-edit-dist(B,GT)`). This joins
`addi`+`tiongl` (neither a GT word → closer merged) while leaving `well`+`as`
(both exact GT words, cannot improve) untouched — the separation a blunt
`\w\n\w` regex cannot make (that regex glued real words and spiked WER to 0.24;
discarded). On this article it made exactly 8 merges, all correct, zero false
merges. It only undoes splits; it never alters characters, so genuine recognition
errors (`tiongl`, `deflnitely`) survive and stay counted.

**Implications.**

- **Headline metric.** Report **recognition WER** (de-wrapped) as the primary
  number; treat raw CER/WER as caveated upper bounds unless GT and OCR share line
  structure. Pairs with the significant-word/proper-noun metric idea (memory:
  `significant-word-accuracy-metric`) — both say the headline number should
  reflect use, not flatter.
- **Wrapper work, not upstream (revised).** The fix lives in this repo (author GT
  to match line structure, or apply the de-wrapper before scoring), not
  necessarily in dinglehopper. A dinglehopper `--normalize-whitespace` flag would
  only address the CER half; the WER half needs the token-aware step.

**Status.** Measurement + throwaway de-wrapper script; no repo code changed yet.
Repro: `gt/` + `ocr/` under the eval workspace, dinglehopper v0.11.0. Single
article — needs a second graded page before the ~2x factor and the de-wrapper's
zero-false-merge behavior are treated as general.

## 8. dpi-eval-web scope fence — deferred features and their triggers

**Source.** REDUCE-posture brainstorm for `dpi-eval-web` (2026-07-16) and
its 2026-07-17 accessibility amendment; spec
`docs/superpowers/specs/2026-07-16-dpi-eval-web-design.md`.

Deferred, each with its trigger to build:

- **GT transcription in the UI** (textarea beside the page image — likely
  the highest-value candidate). Trigger: an HDC pilot shows that
  transcribing in a separate editor is the workflow bottleneck.
- **Progress streaming during long batches.** Trigger: real batches grow
  well past the 10–20 GT-page sampling size and the synchronous
  request feels hung.
- **GitHub Pages instructions site.** Trigger: the form page's inline
  instructions prove insufficient for student onboarding.
- **Auth / multi-user.** Trigger: HDC wants a shared always-on instance
  instead of per-student localhost (would also reopen the hosting and
  files-leave-machine constraints — a new spec, not an amendment).
- **Per-page failure detail in the UI.** The results page says a page
  "failed to grade" but not why; the stderr the runner logs is not kept
  on `BatchResult`. Trigger: students can't self-serve the reason.
  Requires a small engine change (carry stderr per failed stem) — its
  own task, since the web sprint holds engine files untouched.
- **Layout-neutral scores in the UI.** Blocked on findings §7: the
  token-aware de-wrapper must hold up beyond one article before the
  results page shows recognition-only WER/CER beside the raw figures.
- **Error categories and source-scan view** (accessibility notes P2).
  Show error *classes* (proper nouns, numbers) rather than only rates;
  optional page-scan-beside-diff verification view. Trigger: pilot
  feedback that rates alone don't tell students what to fix. The
  per-page table grows columns; nothing in the layout precludes this.
- **Dinglehopper diff color-only audit (upstream-PR candidate).** The
  served diff HTML likely marks insertions/deletions by color alone
  (WCAG 1.4.1). Audit it; if it fails, the fix belongs upstream in
  dinglehopper's report template, not in this wrapper.
- **Pyodide static-hosted grader** (no local install at all). Contingent,
  far future: requires dinglehopper to become ocrd-free AND report
  rendering to decouple from its `cli.py` — see findings #1. Logged so
  the idea has a home; not a roadmap item.

## 9. dinglehopper grades unreadable input as plain text — pilot data-quality caveat, possible upstream flag

**Source (2026-07-17).** Surfaced writing `dpi-eval-web`'s failure-path tests:
no upload payload can deterministically fail a page. dinglehopper 0.11.0 falls
back to plain-text grading for XML it cannot parse (verified: `<not-valid-alto`
as `.xml` grades with exit 0, WER 1.0 / CER 0.897), and lxml's HTML parser
recovery-parses malformed hOCR in our adapter.

**Implication for the HDC pilot.** A corrupt or wrong-format OCR file surfaces
as a *terrible score*, not a failure — students should read a ~100% word error
rate as "check the file," not "the OCR is that bad." The web UI's engine-level
failure list only catches unreadable-at-the-OS-level inputs (see
`tests/test_batch.py`'s directory trick).

**Upstream candidate.** A dinglehopper `--strict-format` flag (error instead of
plain-text fallback on unparseable XML) would let wrappers distinguish "bad
recognition" from "bad file." Small, opt-in, mergeable.

## 10. Beyond CER/WER — measuring reading order and structure — design note

**Source (2026-07-25).** T. Muñoz: reading order and structure are essential to
real text alternatives; dinglehopper measures only CER/WER. What could the system
measure to get at those requirements?

**Observation.** CER and WER compare two strings and report how many characters or
words differ. They say nothing about how the page is organized. Accessibility
requirements are almost entirely about organization — what order to read the text
in, which text is a heading, which is a caption, what language it is in, what a
picture shows. None of the WCAG criteria that cover those things is measured
today:

| Requirement | WCAG | Measured now? |
|---|---|---|
| Text is read in a meaningful order | 1.3.2 (A) | No |
| Headings, lists, tables, captions keep their roles | 1.3.1 (A) | No |
| Images have a text alternative | 1.1.1 (A) | No |
| Language of the page and of parts is declared | 3.1.1 (A), 3.1.2 (AA) | No |
| Headings describe their section | 2.4.6 (AA) | No — heading and body errors weigh the same |

When structure goes wrong the current numbers do move, but not in a way anyone can
interpret. A two-column page read straight across both columns instead of down one
and then the other produces interleaved words and a high WER. The report says
"31% word error rate," not "recognition was fine, the column order was wrong."
Findings §7 is a smaller instance of the same thing: roughly half the error on the
Daily Tribune article was line wrapping rather than misrecognition, and nothing in
the output said so.

**Why the current code cannot measure it (verified in source, 2026-07-25).** Both
paths discard the structural information before scoring. `adapter.hocr_to_text`
walks the hOCR file, keeps the text of elements whose class is `ocr_line`, and
drops the bounding boxes along with every other class — `ocr_carea` (column area),
`ocr_par`, `ocr_title`, `ocr_caption`. dinglehopper does the equivalent when it
reads ALTO: it produces a flat string.

Anything that measures structure therefore has to read the original OCR file,
alongside dinglehopper rather than through it. This is not upstream work.
dinglehopper is a text-comparison tool; layout analysis is a different job.

The `.hocr` test fixture shows the cheapest available signal:

    <meta name="ocr-capabilities" content="ocr_page ocr_line ocrx_word" />

The engine states in the file that it emits pages, lines, and words and nothing
else — no paragraphs, no headings, no captions. hOCR and ALTO/PAGE can all hold
that information; most engines do not fill it in. Reading that one line takes a
few lines of code and says a lot about what a collection can support.

### Tier 1 — record what structure is present in the OCR files. No GT needed.

Open each OCR file and note:

- whether regions are typed (ALTO `TextBlock`, `Illustration`, `ComposedBlock`,
  `@TYPE`; PAGE `TextRegion/@type`; the hOCR classes above)
- whether reading order is stated explicitly (PAGE has a `<ReadingOrder>` element;
  ALTO generally relies on the order elements appear in the file)
- whether a language attribute is present (`@LANG`, `xml:lang`) — without one,
  3.1.1 and 3.1.2 cannot be met at all
- illustration regions with no caption region nearby — each is a picture that will
  need alt text written, so the count is the size of that backlog, which is the
  number finding §6 currently lacks
- whether hyphenation is recorded (`<HYP>`, `SUBS_TYPE`, `SUBS_CONTENT`) — without
  it, reassembling words split across lines later is guesswork
- whether confidence values are present (`WC`, `CC`), which allow flagging bad
  pages without transcribing GT
- using coordinates alone: places where the text order jumps back up the page
  without moving to a new column. Each is a likely reading-order error.

This needs no transcription, so it runs on every page in a collection rather than
the 10–20 sampled. It also answers a different question than CER/WER. Not "how
accurate is this OCR" but "does this file hold enough information to build an
accessible version from?" A vendor ALTO with no region types and no language
attribute cannot produce a conformant tagged PDF regardless of how accurate its
characters are, and the system currently has no way to say so. The vendor
collections named in §4 have files today, so this can run without waiting on
anything.

### Tier 2 — separate reading-order errors from recognition errors. Uses existing plain-text GT.

Match OCR lines to GT lines by content, then compare the two orderings. Two
standard scores apply: the fraction of lines in the correct order relative to each
other (longest increasing subsequence), or Kendall's tau. Then split the total:

    raw WER = recognition WER + line-wrapping cost + reading-order cost

So instead of "WER 9.5%," the report reads "6.9% recognition, 1.4% line wrapping,
0.7% reading order." Those are three different problems with three different fixes
— rescan or retrain, change how GT is transcribed, fix layout analysis. Builds on
the §7 de-wrapper rather than starting over.

### Tier 3 — richer ground truth, for per-region scores.

A plain-text file cannot record that something is a heading, so per-region metrics
need a different GT format. Markdown is probably the least painful one for student
transcribers: `#` for a heading, `-` for a list item, `|` for table rows, a blank
line between paragraphs. Save it as `<stem>.gt.md` beside the existing `.gt.txt`.

That supports: whether headings were detected (precision and recall), whether
paragraph breaks landed correctly, whether table structure survived (TEDS is the
usual metric), and WER broken out by region — headline WER reported separately
from body WER. A wrong word in a headline costs more than one in the fourth
paragraph, because headlines are what people search and skim. Related to the
significant-word idea already noted in §7.

### Tier 4 — check the artifact that actually gets published.

Nobody reads the ALTO. They read a PDF, an EPUB, or a page in a viewer. Once one
of those exists, run an existing conformance checker on it rather than writing our
own scoring: veraPDF for PDF/UA, DAISY Ace for EPUB, axe or pa11y for viewer HTML.

### How to report the results

- **Separate file.** Write structure results to `<stem>.structure.json`, beside
  dinglehopper's `<stem>.json`, not merged into it. That keeps the rule the web UI
  already follows: each number has exactly one producer, and the display layer only
  formats.
- **Specific problems with page numbers, not an overall score.** "Pages 4, 7, and
  12 have images with no caption region" is actionable. A single accessibility
  score is not, and it would break the existing rule in the web spec against
  collapsing results into one number.
- **Show the two coverage levels separately.** The Tier 1 check covers every page;
  the GT-based metrics cover only sampled pages. The results page already shows
  denominators for this reason.

**Trigger to build.** Tier 1 when the first vendor collection raises the question
of whether its deliverable is usable for accessibility — no GT is required, so the
§4 collections are ready now. Tiers 2 and 3 wait for the §7 de-wrapper to hold up
beyond one article. Tier 4 waits for a delivery artifact to exist.

**Status.** Design note; no code. The format details above — whether ALTO 4 has a
reading-order element, which elements carry `@LANG` — are taken from the format
specifications and have **not** been checked against real files. Verify against
real vendor ALTO before building on them.
