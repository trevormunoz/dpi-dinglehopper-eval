# dpi-eval

dpi-eval grades OCR text against a small hand-typed sample of "what the
page actually says" (the ground truth) and reports how close the OCR
came. The OCR engine is the party being graded — the score measures the
quality of the machine-generated text, not the person who typed the
ground truth. This is the QA step in UMD Libraries' text-alternatives
work: before OCR output is trusted as an accessible text alternative for
a scanned page, dpi-eval tells you how good it actually is.

There are two ways to run it: a desktop app (no terminal, recommended for
student workers) and a command-line tool (for anyone comfortable with
one command).

## Desktop app

### Install (macOS)

1. Go to the project's [Releases page on
   GitHub](https://github.com/trevormunoz/dpi-dinglehopper-eval/releases)
   and download the `.dmg` file from the latest release.
2. Open the `.dmg` and drag **dpi-eval** into your Applications folder
   (your own `~/Applications` is fine if you don't have permission to
   write to the system one).
3. Double-click **dpi-eval** to launch it.

### First-run prompts

The app is not signed by Apple (that costs an annual developer fee UMD
Libraries hasn't paid for a pilot tool), so macOS will try to stop you
from opening it the first time. This is expected — click through it
once and it won't happen again.

**(a) Gatekeeper warning.** The first time you open the app, macOS shows
a dialog saying something like *"Apple could not verify 'dpi-eval' is
free of malware"* or *"is from an unidentified developer."* Don't move
it to the Trash. Instead:

1. Open **System Settings → Privacy & Security**.
2. Scroll down — you'll see a notice about `dpi-eval` being blocked,
   with an **Open Anyway** button. Click it.
3. Confirm in the dialog that appears. The app now opens, and every
   launch after this one is normal — no more warnings.

If you don't see an **Open Anyway** button at all, the machine's
management policy is blocking it outright; stop and tell a supervisor
rather than trying to work around it.

**(b) Notification permission.** The first time you run a grading job,
macOS may ask whether dpi-eval can send notifications. This is
optional — allowing it just means you'll get a system notification when
grading finishes (handy if you switch to another window while it runs).
Denying it changes nothing else about how the app works.

### Folder conventions

dpi-eval compares two folders:

- **`ocr/`** — the OCR output you want to check. Accepted formats: ALTO
  XML, PAGE XML, hOCR, or plain text. One file per page.
- **`gt/`** — your ground-truth sample: plain-text files containing what
  each sampled page actually says, typed by hand. You only need a ground
  truth file for the pages you've chosen to sample (10–20 pages is a
  typical sample) — not every page in the batch needs one.

Each ground-truth file must be named after the OCR file it checks,
with a `.gt.txt` extension in place of the OCR file's own extension.
For example:

    ocr/page_003.xml   ↔   gt/page_003.gt.txt

If the names don't line up exactly, dpi-eval can't pair the files and
will tell you which ones it couldn't match (see Troubleshooting below).

**Only have images, no OCR yet?** dpi-eval grades OCR — it doesn't
create it. For image-only content, Marc Aguilar's
[iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr) generates OCR from
a IIIF manifest; its output folder can then be graded with dpi-eval as
usual.

### Using the app

1. Launch dpi-eval. Click the button to choose your `ocr/` folder, then
   the button to choose your `gt/` folder.
2. Once both folders are chosen, click **Grade this batch**.
3. When grading finishes, you'll land on a results page with a verdict
   at the top — an overall score band (for example "Strong" or "Review
   the diffs") and the batch word error rate.
4. Below the verdict, each page gets its own row of scores, linking to a
   **full technical report** — the same information dinglehopper itself
   would show, including a side-by-side diff of the OCR text against
   your ground truth and, for the batch as a whole, tables of the most
   common OCR mistakes (which characters or words the OCR engine tends
   to get wrong).
5. Click **Download reports (.zip)** to save the complete report set —
   it goes to your **Downloads folder**, same as any other file you
   download in a browser.

## Command-line tool

Colleagues who already have the one-line command from an earlier
circulated doc can keep using it — the desktop app doesn't replace it,
it's just an easier way in for people who don't want a terminal.

Requires [uv](https://docs.astral.sh/uv/) installed. The first run
downloads dpi-eval's dependencies, so it takes a little longer than
later runs.

    uvx --from git+https://github.com/trevormunoz/dpi-dinglehopper-eval dpi-eval gt/ ocr/ reports/

This grades every OCR file in `ocr/` against its match in `gt/` (same
naming convention as above) and writes per-page and batch reports into
`reports/`.

**No desktop app on this machine?** The same interface the desktop app
shows can be opened in an ordinary browser tab:

    uvx --from git+https://github.com/trevormunoz/dpi-dinglehopper-eval dpi-eval-web

This is a useful fallback on machines where the desktop app isn't
installed or validated yet; the desktop app remains the recommended
path.

## Troubleshooting

**The app was force-quit (or crashed) and now grading won't start.**
Force-quitting can leave dpi-eval's background process still holding
the port it needs. Quit the app fully, wait a few seconds, and reopen
it. If that doesn't help, open Activity Monitor, look for a leftover
`dpi-eval-web` (or similar) process, end it, and reopen the app.

**Files won't pair up.** If dpi-eval can't match your OCR files to your
ground-truth files, the error page lists the specific files it couldn't
pair on both sides. Check each one against the naming convention above
— the ground-truth file's name (minus `.gt.txt`) must exactly match the
OCR file's name (minus its extension).

**Grading Japanese or other CJK material.** Word error rate isn't a
meaningful number for text that isn't segmented into space-separated
words (Japanese and some other CJK scripts). For that material, read
the **character error rate** only, and treat the word error rate figure
as not applicable.

## Developer setup (working copy)

    uv sync
    uv run dpi-eval GT_DIR OCR_DIR REPORTS_DIR [--max-failure-rate 0.2]
    uv run dpi-eval-web

`uv run` activates the project's virtual environment for you. If you
instead create or activate a venv manually and install the project into
it (`pip install -e .` or similar), the installed console scripts
(`dpi-eval`, `dpi-eval-web`) are only on your `PATH` while that venv is
active — running them from a fresh shell without activating first will
fail as "command not found," not as a bug in the tool.

- `GT_DIR` — plain-text ground truth, one file per page, named
  `<stem>.gt.txt`
- `OCR_DIR` — OCR output sharing the stem: `<stem>.hocr` (e.g. from
  [iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr)), `<stem>.xml`
  (ALTO/PAGE), or `<stem>.txt`. hOCR is converted internally; everything
  else goes to dinglehopper untouched.
- `REPORTS_DIR` — receives per-page `<stem>.json` / `<stem>.html` and
  batch-level `summary.json` / `summary.html`. The tool owns this
  directory: stale reports from prior runs are cleared at the start of
  each run so re-grading never mixes old and new results.

Exit code is non-zero when more than `--max-failure-rate` of pages fail
or when there is nothing to grade. Pages with no matching OCR file are
logged and skipped.

## Project docs

- Desktop app design spec:
  `docs/superpowers/specs/2026-07-17-dpi-eval-desktop-tauri-design.md`
- Web interface design spec:
  `docs/superpowers/specs/2026-07-16-dpi-eval-web-design.md`
- Original CLI design spec:
  `docs/superpowers/specs/2026-07-16-dpi-ocr-eval-demo-design.md`
- Findings log (upstream-PR candidates, deferred ideas, lessons
  learned): `docs/findings.md`
