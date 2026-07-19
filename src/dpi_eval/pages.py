"""Self-contained HTML pages for dpi-eval-web.

Pure string builders: no framework imports, no external assets (lab
machines may be offline; nothing leaves localhost).

Display layer only: metrics arrive parsed from the engine's own JSON
reports and are formatted here, never recomputed — the engine's numbers
are the single source of truth.
"""

from html import escape

_STYLE = """
  /* tokens hand-duplicated in desktop/ui/index.html — keep in sync */
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

  /* Progressive form (F6/F10/F17/F7). Every cue here is visual only:
     no rule disables a control or removes it from the tab order. */
  fieldset { transition: opacity .18s ease; }
  fieldset.is-muted { opacity: .55; }
  .picked { display: flex; flex-wrap: wrap; align-items: baseline;
            gap: var(--space-1) var(--space-2); margin-top: var(--space-2); }
  .picked-check { color: var(--color-ok); font-weight: 700; }
  .picked-name { font-weight: 600; }
  .picked-path { flex-basis: 100%; color: var(--color-muted);
                 font-size: var(--fs-small); overflow-wrap: anywhere; }
  form.is-grading { opacity: .6; transition: opacity .18s ease; }
  .grading-status { margin: var(--space-3) 0;
                    padding: var(--space-2) var(--space-3);
                    border: 1px solid var(--color-accent);
                    border-left: 6px solid var(--color-accent);
                    border-radius: 4px; }
  .grading-status-headline { margin: 0; font-size: var(--fs-large);
                             font-weight: 600; }
  .grading-elapsed { font-variant-numeric: tabular-nums;
                     color: var(--color-muted); }
  @media (prefers-reduced-motion: reduce) {
    fieldset, form.is-grading { transition: none; }
  }
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
    # Plain (non-f) string: the inline script is full of `{}` literals, so
    # kept un-escaped for readability. No Python interpolation happens here;
    # the token is injected via `meta` in the document head instead.
    body = """
<h1>Grade OCR against ground truth</h1>
<div id="grading-status" class="grading-status" hidden>
  <p class="grading-status-headline"><span id="grading-status-msg"
      aria-live="polite"></span><span id="grading-elapsed"
      aria-hidden="true"></span></p>
  <p class="note">Still working — the page updates when grading finishes.</p>
</div>
<p class="lead">Choose two folders, then grade.</p>
<p>The name before the extension pairs a ground-truth file with the OCR
file it grades. Only pages that have a ground-truth file are graded.</p>
<ul>
  <li>Ground-truth files end in <code>.gt.txt</code> — one per sampled
    page.</li>
  <li>OCR files end in <code>.hocr</code>, <code>.xml</code>, or
    <code>.txt</code>.</li>
  <li>Matching names pair up: <code>page_0.gt.txt</code> grades
    <code>page_0.txt</code>.</li>
</ul>
<div id="dpi-eval-error" class="error" aria-live="polite" tabindex="-1"
     hidden></div>
<form id="dpi-eval-form" action="/grade" method="post"
      enctype="multipart/form-data"
      onsubmit="if(window.__dpiStartGrading)window.__dpiStartGrading();">
  <fieldset id="gt-fieldset">
    <legend>1. Ground-truth folder</legend>
    <input type="file" id="gt_files" name="gt_files" webkitdirectory
           multiple required>
    <button type="button" id="gt-picker-btn" hidden
            aria-describedby="gt-picker-path">Choose ground-truth
      folder&hellip;</button>
    <div id="gt-picker-path" class="picked" hidden>
      <span class="picked-check" aria-hidden="true">&#10003;</span>
      <span class="picked-name"></span>
      <span class="picked-path"></span>
    </div>
  </fieldset>
  <fieldset id="ocr-fieldset">
    <legend>2. OCR folder</legend>
    <input type="file" id="ocr_files" name="ocr_files" webkitdirectory
           multiple required>
    <button type="button" id="ocr-picker-btn" hidden
            aria-describedby="ocr-picker-path">Choose OCR
      folder&hellip;</button>
    <div id="ocr-picker-path" class="picked" hidden>
      <span class="picked-check" aria-hidden="true">&#10003;</span>
      <span class="picked-name"></span>
      <span class="picked-path"></span>
    </div>
  </fieldset>
  <div id="ready-notice" class="notice notice-ok"
       hidden>Both folders chosen — ready to grade.</div>
  <button id="run" type="submit">Grade this batch</button>
