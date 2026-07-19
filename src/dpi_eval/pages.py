"""Self-contained HTML pages for dpi-eval-web.

Pure string builders: no framework imports, no external assets (lab
machines may be offline; nothing leaves localhost).

Display layer only: metrics arrive parsed from the engine's own JSON
reports and are formatted here, never recomputed — the engine's numbers
are the single source of truth.
"""

from html import escape

_STYLE = """
  :root {
    --space-1: .25rem; --space-2: .5rem; --space-3: 1rem; --space-4: 2rem;
    --fs-small: .875rem; --fs-base: 1rem; --fs-large: 1.25rem; --fs-xl: 2rem;
    --color-ink: #1a1a1a; --color-muted: #595959; --color-accent: #0b5fff;
    --color-ok: #1a7f37; --color-warn: #9a6700; --color-err: #b42318;
  }
  body { font-family: system-ui, sans-serif; max-width: 44rem;
         margin: var(--space-4) auto; padding: 0 var(--space-3);
         line-height: 1.5; color: var(--color-ink); }
  /* Explicit type scale: h1 > h2 > h3 (was inverted — h2 outsized h1). */
  h1 { font-size: var(--fs-xl); line-height: 1.15;
       letter-spacing: -0.01em; margin: 0 0 var(--space-2); }
  h2 { font-size: var(--fs-large); margin: var(--space-4) 0 var(--space-2); }
  h3 { font-size: var(--fs-base); margin: var(--space-3) 0 var(--space-2); }
  a { color: var(--color-accent); }
  fieldset { margin: var(--space-3) 0; border: 1px solid #767676;
             border-radius: 4px; }
  legend { font-weight: 600; }
  a:focus-visible, button:focus-visible, input:focus-visible,
  summary:focus-visible {
    outline: 3px solid #1a4a8a; outline-offset: 2px; }

  /* Button token (F13): one primary solid style, plus a quiet variant. */
  button { font-size: var(--fs-base); font-family: inherit;
           padding: var(--space-2) var(--space-4); border-radius: 4px;
           border: 1px solid var(--color-accent); cursor: pointer;
           background: var(--color-accent); color: #fff; }
  button:hover { background: #0949c9; border-color: #0949c9; }
  button[disabled] { background: var(--color-muted);
                     border-color: var(--color-muted); cursor: default; }
  button.quiet { background: #fff; color: var(--color-accent); }
  button.quiet:hover { background: #f0f5ff; }

  /* Notice component (F19): three tiers. Old .ok/.banner/.error kept as
     aliases until the 7.x copy tasks migrate their call sites. */
  .notice { padding: var(--space-2) var(--space-3);
            border: 1px solid var(--color-muted);
            border-left: 6px solid var(--color-muted); border-radius: 4px;
            margin: var(--space-3) 0; }
  .notice-ok { border-color: var(--color-ok); background: #eef7f0; }
  .notice-ok, .notice-ok > * { color: #14501f; }
  .notice-warn { border-color: var(--color-warn); background: #fdf6e7; }
  .notice-warn, .notice-warn > * { color: #6b4a00; }
  .notice-err { border-color: var(--color-err); background: #fdeeec; }
  .notice-err, .notice-err > * { color: #7f1d15; }
  .error, .banner { background: #fdecea; border: 1px solid #7a1f12;
                    padding: 0.5rem 1rem; border-radius: 4px; }
  .ok { background: #eafaf1; border: 1px solid #1d6f43;
        padding: 0.5rem 1rem; border-radius: 4px; }

  /* Verdict / score-display: the headline judgment, first on the page. */
  .verdict { margin: var(--space-4) 0; padding: var(--space-3) var(--space-4);
             border: 1px solid #d7d7d7; border-radius: 8px;
             border-left: 8px solid var(--color-muted); }
  .verdict[data-band="ok"] { border-left-color: var(--color-ok); }
  .verdict[data-band="warn"] { border-left-color: var(--color-warn); }
  .verdict[data-band="err"] { border-left-color: var(--color-err); }
  .verdict-band { font-size: var(--fs-small); font-weight: 700;
                  text-transform: uppercase; letter-spacing: .09em;
                  margin: 0 0 var(--space-1); color: var(--color-muted); }
  .verdict[data-band="ok"] .verdict-band { color: var(--color-ok); }
  .verdict[data-band="warn"] .verdict-band { color: var(--color-warn); }
  .verdict[data-band="err"] .verdict-band { color: var(--color-err); }
  .verdict-score { display: block; font-size: 3.25rem; font-weight: 700;
                   line-height: 1; letter-spacing: -0.02em;
                   font-variant-numeric: tabular-nums;
                   margin: 0 0 var(--space-2); }
  .verdict-label { margin: 0; color: var(--color-muted);
                   font-size: var(--fs-base); max-width: 34rem; }

  .section { margin: var(--space-4) 0; }
  .lead { font-size: var(--fs-large); }
  table { border-collapse: collapse; margin: var(--space-3) 0; width: 100%; }
  caption { text-align: left; font-size: var(--fs-small);
            color: var(--color-muted); padding-bottom: var(--space-2); }
  th, td { border: 1px solid #767676; padding: 0.35rem 0.6rem;
           text-align: left; }
  thead th { background: #f3f4f6; }
  td.num { font-variant-numeric: tabular-nums; text-align: right; }
  .note { font-size: var(--fs-small); color: var(--color-muted); }
  details.section > summary { cursor: pointer; font-weight: 600;
                             color: var(--color-ink); }
  ul.stems { columns: 2; }
  footer { margin-top: var(--space-4); color: var(--color-muted);
           font-size: var(--fs-small); }
"""


