# dpi-eval UX Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dpi-eval pages credible and self-explanatory for HDC colleagues (clean-and-credible bar) via review-first critique, a cut-line gate, then tracer-bullet TDD implementation.

**Architecture:** Capture screenshots of every real page state → two blind PAR critiques (flow/copy lens, visual lens) → aggregated findings → Trevor's cut-line → implementation starting with ONE end-to-end tracer slice (minimal tokens + results page restyle, test-first) before fanning out. One new read-only web.py route wraps dinglehopper-generated report HTML in the styled shell.

**Tech Stack:** FastAPI/pages.py server-rendered HTML (single `_STYLE` stylesheet), pytest (`uv run pytest`, 69 passing), Tauri v2 shell (not modified beyond what's committed), browser MCP for capture.

**Spec:** docs/superpowers/specs/2026-07-19-dpi-eval-ux-pass-design.md (APPROVED 2026-07-19).

## Model tiers (capability-matched per task)

| Task | Tier | Why this tier |
|---|---|---|
| 1 Capture | orchestrator | Browser-MCP driving + judgment about which states matter; no delegable spec yet |
| 2 Critiques | opus ×2 (blind PAR) | Evaluative taste + evidence-grounded UX judgment — the quality ceiling of the whole pass |
| 2 Aggregation | orchestrator | Mechanical merge + severity arbitration is the dispatcher's job (PAR rule) |
| 3 Cut-line | Trevor | Product judgment; only human gate can bound scope |
| 4 TRACER slice | **opus** | Establishes the design system's taste (tokens, hierarchy, verdict treatment) — the one implementation task where aesthetic judgment is the deliverable. **Works under the frontend-design skill (Trevor, 2026-07-19): the implementer loads it before writing CSS; the orchestrator loads it when reviewing design output. Applies to any 7.x task with visual scope too.** |
| 5 Wrapper route | sonnet | Well-specified route + wrap with tests written in the plan |
| 6 Placeholder | sonnet | Small, but user-facing copy quality matters (not haiku-mechanical) |
| 7.x Fan-out | sonnet; opus if touching the picker script | Applying a settled system = standard work; the script's ID-contract/footgun zone is precision work |
| 8 Final gate | orchestrator + Trevor | Verification and human walkthrough |

Fable stays reserved (standing rule: hardest problems only — none anticipated here).

## Global Constraints (from the spec — binding on every task)

- Pages stay shared (browser + desktop from one codebase); desktop divergence only via the existing feature-detected picker variant.
- Webview is a renderer: no new browser-chrome reliance.
- `web.py`: ONLY the one wrapper route may be added (Task 5). Token check, Host guard, `/grade-paths` contract untouched.
- Engine files (`runner.py`, `cli.py`, `pairing.py`, `adapter.py`) untouched; generated report files never modified — wrapped at serve time only.
- Picker script footguns preserved: `__TAURI__` probed only inside `load` handler; no iframes.
- Element-ID/meta contract fenced: `dpi-eval-form`, `gt_files`, `ocr_files`, `gt-picker-btn`, `ocr-picker-btn`, `gt-picker-path`, `ocr-picker-path`, `dpi-eval-error`, `run`, `meta[name="dpi-eval-token"]` — keep IDs, or change markup+script+tests together.
- A11y mechanisms survive: aria-live error region, focus-on-error, aria-describedby path displays, aria-busy.
- Markup tests live in `tests/test_pages.py`, `tests/test_web.py`, `tests/test_grade_paths.py`; updates must preserve the ORIGINAL guarantee, not just match new markup.
- Grading-wait feedback: static/elapsed-time messaging only. No new endpoints (beyond the wrapper route), no engine hooks.
- No time-unit estimates anywhere; effort in S/M/L.
- Commits: conventional, trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; stage only named files.

---

### Task 1: Stage 1 capture (orchestrator, browser MCP)

**Files:**
- Create: screenshots under the session scratchpad `ux-capture/` (not committed)
- Read-only: everything

- [ ] **Step 1:** Start the server with a token: `DPI_EVAL_TOKEN=cafebabecafebabecafebabecafebabe uv run dpi-eval-web --no-browser` (background; parse the sentinel URL — never assume 8765).
- [ ] **Step 2:** Browser-capture, saving PNG per state:
  - `form-browser.png` — plain GET /
  - `form-desktop-empty.png` and `form-desktop-chosen.png` — before load, inject: `window.__TAURI__ = { dialog: { open: () => Promise.resolve('/Users/student/Documents/scans') } }` (CDP addScriptToEvaluateOnNewDocument), then for the chosen state click both picker buttons.
  - `results-success.png` — grade `tests/fixtures/text` via the form or curl, open `/runs/run-NNN`.
  - `results-failure.png` — grade a folder pair that fails every page (e.g. gt with only `page_9.gt.txt` and an ocr `page_9.txt` whose gt is empty → check verdict branch; if hard to trigger, POST fixture with a gt whose OCR is missing so `missing` populates, and capture the "failed"/"Too many pages failed" banner via a batch where ocr file is an unreadable/binary file).
  - `error-no-gt.png`, `error-empty-ocr.png`, `error-collision.png` — three POSTs to /grade violating each rule.
  - `diff-page.png`, `summary.png` — the generated report pages (context + wrapper design input).
  - `placeholder-installing.png`, `placeholder-ready.png`, `placeholder-failed.png` — open `desktop/ui/index.html` as file://, injecting a stub `window.__TAURI__.event.listen` that immediately invokes the callback with each payload (`installing`, `ready`, `failed: pip exited 1`).
- [ ] **Step 3:** Ledger line listing captured states; any state that resisted capture is named there, not silently skipped.

### Task 2: Stage 2 critiques (PAR, opus x2)

**Files:**
- Create: `docs/superpowers/ux-findings-2026-07.md`

- [ ] **Step 1:** Dispatch two blind reviewers (PAR wrapper), identical inputs: all screenshots + `src/dpi_eval/pages.py` + `desktop/ui/index.html`. Lens A: flow/forms/copy per GOV.UK-style patterns (button states, error placement, instructional copy register, the two-pickers-one-Run shape). Lens B: visual credibility (hierarchy, type scale, spacing rhythm, table treatment, scannability). Both told: dinglehopper-generated diff/summary INTERNALS are out of restyle scope (framing/wrapper critique welcome; internals findings → Deferred/upstream).
- [ ] **Step 2:** Aggregate per PAR rules (dedupe, worst severity wins).
  Pre-seed one Trevor-sourced finding (2026-07-19, rides the cut-line
  like any other): **pairing pre-check** — "name before the extension
  must match" is mechanically checkable before grading; call the
  engine's own `pairing.py` matcher (read-only import — exact parity,
  no reimplementation) on the filename lists inside `_grade_pipeline`
  and 400 with the specific unmatched names instead of grading into a
  "Nothing was graded" banner. Tag: general; effort M; NOTE if chosen
  it needs a narrow spec-amendment widening the `web.py` fence to
  pipeline validation. Write `docs/superpowers/ux-findings-2026-07.md`: one finding per line item — id, severity (critical/serious/minor), effort (S/M/L), area tag (results-legibility | waiting-states | picker-feedback | general | deferred-upstream), description, screenshot reference. Include an empty `## Deferred` section for Stage 3.
