"""Self-contained HTML pages for dpi-eval-web.

Pure string builders: no framework imports, no external assets (lab
machines may be offline; nothing leaves localhost).

Display layer only: metrics arrive parsed from the engine's own JSON
reports and are formatted here, never recomputed — the engine's numbers
are the single source of truth.
"""

from html import escape

_STYLE = """
  body { font-family: system-ui, sans-serif; max-width: 44rem;
         margin: 2rem auto; padding: 0 1rem; line-height: 1.5;
         color: #1a1a1a; }
  h1 { font-size: 1.4rem; }
  fieldset { margin: 1rem 0; border: 1px solid #767676;
             border-radius: 4px; }
  legend { font-weight: 600; }
  button { font-size: 1rem; padding: 0.5rem 1.5rem; }
  a:focus-visible, button:focus-visible, input:focus-visible {
    outline: 3px solid #1a4a8a; outline-offset: 2px; }
  .error, .banner { background: #fdecea; border: 1px solid #7a1f12;
                    padding: 0.5rem 1rem; border-radius: 4px; }
  .ok { background: #eafaf1; border: 1px solid #1d6f43;
        padding: 0.5rem 1rem; border-radius: 4px; }
  .lead { font-size: 1.15rem; }
  table { border-collapse: collapse; margin: 1rem 0; }
  caption { text-align: left; font-size: 0.9rem; color: #3d3d3d;
            padding-bottom: 0.5rem; }
  th, td { border: 1px solid #767676; padding: 0.35rem 0.6rem;
           text-align: left; }
  td.num { font-variant-numeric: tabular-nums; text-align: right; }
  .note { font-size: 0.9rem; color: #3d3d3d; }
  ul.stems { columns: 2; }
  footer { margin-top: 3rem; color: #3d3d3d; font-size: 0.9rem; }
"""