def _document(title: str, body: str, *, extra_head: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_STYLE}</style>
{extra_head}</head>
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


def form_page(*, token: str | None = None) -> str:
    meta = f'<meta name="dpi-eval-token" content="{escape(token)}">\n' if token else ""
    body = f"""
<h1>Grade OCR against ground truth</h1>
<p>Pick the folder with your ground-truth transcriptions
(<code>&lt;name&gt;.gt.txt</code>, one per sampled page) and the folder
with the OCR files they grade (<code>&lt;name&gt;.hocr</code>,
<code>&lt;name&gt;.xml</code>, or <code>&lt;name&gt;.txt</code> — the
name before the extension must match). Only pages with a ground-truth
file are graded.</p>
<div id="dpi-eval-error" class="error" aria-live="polite" tabindex="-1"
     hidden></div>
<form id="dpi-eval-form" action="/grade" method="post"
      enctype="multipart/form-data"
      onsubmit="var b=document.getElementById('run');b.disabled=true;b.textContent='Grading\\u2026';">
  <fieldset id="gt-fieldset">
    <legend>Ground-truth folder</legend>
    <input type="file" id="gt_files" name="gt_files" webkitdirectory
           multiple required>
    <button type="button" id="gt-picker-btn" hidden
            aria-describedby="gt-picker-path">Choose ground-truth
      folder&hellip;</button>
    <span id="gt-picker-path" class="note"></span>
  </fieldset>
  <fieldset id="ocr-fieldset">
    <legend>OCR folder</legend>
    <input type="file" id="ocr_files" name="ocr_files" webkitdirectory
           multiple required>
    <button type="button" id="ocr-picker-btn" hidden
            aria-describedby="ocr-picker-path">Choose OCR
      folder&hellip;</button>
    <span id="ocr-picker-path" class="note"></span>
  </fieldset>
  <button id="run" type="submit">Run</button>
</form>
<footer>Your files never leave this computer. Results are saved in the
<code>dpi-eval-runs</code> folder in your home folder.<br>
Done? Close this window and the terminal window it came from.</footer>
<script>
(function () {{
  window.addEventListener('load', function () {{
    if (!window.__TAURI__) return;
    var tokenMeta = document.querySelector('meta[name="dpi-eval-token"]');
    if (!tokenMeta) return;
    var token = tokenMeta.content;

    var form = document.getElementById('dpi-eval-form');
    var runBtn = document.getElementById('run');
    var errorBox = document.getElementById('dpi-eval-error');
    var selections = {{gt: null, ocr: null}};

    function showError(message) {{
      errorBox.textContent = message;
      errorBox.hidden = false;
      errorBox.focus();
    }}

    function clearError() {{
      errorBox.hidden = true;
      errorBox.textContent = '';
    }}

    function wirePicker(kind, inputId, btnId, pathId) {{
      var input = document.getElementById(inputId);
      var btn = document.getElementById(btnId);
      var pathEl = document.getElementById(pathId);
      input.hidden = true;
      input.required = false;
      btn.hidden = false;
      btn.addEventListener('click', function () {{
        window.__TAURI__.dialog.open({{directory: true}}).then(
          function (selected) {{
            if (!selected) return;
            selections[kind] = selected;
            pathEl.textContent = selected;
          }},
          function (err) {{
            showError('Could not open the folder picker: ' + err);
          }}
        );
      }});
    }}

    wirePicker('gt', 'gt_files', 'gt-picker-btn', 'gt-picker-path');
    wirePicker('ocr', 'ocr_files', 'ocr-picker-btn', 'ocr-picker-path');

    form.onsubmit = function (evt) {{
      evt.preventDefault();
      clearError();
      if (!selections.gt || !selections.ocr) {{
        showError('Choose both the ground-truth folder and the OCR folder.');
        return;
      }}
      runBtn.disabled = true;
      runBtn.textContent = 'Grading\\u2026';
      form.setAttribute('aria-busy', 'true');
      fetch('/grade-paths', {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'X-DPI-Eval-Token': token
        }},
        body: JSON.stringify({{gt_dir: selections.gt, ocr_dir: selections.ocr}})
      }}).then(function (resp) {{
        return resp.json().then(function (data) {{
          return {{ok: resp.ok, data: data}};
        }});
      }}).then(function (result) {{
        if (!result.ok) {{
          throw new Error(result.data.error || 'Grading failed.');
        }}
        window.location = result.data.run_url;
      }}).catch(function (err) {{
        showError(err.message || String(err));
        runBtn.disabled = false;
        runBtn.textContent = 'Run';
        form.setAttribute('aria-busy', 'false');
      }});
    }};
  }});
}})();
</script>
"""
    return _document("dpi-eval", body, extra_head=meta)