</form>
<footer>Your files never leave this computer. Results are saved in the
<code>dpi-eval-runs</code> folder in your home folder.<br>
Done? Close this window<span id="footer-terminal-note"> and the
terminal window it came from</span>.</footer>
<script>
(function () {
  var gradingTimer = null;

  // Shared by both variants: the browser form calls this from its inline
  // onsubmit before its native POST navigation; the desktop handler calls
  // it after validation, before fetch.
  function startGrading() {
    var form = document.getElementById('dpi-eval-form');
    var runBtn = document.getElementById('run');
    var status = document.getElementById('grading-status');
    var statusMsg = document.getElementById('grading-status-msg');
    var elapsed = document.getElementById('grading-elapsed');
    runBtn.disabled = true;
    runBtn.textContent = 'Grading…';
    form.setAttribute('aria-busy', 'true');
    form.classList.add('is-grading');
    status.hidden = false;
    // Announced once via the aria-live message element. The elapsed
    // counter below lives outside that region (and is aria-hidden), so
    // its per-second ticks are never announced.
    statusMsg.textContent = 'Grading your batch…';
    var started = Date.now();
    function tick() {
      var s = Math.round((Date.now() - started) / 1000);
      elapsed.textContent = ' (' + s + 's)';
    }
    tick();
    gradingTimer = setInterval(tick, 1000);
  }
  window.__dpiStartGrading = startGrading;

  function resetGrading() {
    if (gradingTimer) { clearInterval(gradingTimer); gradingTimer = null; }
    var form = document.getElementById('dpi-eval-form');
    var runBtn = document.getElementById('run');
    var status = document.getElementById('grading-status');
    runBtn.disabled = false;
    runBtn.textContent = 'Grade this batch';
    form.setAttribute('aria-busy', 'false');
    form.classList.remove('is-grading');
    status.hidden = true;
  }

  window.addEventListener('load', function () {
    if (!window.__TAURI__) return;
    var tokenMeta = document.querySelector('meta[name="dpi-eval-token"]');
    if (!tokenMeta) return;
    var token = tokenMeta.content;

    var form = document.getElementById('dpi-eval-form');
    var errorBox = document.getElementById('dpi-eval-error');
    var readyNotice = document.getElementById('ready-notice');
    var ocrFieldset = document.getElementById('ocr-fieldset');
    var termNote = document.getElementById('footer-terminal-note');
    if (termNote) termNote.hidden = true;  // desktop has no terminal (F3)
    var selections = {gt: null, ocr: null};

    function showError(message) {
      errorBox.textContent = message;
      errorBox.hidden = false;
      errorBox.focus();
    }

    function clearError() {
      errorBox.hidden = true;
      errorBox.textContent = '';
    }

    function updateReadyState() {
      // Muting step 2 is a visual hint only (opacity via .is-muted); it
      // never disables the control or removes it from the tab order, so a
      // keyboard-first user may still choose OCR first.
      if (selections.gt) ocrFieldset.classList.remove('is-muted');
      else ocrFieldset.classList.add('is-muted');
      readyNotice.hidden = !(selections.gt && selections.ocr);
    }

    function wirePicker(kind, inputId, btnId, pathId) {
      var input = document.getElementById(inputId);
      var btn = document.getElementById(btnId);
      var pathEl = document.getElementById(pathId);
      input.hidden = true;
      input.required = false;
      btn.hidden = false;
      btn.addEventListener('click', function () {
        window.__TAURI__.dialog.open({directory: true}).then(
          function (selected) {
            if (!selected) return;
            selections[kind] = selected;
            var parts = selected.split(/[/\\\\]/).filter(Boolean);
            var name = parts.length ? parts[parts.length - 1] : selected;
            pathEl.querySelector('.picked-name').textContent = name;
            pathEl.querySelector('.picked-path').textContent = selected;
            pathEl.hidden = false;
            updateReadyState();
          },
          function (err) {
            showError('Could not open the folder picker: ' + err);
          }
        );
      });
    }

    ocrFieldset.classList.add('is-muted');
    wirePicker('gt', 'gt_files', 'gt-picker-btn', 'gt-picker-path');
    wirePicker('ocr', 'ocr_files', 'ocr-picker-btn', 'ocr-picker-path');

    form.onsubmit = function (evt) {
      evt.preventDefault();
      clearError();
      if (!selections.gt || !selections.ocr) {
        showError('Choose both the ground-truth folder and the OCR folder.');
        return;
      }
      startGrading();
      fetch('/grade-paths', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-DPI-Eval-Token': token
        },
        body: JSON.stringify({gt_dir: selections.gt, ocr_dir: selections.ocr})
      }).then(function (resp) {
        return resp.json().then(function (data) {
          return {ok: resp.ok, data: data};
        });
      }).then(function (result) {
        if (!result.ok) {
          throw new Error(result.data.error || 'Grading failed.');
        }
        window.location = result.data.run_url;
      }).catch(function (err) {
        showError(err.message || String(err));
        resetGrading();
      });
    };
  });
})();
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
            '<div class="notice notice-err"><p>None of the pages could be '
            "graded. The files matched up by name, but grading failed on "
            "every page — check that the OCR files open correctly, or "
            "show this page to a supervisor.</p></div>"
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
            f'<p class="note section"><a href="/runs/{run}/reports/summary">'
            "Full technical report</a> &middot; "
            f'<a href="/runs/{run}/download">Download reports (.zip)</a>'
            " — the zip goes to your Downloads folder.</p>"
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
    # F16: nothing was graded in the zero-success state, so the exit link
    # must not claim grading happened.
    exit_text = "Grade another batch" if succeeded else "Back to the form"
    sections.append(f'<p class="section"><a href="/">{exit_text}</a></p>')
    return _document(f"dpi-eval — {run_id}", "\n".join(sections))


def report_page(run_id: str, name: str, inner_html: str) -> str:
    run = escape(run_id)
    body = (
        # GOV.UK back-link convention: the back link sits above the H1.
        f'<p class="note"><a href="/runs/{run}">Back to results</a></p>'
        f"<h1>Technical report: {escape(name)}</h1>"
        f'<p class="note">Run <code>{run}</code></p>'
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