def _document(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>"""


def _pct(value) -> str:
    """Format an engine-reported rate as a one-decimal percentage."""
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return "—"


def form_page() -> str:
    body = """
<h1>Grade OCR against ground truth</h1>
<p>Pick the folder with your ground-truth transcriptions
(<code>&lt;name&gt;.gt.txt</code>, one per sampled page) and the folder
with the OCR files they grade (<code>&lt;name&gt;.hocr</code>,
<code>&lt;name&gt;.xml</code>, or <code>&lt;name&gt;.txt</code> — the
name before the extension must match). Only pages with a ground-truth
file are graded.</p>
<form action="/grade" method="post" enctype="multipart/form-data"
      onsubmit="var b=document.getElementById('run');b.disabled=true;b.textContent='Grading\\u2026';">
  <fieldset>
    <legend>Ground-truth folder</legend>
    <input type="file" name="gt_files" webkitdirectory multiple required>
  </fieldset>
  <fieldset>
    <legend>OCR folder</legend>
    <input type="file" name="ocr_files" webkitdirectory multiple required>
  </fieldset>
  <button id="run" type="submit">Run</button>
</form>
<footer>Your files never leave this computer. Results are saved in the
<code>dpi-eval-runs</code> folder in your home folder.<br>
Done? Close this window and the terminal window it came from.</footer>
"""
    return _document("dpi-eval", body)


def _scores_section(
    run: str,
    succeeded: list[str],
    summary: dict,
    page_metrics: dict[str, dict],
) -> str:
    total_words = sum(m.get("n_words") or 0 for m in page_metrics.values())
    total_chars = sum(
        m.get("n_characters") or 0 for m in page_metrics.values()
    )
    rows = "".join(
        f'<tr><th scope="row">{escape(stem)}</th>'
        f'<td class="num">{_pct((page_metrics.get(stem) or {}).get("wer"))}</td>'
        f'<td class="num">{_pct((page_metrics.get(stem) or {}).get("cer"))}</td>'
        f'<td class="num">{(page_metrics.get(stem) or {}).get("n_words") or "—"}</td>'
        f'<td><a href="/files/{run}/reports/{escape(stem)}.html">View diff</a></td>'
        "</tr>"
        for stem in succeeded
    )
    return (
        "<h2>Batch scores</h2>"
        '<p class="lead">Word error rate: '
        f"<strong>{_pct(summary.get('wer_avg'))}</strong> — the share of "
        "words that differ from the ground truth. Lower is better.</p>"
        f"<p>Raw character error rate: {_pct(summary.get('cer_avg'))} — the "
        "share of characters that differ, line breaks included.</p>"
        '<p class="note">These are raw scores: differences in line breaks '
        "count as errors. If you typed your transcription as flowing "
        "paragraphs, up to about half of a raw score can be layout rather "
        "than recognition — read raw scores as an upper bound.</p>"
        f"<p>Based on {len(succeeded)} graded page(s) — {total_words} "
        f"words, {total_chars} characters of ground truth.</p>"
        "<p>In each diff, the <strong>left column is the ground "
        "truth</strong> (what the page says) and the <strong>right column "
        "is what the OCR produced</strong>.</p>"
        "<table><caption>Per-page scores. Percentages show how much of "
        "each page differs from the ground truth.</caption>"
        '<thead><tr><th scope="col">Page</th>'
        '<th scope="col">Word error rate</th>'
        '<th scope="col">Raw character error rate</th>'
        '<th scope="col">Words</th>'
        '<th scope="col">Diff</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def results_page(
    run_id: str,
    succeeded: list[str],
    failed: list[str],
    missing: list[str],
    exit_code: int,
    summary: dict | None = None,
    page_metrics: dict[str, dict] | None = None,
) -> str:
    run = escape(run_id)
    page_metrics = page_metrics or {}
    if exit_code == 0:
        verdict = (
            f'<div class="ok"><p>Graded {len(succeeded)} page(s).</p></div>'
        )
    elif not succeeded:
        verdict = (
            '<div class="banner"><p>Nothing was graded. Check that your '
            "ground-truth files end in <code>.gt.txt</code>, that they "
            "share names with the OCR files, and that the OCR files open "
            "correctly.</p></div>"
        )
    else:
        verdict = (
            f'<div class="banner"><p>Too many pages failed ({len(failed)} '
            f"of {len(failed) + len(succeeded)}). The results below are "
            "incomplete — a supervisor should look at this batch.</p></div>"
        )
    sections = [f"<h1>Run {run}</h1>", verdict]
    if succeeded:
        sections.append(
            _scores_section(run, succeeded, summary or {}, page_metrics)
        )
        sections.append(
            f'<p><a href="/files/{run}/reports/summary.html">'
            "<strong>Full batch summary</strong></a> &middot; "
            f'<a href="/runs/{run}/download">Download reports (.zip)</a></p>'
        )
    if failed:
        items = "".join(f"<li><code>{escape(s)}</code></li>" for s in failed)
        sections.append(
            "<h2>Pages that failed to grade</h2>"
            "<p>The grader could not read these OCR files. Open each one "
            "to check it isn't empty or damaged, then run again:</p>"
            f'<ul class="stems">{items}</ul>'
        )
    if missing:
        items = "".join(
            f"<li><code>{escape(s)}</code></li>" for s in missing
        )
        sections.append(
            "<h2>Skipped: ground truth with no matching OCR file</h2>"
            "<p>These pages were not graded because the OCR folder had "
            "no file with the same name ending in <code>.hocr</code>, "
            "<code>.xml</code>, or <code>.txt</code>:</p>"
            f'<ul class="stems">{items}</ul>'
        )
    sections.append('<p><a href="/">Grade another batch</a></p>')
    return _document(f"dpi-eval — {run_id}", "\n".join(sections))


def error_page(message: str, details: tuple[str, ...] = ()) -> str:
    items = "".join(f"<li><code>{escape(d)}</code></li>" for d in details)
    detail_html = f"<ul>{items}</ul>" if items else ""
    body = (
        "<h1>Can't grade this batch</h1>"
        f'<div class="error"><p>{escape(message)}</p>{detail_html}</div>'
        '<p><a href="/">Back to the form</a></p>'
    )
    return _document("dpi-eval — problem", body)