def _band(wer) -> tuple[str, str]:
    """Map an average WER onto a plain-language judgment band.

    Colour alone fails accessibility, so every band carries a word:
    green <=10% "Strong", amber <=25% "Review the diffs", red otherwise.
    """
    if not isinstance(wer, (int, float)):
        return ("", "No score")
    if wer <= 0.10:
        return ("ok", "Strong")
    if wer <= 0.25:
        return ("warn", "Review the diffs")
    return ("err", "Needs attention")


def _verdict_block(summary: dict) -> str:
    """The headline judgment: large tabular score + banded label, first."""
    wer = summary.get("wer_avg")
    band, word = _band(wer)
    return (
        f'<section class="verdict" data-band="{band}">'
        f'<p class="verdict-band">{escape(word)}</p>'
        f'<p class="verdict-score">{_pct(wer)}</p>'
        '<p class="verdict-label">Word error rate — the share of words '
        "that differ from the ground truth. Lower is better.</p>"
        "</section>"
    )


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
        f'<td><a href="/runs/{run}/reports/{escape(stem)}">View diff</a></td>'
        "</tr>"
        for stem in succeeded
    )
    return (
        '<table class="section"><caption>Per-page scores. Percentages show '
        "how much of each page differs from the ground truth.</caption>"
        '<thead><tr><th scope="col">Page</th>'
        '<th scope="col">Word error rate</th>'
        '<th scope="col">Raw character error rate</th>'
        '<th scope="col">Words</th>'
        '<th scope="col">Diff</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
        '<p class="note section">These are raw scores: differences in line '
        "breaks count as errors. If you typed your transcription as flowing "
        "paragraphs, up to about half of a raw score can be layout rather "
        "than recognition — read raw scores as an upper bound. In each diff, "
        "the left column is the ground truth (what the page says) and the "
        "right column is what the OCR produced.</p>"
        '<details class="section"><summary>How these scores are calculated'
        "</summary>"
        f"<p>Raw character error rate: {_pct(summary.get('cer_avg'))} — the "
        "share of characters that differ, line breaks included.</p>"
        f"<p>Based on {len(succeeded)} graded page(s) — {total_words} "
        f"words, {total_chars} characters of ground truth.</p>"
        "</details>"
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
    summary = summary or {}
    page_metrics = page_metrics or {}
    sections = [
        "<h1>Grading results</h1>",
        f'<p class="note">Run <code>{run}</code></p>',
    ]
    if exit_code == 0:
        sections.append(_verdict_block(summary))
    elif not succeeded:
        sections.append(
            '<div class="notice notice-err"><p>Nothing was graded. Check '
            "that your ground-truth files end in <code>.gt.txt</code>, that "
            "they share names with the OCR files, and that the OCR files "
            "open correctly.</p></div>"
        )
    else:
        sections.append(
            '<div class="notice notice-warn"><p>Too many pages failed '
            f"({len(failed)} of {len(failed) + len(succeeded)}). The results "
            "below are incomplete — a supervisor should look at this "
            "batch.</p></div>"
        )
    if succeeded:
        sections.append(
            _scores_section(run, succeeded, summary, page_metrics)
        )
        sections.append(
            f'<p class="section"><a href="/runs/{run}/reports/summary">'
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
    sections.append('<p class="section"><a href="/">Grade another batch</a></p>')
    return _document(f"dpi-eval — {run_id}", "\n".join(sections))


def report_page(run_id: str, name: str, inner_html: str) -> str:
    body = (
        f"<h1>Report: {escape(name)} — {escape(run_id)}</h1>"
        f'<p class="note"><a href="/runs/{escape(run_id)}">Back to results</a></p>'
        f'<div class="section">{inner_html}</div>'
    )
    return _document(f"dpi-eval — {name}", body)


def error_page(message: str, details: tuple[str, ...] = ()) -> str:
    items = "".join(f"<li><code>{escape(d)}</code></li>" for d in details)
    detail_html = f"<ul>{items}</ul>" if items else ""
    body = (
        "<h1>Can't grade this batch</h1>"
        f'<div class="error"><p>{escape(message)}</p>{detail_html}</div>'
        '<p><a href="/">Back to the form</a></p>'
    )
    return _document("dpi-eval — problem", body)