- [ ] **Step 3:** Commit the findings doc.

### Task 3: Stage 3 cut-line (human gate — Trevor)

- [ ] **Step 1:** Present the findings list (terminal for the list; visual companion for any mockup comparisons — Trevor opted in for mockups).
- [ ] **Step 2:** Trevor marks the cut-line. Move below-line items into `## Deferred` in the findings doc; commit.
- [ ] **Step 3:** Orchestrator appends "Task 7.x" entries to THIS plan — one per above-line finding not already covered by Tasks 4–6 — each with files, failing-test-first steps, and complete code, following the Task 4 pattern. Commit the plan update. (This step is the defined mechanism for turning findings into tasks; it is not a placeholder — Tasks 4–6 below are cut-line-independent and fully specified.)

### Task 4: TRACER — minimal tokens + results-page restyle (TDD, sonnet)

Proves end-to-end: tokens in `_STYLE`, a restyled page, test updates that preserve intent, both variants unharmed. Scope: results page only; token set minimal (extend later, don't gold-plate).

**Files:**
- Modify: `src/dpi_eval/pages.py` (`_STYLE`, `results_page`)
- Test: `tests/test_pages.py`, `tests/test_web.py:195-200`, `tests/test_grade_paths.py:90`

**Interfaces:**
- Produces: CSS custom properties on `:root` — `--space-1..4`, `--fs-small/base/large/xl`, `--color-ink/muted/accent/ok/warn/err`, and classes `.verdict`, `.verdict-score`, `.note`, `.section` used by later tasks. Task 5's wrapper shell and Task 7.x fan-out reuse exactly these names.

- [ ] **Step 1: Write the failing test** — in `tests/test_pages.py`:

```python
def test_results_page_leads_with_verdict_score():
    page = pages.results_page(
        "run-001", ["page_0"], [], [], 0,
        summary={"wer_avg": 0.125, "cer_avg": 0.034,
                 "n_words_gt": 16, "n_characters_gt": 87},
        page_metrics={"page_0": {"wer": 0.125, "cer": 0.034, "n_words": 16}},
    )
    # Verdict-first: the score element appears before the explanatory prose.
    assert page.index('class="verdict"') < page.index("share of words")
    assert "12.5%" in page

def test_style_defines_design_tokens():
    page = pages.form_page()
    for token in ("--space-1", "--fs-base", "--color-ink"):
        assert token in page
```

- [ ] **Step 2:** `uv run pytest tests/test_pages.py -k "verdict or tokens" -v` → FAIL (no `.verdict` class, no tokens).
- [ ] **Step 3:** Implement: add the token block to `_STYLE` (`:root { --space-1: .25rem; --space-2: .5rem; --space-3: 1rem; --space-4: 2rem; --fs-small: .875rem; --fs-base: 1rem; --fs-large: 1.25rem; --fs-xl: 2rem; --color-ink: #1a1a1a; --color-muted: #595959; --color-accent: #0b5fff; --color-ok: #1a7f37; --color-warn: #9a6700; --color-err: #b42318; }`), restyle `results_page`: a `.verdict` block first (`<p class="verdict"><span class="verdict-score">12.5%</span> word error rate — …plain-language judgment…</p>`), methodology prose in a `<details class="section">` below the per-page table, existing table gains `.section` spacing. Keep `<th scope="col">` (test_web pins it — that's an a11y guarantee, preserve).
- [ ] **Step 4:** `uv run pytest` → some old assertions fail. For EACH failing assertion, identify the guarantee it pinned (e.g. `test_grade_paths.py:90` pins "page_0 appears in results" — keep, likely still passes; `test_web.py` pins `.gt.txt` guidance text presence — keep text, maybe moved). Update ONLY presentation-coupled assertions; guarantee-coupled ones must still pass or be re-expressed against the new markup with the same meaning.
- [ ] **Step 5:** `uv run pytest` → 69+2 passing. Visual check: serve, screenshot results page, compare against `results-success.png` baseline.
- [ ] **Step 6:** Commit: `feat(web): design tokens + verdict-first results page (UX tracer slice)`.

### Task 5: Report-wrapper route (TDD, sonnet)

**Files:**
- Modify: `src/dpi_eval/web.py` (ONE new GET route — the sole authorized web.py change), `src/dpi_eval/pages.py` (add `report_page()`; update the two report links in `results_page`)
- Test: `tests/test_web.py` (new tests)

**Interfaces:**
- Consumes: Task 4's `.section`/token classes for the shell.
- Produces: `GET /runs/{run_id}/reports/{name}` (name = `page_N` stem or `summary`) returning the generated HTML's `<body>` content wrapped in the styled shell with an `<h1>` and a back-link to `/runs/{run_id}`; `pages.report_page(run_id: str, name: str, inner_html: str) -> str`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_web.py`:

```python
def test_wrapped_report_serves_generated_html_in_shell(tmp_path):
    client, base = make_client(tmp_path)          # existing helper pattern in this file
    run = base / "run-001"; (run / "reports").mkdir(parents=True)
    (run / "result.json").write_text(
        '{"succeeded": ["page_0"], "failed": [], "missing": [], "exit_code": 0}'
    )
    (run / "reports" / "page_0.html").write_text(
        "<html><body><table class='diff'>DIFFCONTENT</table></body></html>"
    )
    resp = client.get("/runs/run-001/reports/page_0")
    assert resp.status_code == 200
    assert "DIFFCONTENT" in resp.text            # generated content survives
    assert 'href="/runs/run-001"' in resp.text   # back-link in our shell
    assert "--color-ink" in resp.text            # our stylesheet wraps it

def test_wrapped_report_rejects_bad_names(tmp_path):
    client, base = make_client(tmp_path)
    assert client.get("/runs/run-001/reports/../secret").status_code in (400, 404)
    assert client.get("/runs/nope/reports/page_0").status_code == 404
```

(Adapt `make_client` to however tests/test_web.py actually constructs its TestClient — reuse the existing fixture/helper, do not invent a new one.)

- [ ] **Step 2:** Run → FAIL (404, route absent).
- [ ] **Step 3:** Implement. In pages.py:

```python
def report_page(run_id: str, name: str, inner_html: str) -> str:
    body = (
        f"<h1>Report: {escape(name)} — {escape(run_id)}</h1>"
        f'<p class="note"><a href="/runs/{escape(run_id)}">Back to results</a></p>'
        f'<div class="section">{inner_html}</div>'
    )
    return _document(f"dpi-eval — {name}", body)
```

In web.py (inside create_app, after the download route):

```python
    @app.get("/runs/{run_id}/reports/{name}", response_class=HTMLResponse)
    def wrapped_report(run_id: str, name: str):
        record = _load_result(base_dir, run_id)
        if record is None or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            return HTMLResponse(pages.error_page("No such report."), status_code=404)
        report = base_dir / run_id / "reports" / f"{name}.html"
        if not report.is_file():
            return HTMLResponse(pages.error_page("No such report."), status_code=404)
        html = report.read_text(encoding="utf-8")
        body = html.split("<body", 1)[-1]
        body = body.split(">", 1)[-1].rsplit("</body>", 1)[0] if "<body" in html else html
        return pages.report_page(run_id, name, body)
```

Update `results_page`'s "View diff" and "Full batch summary" links from `/files/{run}/reports/...` to `/runs/{run}/reports/{stem}` (keep `/files` mount itself — deep links still work).
- [ ] **Step 4:** Run the new tests → PASS; full `uv run pytest` → green (update any link-asserting tests per the intent rule).
- [ ] **Step 5:** Live check: grade the fixture, click View diff — diff renders inside the shell.
- [ ] **Step 6:** Commit: `feat(web): wrap generated reports in the styled shell (spec-authorized route)`.

### Task 6: Bootstrap placeholder (TDD-lite, sonnet)

**Files:**
- Modify: `desktop/ui/index.html`

- [ ] **Step 1:** Duplicate the Task 4 token values into `index.html`'s inline `<style>`, with a comment in BOTH files: `/* tokens duplicated in desktop/ui/index.html — keep in sync */` and `/* tokens duplicated from src/dpi_eval/pages.py _STYLE — keep in sync */`.
- [ ] **Step 2:** Copy: replace "about a minute" with "Setting up on first run — usually well under a minute." Add a friendly branch for `failed:` payloads: display "Setup failed. Please quit and reopen; if it persists, note this message:" + the raw detail, styled with `--color-err`.
- [ ] **Step 3:** No pytest surface (static file; shell not run by tests). Verification: file:// open with the Task 1 event stub, all three states screenshot-compared.
- [ ] **Step 4:** Commit: `feat(desktop): placeholder tokens, honest copy, friendly failure state`.

### Task 4 addendum (cut-line: EVERYTHING, 2026-07-19)

Task 4's system additionally defines (used by 7.x): a **notice
component** with three tiers (`.notice`, `.notice-ok`, `.notice-warn`,
`.notice-err` — replacing `.ok`/`.banner`/`.error` while keeping those
class names as aliases until 7.x migrates them) and a **button token**
(`button` primary solid style; `button.quiet` secondary) [F13, F19].
Task 4 also covers F15 (H1 "Grading results", run id as caption) and
F5's label change lands in Task 5 with the link move.

### Task 7.1: Form page bundle — F3, F6, F7, F9, F10, F17 (opus — touches the picker script)

**Files:** Modify `src/dpi_eval/pages.py` (form_page: intro, fieldsets,
button, footer, picker script), tests in `tests/test_pages.py` +
`tests/test_web.py`.

- [ ] Failing tests first: numbered legends ("1. Ground-truth folder"),
  button text "Grade this batch", intro lead sentence present, footer
  terminal-sentence wrapped in an element the script can hide
  (`id="footer-terminal-note"`), picker confirmation row markup
  (`class="picked"` row with wrapping path span), status region for
  the grading wait (`id="grading-status"` aria-live, hidden until
  submit). Keep ALL fenced IDs and a11y mechanisms (ID-contract test
  from the plan's Task 7.x block lands here too).
- [ ] Implement: intro rewrite per F6 ("Choose two folders, then
  grade." + bulleted naming rules); legends numbered; Run → "Grade
  this batch"; desktop script hides `#footer-terminal-note` and
  writes picker confirmations into the `.picked` rows (✓ + wrapped
  path; file count omitted — dialog returns only a path); on submit
  both variants unhide `#grading-status` ("Grading… this can take a
  minute for large batches."). Buttons pick up the Task 4 token.
- [ ] `uv run pytest` green; commit `feat(web): form-page UX bundle`.

### Task 7.2: Results/error copy bundle — F16, F18 (sonnet)

**Files:** Modify `src/dpi_eval/pages.py` (results_page), tests.

- [ ] Failing tests: zero-success state renders "Back to the form" (not
  "Grade another batch"); a note after the download link contains
  "dpi-eval-runs". Implement; migrate results/error banners to the
  Task 4 notice tiers (warn for partial/zero-success, err for
  can't-grade, ok for success). `uv run pytest` green; commit
  `feat(web): results and recovery copy fixes`.

### Task 7.3: Pipeline validation quality — F8, F14 (sonnet, TDD, spec-amended fence)

**Files:** Modify `src/dpi_eval/web.py` (`_grade_pipeline` validation
stage ONLY, per amendment), tests in `tests/test_grade_paths.py` +
`tests/test_web.py`.

- [ ] Failing tests: (a) gt `page_1.gt.txt` + ocr `page_2.txt` → 400
  whose message names both `page_1` (no OCR) and `page_2` (no ground
  truth) — via the engine's `pairing.py` matcher imported read-only,
  NOT a reimplementation; assert parity with `discover_pairs`
  semantics by using it in the test oracle too; (b) collision message
  includes the relative paths (`a/page_0.txt`, `b/page_0.txt`), not
  bare basenames twice. Both endpoints (/grade HTML, /grade-paths
  JSON) surface the same messages in their own formats.
- [ ] Implement inside the validation stage; engine files untouched;
  token/Host/contract untouched. `uv run pytest` green; commit
  `feat(web): pairing pre-check and distinguishable collision paths`.

### Task 7.x: Cut-line findings fan-out (appended at Task 3 Step 3)

Written by the orchestrator from the approved findings, one task per finding, following Task 4's step pattern (failing test → red → implement → green → commit), tiered sonnet unless a task touches the picker script (then opus, with the ID-contract and footgun constraints quoted in the prompt). The fan-out batch ALSO adds the spec-mandated ID-contract test:

```python
def test_picker_script_ids_exist_in_markup():
    page = pages.form_page(token="t" * 32)
    for element_id in ("dpi-eval-form", "gt_files", "ocr_files",
                       "gt-picker-btn", "ocr-picker-btn",
                       "gt-picker-path", "ocr-picker-path",
                       "dpi-eval-error", "run"):
        assert f'id="{element_id}"' in page
```

### Task 8: Final gate

- [ ] **Step 1:** Orchestrator a11y-parity verification: diff every test change in this pass against the guarantee it pinned (aria-live, focus, aria-describedby, aria-busy, load-handler probe, no-iframe, `<th scope="col">`); confirm each survives in meaning, not just in string.
- [ ] **Step 2:** Rebuild payload (`build_wheelhouse.sh` — content hash picks up the new pages), relaunch dev app, Trevor walkthrough: full grade via native pickers PLUS keyboard-only pass of the picker flow and one triggered error (announcement + focus verified).
- [ ] **Step 3:** Capture final screenshots for the Task 11 write-up; ledger the outcome.

---

## Self-review record

Spec coverage: capture (T1), critique (T2), cut-line + deferred recording (T3), design system + friction areas (T4, T7.x), wrapper route (T5), placeholder incl. failed state + copy (T6), a11y verification + walkthrough (T8). Placeholder scan: T7.x is a defined generation mechanism, not deferred content; all concrete tasks carry code. Type consistency: token names and `.verdict`/`.section`/`.note` classes match between T4 (producer) and T5/T7.x (consumers); `report_page` signature consistent between pages.py and web.py snippets.
