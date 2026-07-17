# dpi-eval-web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A localhost web UI (`dpi-eval-web` console script) where an HDC student picks a ground-truth folder and an OCR folder in the browser, clicks Run, and reads dinglehopper's reports — no terminal beyond one pinned uvx command.

**Architecture:** A thin FastAPI app (`src/dpi_eval/web.py`) over the existing `dpi_eval.runner.run_batch`. HTML lives in pure string-builder functions (`src/dpi_eval/pages.py`) with no framework imports. Each grading run writes to `~/dpi-eval-runs/run-NNN/` (`gt/`, `ocr/`, `reports/`, `result.json`); dinglehopper's self-contained HTML reports are served as-is via a StaticFiles mount. The app factory takes `base_dir` as a parameter so tests inject `tmp_path`.

**Tech Stack:** Python ≥3.10, FastAPI, uvicorn, python-multipart (runtime); pytest + httpx (dev, httpx is TestClient's transport). Engine: existing `dpi_eval` package shelling out to dinglehopper.

**Spec:** `docs/superpowers/specs/2026-07-16-dpi-eval-web-design.md`

**Model tiers (per project convention):** Tasks 1–5 sonnet (standard implementation); Task 6 haiku (mechanical docs, exact text provided). Orchestrator reviews between tasks.

## Global Constraints

- NEVER import `dinglehopper.*` — it stays an unmodified subprocess dependency.
- The web layer imports ONLY `run_batch` from `dpi_eval.runner`. Do not modify `runner.py`, `cli.py`, `pairing.py`, or `adapter.py`.
- Existing CLI behavior and the existing 22 tests stay green — run the FULL suite (`uv run pytest`) at every "verify pass" step, not just the new file.
- Server binds `127.0.0.1` only; port 8765 preferred, ephemeral fallback.
- All HTML is self-contained: inline CSS, no CDN, no external requests.
- Runs live under the injected `base_dir` (`~/dpi-eval-runs` in production, `tmp_path / "runs"` in tests).
- Work on branch `feat/dpi-eval-web`. Conventional commits (repo style: `feat:`, `fix:`, `docs:`, `test:`).

---

### Task 1: Tracer bullet — one page graded through the web path

The riskiest integrations, end to end, with deliberately bare HTML: multipart upload → per-run directory → `run_batch` → `result.json` → results page → static report serving. UI polish is Task 3.

**Files:**
- Modify: `pyproject.toml` (via `uv add`)
- Create: `src/dpi_eval/pages.py`
- Create: `src/dpi_eval/web.py`
- Create: `tests/test_web.py`

**Interfaces:**
- Consumes: `dpi_eval.runner.run_batch(gt_dir, ocr_dir, reports_dir) -> tuple[BatchResult, int]` where `BatchResult` has `succeeded: list[str]`, `failed: list[str]`, `missing: list[str]`, `summary: Path | None`.
- Produces (later tasks rely on these exact names):
  - `dpi_eval.web.create_app(base_dir: Path) -> FastAPI`
  - Routes: `GET /`, `POST /grade` (fields `gt_files`, `ocr_files`) → 303 to `/runs/{run_id}`, `GET /runs/{run_id}`, static mount at `/files` serving `base_dir`
  - `run-NNN/result.json` schema: `{"succeeded": [...], "failed": [...], "missing": [...], "exit_code": 0}`
  - `dpi_eval.pages.form_page() -> str`, `pages.results_page(run_id, succeeded, failed, missing, exit_code) -> str`, `pages.error_page(message, details=()) -> str`
  - Test helper `make_client(tmp_path)` in `tests/test_web.py`

- [ ] **Step 1: Add dependencies**

```bash
uv add "fastapi>=0.110" "uvicorn>=0.29" "python-multipart>=0.0.9"
uv add --dev "httpx>=0.27"
```

Expected: `pyproject.toml` gains the three runtime deps; `httpx` lands in `[dependency-groups] dev`; `uv.lock` updates; exit 0.

- [ ] **Step 2: Write the failing tracer test**

Create `tests/test_web.py`:

```python
import json
from pathlib import Path

from fastapi.testclient import TestClient

from dpi_eval.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(tmp_path / "runs"))


def _fixture_pair() -> tuple[bytes, bytes]:
    gt = (FIXTURES / "text" / "page_0.gt.txt").read_bytes()
    ocr = (FIXTURES / "text" / "page_0.txt").read_bytes()
    return gt, ocr


def test_form_page_renders(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "webkitdirectory" in resp.text


def test_tracer_one_page_graded_through_web_path(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/runs/run-001"

    results = client.get("/runs/run-001")
    assert results.status_code == 200
    assert "page_0" in results.text

    summary = client.get("/files/run-001/reports/summary.html")
    assert summary.status_code == 200

    saved = json.loads(
        (tmp_path / "runs" / "run-001" / "result.json").read_text(encoding="utf-8")
    )
    assert saved["succeeded"] == ["page_0"]
    assert saved["exit_code"] == 0
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL (collection error) with `ModuleNotFoundError: No module named 'dpi_eval.web'`.

- [ ] **Step 4: Create the minimal pages module**

Create `src/dpi_eval/pages.py` (bare on purpose — Task 3 replaces the bodies with the real UI; keep the signatures exactly as shown because `web.py` and Task 3 depend on them):

```python
"""Self-contained HTML pages for dpi-eval-web.

Pure string builders: no framework imports, no external assets (lab
machines may be offline; nothing leaves localhost).
"""

from html import escape


def _document(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n</head>\n<body>\n{body}\n</body>\n</html>"
    )


def form_page() -> str:
    body = """
<h1>Grade OCR against ground truth</h1>
<form action="/grade" method="post" enctype="multipart/form-data">
  <label>Ground-truth folder
    <input type="file" name="gt_files" webkitdirectory multiple required></label>
  <label>OCR folder
    <input type="file" name="ocr_files" webkitdirectory multiple required></label>
  <button type="submit">Run</button>
</form>
"""
    return _document("dpi-eval", body)


def results_page(
    run_id: str,
    succeeded: list[str],
    failed: list[str],
    missing: list[str],
    exit_code: int,
) -> str:
    stems = "".join(f"<li>{escape(stem)}</li>" for stem in succeeded)
    body = (
        f"<h1>Run {escape(run_id)}</h1>"
        f"<p>graded {len(succeeded)}, failed {len(failed)}, "
        f"missing {len(missing)}, exit {exit_code}</p>"
        f"<ul>{stems}</ul>"
    )
    return _document(f"dpi-eval — {run_id}", body)


def error_page(message: str, details: tuple[str, ...] = ()) -> str:
    items = "".join(f"<li><code>{escape(d)}</code></li>" for d in details)
    detail_html = f"<ul>{items}</ul>" if items else ""
    body = f"<h1>Can't grade this batch</h1><p>{escape(message)}</p>{detail_html}" \
           '<p><a href="/">Back to the form</a></p>'
    return _document("dpi-eval — problem", body)
```

- [ ] **Step 5: Create the web app**

Create `src/dpi_eval/web.py`. Notes for the implementer: `grade` is a sync `def` on purpose — FastAPI runs it in a threadpool, so the blocking `run_batch` subprocess calls don't stall the event loop. `result.json` lives in the run dir root, NOT in `reports/`, because the engine clears `reports/` at the start of each run.

```python
"""dpi-eval-web: localhost web UI over run_batch for HDC student workers.

Imports only run_batch from the engine (spec hard constraint); never
imports dinglehopper.
"""

import json
import logging
import re
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from dpi_eval import pages
from dpi_eval.runner import run_batch

logger = logging.getLogger("dpi_eval.web")

RUN_ID = re.compile(r"run-\d{3,}")


def _real_uploads(uploads: list[UploadFile]) -> list[UploadFile]:
    """Drop no-selection placeholders and hidden junk (.DS_Store etc.)."""
    kept = []
    for upload in uploads:
        if not upload.filename:
            continue
        if Path(upload.filename).name.startswith("."):
            continue
        kept.append(upload)
    return kept


def _save(uploads: list[UploadFile], dest: Path) -> None:
    """Flatten to basenames — pairing.py expects flat directories."""
    dest.mkdir(parents=True, exist_ok=True)
    for upload in uploads:
        (dest / Path(upload.filename).name).write_bytes(upload.file.read())


def _next_run_dir(base_dir: Path) -> Path:
    highest = 0
    for existing in base_dir.glob("run-*"):
        suffix = existing.name[len("run-") :]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    run_dir = base_dir / f"run-{highest + 1:03d}"
    run_dir.mkdir(parents=True)
    return run_dir


def _load_result(base_dir: Path, run_id: str) -> dict | None:
    if not RUN_ID.fullmatch(run_id):
        return None
    result_file = base_dir / run_id / "result.json"
    if not result_file.exists():
        return None
    return json.loads(result_file.read_text(encoding="utf-8"))


def create_app(base_dir: Path) -> FastAPI:
    base_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="dpi-eval-web")
    app.mount("/files", StaticFiles(directory=base_dir), name="files")

    @app.get("/", response_class=HTMLResponse)
    def form() -> str:
        return pages.form_page()

    @app.post("/grade")
    def grade(
        gt_files: list[UploadFile] = File(default=[]),
        ocr_files: list[UploadFile] = File(default=[]),
    ):
        gt_uploads = _real_uploads(gt_files)
        ocr_uploads = _real_uploads(ocr_files)
        run_dir = _next_run_dir(base_dir)
        _save(gt_uploads, run_dir / "gt")
        _save(ocr_uploads, run_dir / "ocr")
        result, code = run_batch(
            run_dir / "gt", run_dir / "ocr", run_dir / "reports"
        )
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "missing": result.missing,
                    "exit_code": code,
                }
            ),
            encoding="utf-8",
        )
        return RedirectResponse(f"/runs/{run_dir.name}", status_code=303)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def results(run_id: str):
        record = _load_result(base_dir, run_id)
        if record is None:
            return HTMLResponse(pages.error_page("No such run."), status_code=404)
        return pages.results_page(
            run_id,
            record["succeeded"],
            record["failed"],
            record["missing"],
            record["exit_code"],
        )

    return app
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_web.py -v`
Expected: 2 passed (`test_form_page_renders`, `test_tracer_one_page_graded_through_web_path`).

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest`
Expected: 24 passed (22 existing + 2 new). No existing test touched.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/dpi_eval/pages.py src/dpi_eval/web.py tests/test_web.py
git commit -m "feat: tracer bullet — grade one page through the web path"
```

---

### Task 2: Pre-flight validation on upload

Friendly 400s before anything runs: GT selection must contain `.gt.txt` files; OCR selection must be non-empty; flattening must not collide. Hidden-file filtering (`_real_uploads`, Task 1) already keeps `.DS_Store` out of the collision check — prove it with a test.

**Files:**
- Modify: `src/dpi_eval/web.py` (add `_collisions`; insert pre-flight block at the top of `grade`)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `_real_uploads`, `pages.error_page(message, details=())`, `make_client`, `_fixture_pair` from Task 1.
- Produces: `_collisions(uploads: list[UploadFile]) -> list[str]` (original paths of colliding uploads); `POST /grade` returns `HTMLResponse` with `status_code=400` on validation failure.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
def test_gt_folder_without_gt_txt_is_rejected(tmp_path):
    client = make_client(tmp_path)
    _, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.txt", b"not a gt file", "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
    )
    assert resp.status_code == 400
    assert ".gt.txt" in resp.text
    assert not list((tmp_path / "runs").glob("run-*"))  # nothing ran


def test_empty_ocr_selection_is_rejected(tmp_path):
    client = make_client(tmp_path)
    gt, _ = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[("gt_files", ("page_0.gt.txt", gt, "text/plain"))],
    )
    assert resp.status_code == 400
    assert "OCR folder" in resp.text


def test_basename_collision_is_rejected_naming_both_paths(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("ocr_files", ("issue-1/page_0.txt", ocr, "text/plain")),
            ("ocr_files", ("issue-2/page_0.txt", ocr, "text/plain")),
        ],
    )
    assert resp.status_code == 400
    assert "issue-1/page_0.txt" in resp.text
    assert "issue-2/page_0.txt" in resp.text
    assert not list((tmp_path / "runs").glob("run-*"))


def test_hidden_files_are_ignored_not_collided(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("gt_files", (".DS_Store", b"junk", "application/octet-stream")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
            ("ocr_files", ("a/.DS_Store", b"junk", "application/octet-stream")),
            ("ocr_files", ("b/.DS_Store", b"junk", "application/octet-stream")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    run_dir = tmp_path / "runs" / "run-001"
    assert not (run_dir / "gt" / ".DS_Store").exists()
    assert not (run_dir / "ocr" / ".DS_Store").exists()
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_web.py -v`
Expected: the three rejection tests FAIL (grade currently returns 303 for everything); `test_hidden_files_are_ignored_not_collided` may already pass (filtering shipped in Task 1) — that is fine, it pins the behavior.

- [ ] **Step 3: Implement validation**

In `src/dpi_eval/web.py`, add this module-level helper after `_real_uploads`:

```python
def _collisions(uploads: list[UploadFile]) -> list[str]:
    """Original paths of uploads whose flattened basenames collide."""
    by_name: dict[str, list[str]] = {}
    for upload in uploads:
        by_name.setdefault(Path(upload.filename).name, []).append(upload.filename)
    return [
        path for paths in by_name.values() if len(paths) > 1 for path in paths
    ]
```

In `grade`, insert between the `_real_uploads` calls and `_next_run_dir`:

```python
        if not any(
            Path(u.filename).name.endswith(".gt.txt") for u in gt_uploads
        ):
            return HTMLResponse(
                pages.error_page(
                    "The ground-truth folder has no .gt.txt files. Each "
                    "transcription must be named after its OCR file, with "
                    ".gt.txt in place of the extension — for example "
                    "page_3.gt.txt grades page_3.xml."
                ),
                status_code=400,
            )
        if not ocr_uploads:
            return HTMLResponse(
                pages.error_page(
                    "The OCR folder is empty — pick the folder that holds "
                    "the .hocr, .xml, or .txt files."
                ),
                status_code=400,
            )
        colliding = _collisions(gt_uploads) + _collisions(ocr_uploads)
        if colliding:
            return HTMLResponse(
                pages.error_page(
                    "Two or more files would end up with the same name, so "
                    "grading could silently use the wrong page. Flatten the "
                    "folder or rename these files, then try again:",
                    details=tuple(colliding),
                ),
                status_code=400,
            )
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: 28 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/web.py tests/test_web.py
git commit -m "feat: pre-flight upload validation with friendly errors"
```

---

### Task 3: SUPERSEDED — do not execute this version

> **Amended 2026-07-17:** the accessibility-sprint notes amended the spec
> (see the spec's Amendment section). Execute **"Task 3 (revised)"** near
> the end of this plan instead. This original section is retained for the
> record only.

Original text follows.

#### Task 3 (original): Real UI — results page verdicts and form-page instructions

Replace the bare Task 1 HTML with the spec'd UI. Verdict logic: exit 0 → green "Graded N page(s)"; nonzero with nothing succeeded → "Nothing was graded" banner; nonzero with partial success → "Too many pages failed" banner. Failed and missing stems listed by name; links to summary, per-page reports, zip (endpoint lands in Task 4 — the link may 404 until then, which is fine within this branch).

**Files:**
- Modify: `src/dpi_eval/pages.py` (replace entire file)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: signatures from Task 1 (unchanged): `form_page()`, `results_page(run_id, succeeded, failed, missing, exit_code)`, `error_page(message, details=())`.
- Produces: report links at `/files/{run_id}/reports/{stem}.html` and `/files/{run_id}/reports/summary.html`; zip link at `/runs/{run_id}/download` (implemented in Task 4).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py` (module needs no new imports):

```python
def _grade_mixed_batch(client):
    """page_0 grades cleanly; page_1's OCR is unparseable XML; page_9 has
    GT but no OCR. Exit code 1 (1 failure / 2 pairs > 0.2 threshold)."""
    gt, ocr = _fixture_pair()
    return client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("gt_files", ("page_1.gt.txt", gt, "text/plain")),
            ("gt_files", ("page_9.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
            ("ocr_files", ("page_1.xml", b"<not-valid-alto", "text/xml")),
        ],
        follow_redirects=False,
    )


def test_partial_failure_shows_banner_and_names_pages(tmp_path):
    client = make_client(tmp_path)
    resp = _grade_mixed_batch(client)
    assert resp.status_code == 303
    page = client.get(resp.headers["location"]).text
    assert "Too many pages failed" in page
    assert "page_1" in page  # failed, named
    assert "page_9" in page  # missing OCR, named
    assert '/files/run-001/reports/page_0.html' in page
    assert '/files/run-001/reports/summary.html' in page


def test_nothing_graded_shows_banner(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_9.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    page = client.get(resp.headers["location"]).text
    assert "Nothing was graded" in page


def test_form_page_carries_instructions_and_shutdown_note(tmp_path):
    client = make_client(tmp_path)
    text = client.get("/").text
    assert ".gt.txt" in text
    assert "Close this window" in text
    assert "never leave this computer" in text
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_web.py -v`
Expected: the three new tests FAIL (bare pages have none of these strings); all earlier tests still pass.

- [ ] **Step 3: Replace pages.py with the real UI**

Replace the full contents of `src/dpi_eval/pages.py`:

```python
"""Self-contained HTML pages for dpi-eval-web.

Pure string builders: no framework imports, no external assets (lab
machines may be offline; nothing leaves localhost).
"""

from html import escape

_STYLE = """
  body { font-family: system-ui, sans-serif; max-width: 44rem;
         margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
  h1 { font-size: 1.4rem; }
  fieldset { margin: 1rem 0; border: 1px solid #bbb; border-radius: 4px; }
  legend { font-weight: 600; }
  button { font-size: 1rem; padding: 0.5rem 1.5rem; }
  .error, .banner { background: #fdecea; border: 1px solid #c0392b;
                    padding: 0.5rem 1rem; border-radius: 4px; }
  .ok { background: #eafaf1; border: 1px solid #27ae60;
        padding: 0.5rem 1rem; border-radius: 4px; }
  ul.stems { columns: 2; }
  footer { margin-top: 3rem; color: #555; font-size: 0.9rem; }
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
{body}
</body>
</html>"""


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


def results_page(
    run_id: str,
    succeeded: list[str],
    failed: list[str],
    missing: list[str],
    exit_code: int,
) -> str:
    run = escape(run_id)
    if exit_code == 0:
        verdict = f'<div class="ok"><p>Graded {len(succeeded)} page(s).</p></div>'
    elif not succeeded:
        verdict = (
            '<div class="banner"><p>Nothing was graded. Check that your '
            "ground-truth files end in <code>.gt.txt</code>, that they share "
            "names with the OCR files, and that the OCR files open "
            "correctly.</p></div>"
        )
    else:
        verdict = (
            f'<div class="banner"><p>Too many pages failed ({len(failed)} of '
            f"{len(failed) + len(succeeded)}). The results below are "
            "incomplete — a supervisor should look at this batch.</p></div>"
        )
    sections = [f"<h1>Run {run}</h1>", verdict]
    if succeeded:
        links = "".join(
            f'<li><a href="/files/{run}/reports/{escape(stem)}.html">'
            f"{escape(stem)}</a></li>"
            for stem in succeeded
        )
        sections.append(
            f'<p><a href="/files/{run}/reports/summary.html">'
            "<strong>Batch summary</strong></a> &middot; "
            f'<a href="/runs/{run}/download">Download reports (.zip)</a></p>'
            f'<h2>Per-page reports</h2><ul class="stems">{links}</ul>'
        )
    if failed:
        items = "".join(f"<li><code>{escape(s)}</code></li>" for s in failed)
        sections.append(
            f'<h2>Pages that failed to grade</h2><ul class="stems">{items}</ul>'
        )
    if missing:
        items = "".join(f"<li><code>{escape(s)}</code></li>" for s in missing)
        sections.append(
            "<h2>Ground truth with no matching OCR file</h2>"
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
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: 31 passed. If `test_tracer_one_page_graded_through_web_path` fails, the `results_page` rewrite dropped succeeded stems from the page — they must render as links.

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/pages.py tests/test_web.py
git commit -m "feat: results verdicts, report links, and form instructions"
```

---

### Task 4: Zip download

`GET /runs/{run_id}/download` packages the run's reports for handoff (supervisors, request tickets). Zip layout (spec open question, resolved here): reports only, flat — the inputs stay on the student's disk.

**Files:**
- Modify: `src/dpi_eval/web.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `_load_result`, `pages.error_page`, run layout `base_dir/run-NNN/reports/` from Task 1.
- Produces: `GET /runs/{run_id}/download` → `FileResponse` (`application/zip`, filename `dpi-eval-{run_id}-reports.zip`); 404 for unknown runs and runs with no reports directory.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`; add these two imports at the top of the file:

```python
import io
import zipfile
```

```python
def test_zip_download_contains_reports(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    resp = client.get("/runs/run-001/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(archive.namelist())
    assert {"summary.json", "summary.html", "page_0.json", "page_0.html"} <= names


def test_zip_download_unknown_run_is_404(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/runs/run-999/download").status_code == 404
    assert client.get("/runs/../etc/download").status_code == 404


def test_zip_download_without_reports_is_404(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    # GT stem matches nothing → zero pairs → engine never creates reports/
    client.post(
        "/grade",
        files=[
            ("gt_files", ("page_9.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    assert client.get("/runs/run-001/download").status_code == 404
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_web.py -v`
Expected: the three new tests FAIL with 404s where 200 is expected (route missing) — except the unknown-run test, which may already pass via FastAPI's default 404; keep it as a pin.

- [ ] **Step 3: Implement the download route**

In `src/dpi_eval/web.py`: add `import shutil` to the imports, add `FileResponse` to the `fastapi.responses` import line, and add this route inside `create_app` after `results`:

```python
    @app.get("/runs/{run_id}/download")
    def download(run_id: str):
        record = _load_result(base_dir, run_id)
        reports_dir = base_dir / run_id / "reports"
        if record is None or not reports_dir.is_dir():
            return HTMLResponse(
                pages.error_page("No reports for that run."), status_code=404
            )
        archive = shutil.make_archive(
            str(base_dir / run_id / f"dpi-eval-{run_id}-reports"),
            "zip",
            root_dir=reports_dir,
        )
        return FileResponse(
            archive,
            media_type="application/zip",
            filename=f"dpi-eval-{run_id}-reports.zip",
        )
```

Note: `_load_result` already rejects any `run_id` not matching `run-\d{3,}`, so `base_dir / run_id` never escapes `base_dir`.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: 35 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/web.py tests/test_web.py
git commit -m "feat: zip download of run reports"
```

---

### Task 5: Launcher — port pick, browser open, console script

`main()` wires it together: port 8765 or ephemeral fallback, `webbrowser.open` after a 1-second delay (the server must be listening first), uvicorn on `127.0.0.1`, and the `dpi-eval-web` entry point.

**Files:**
- Modify: `src/dpi_eval/web.py`
- Modify: `pyproject.toml` (`[project.scripts]`)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `create_app` from Task 1.
- Produces: `_pick_port(preferred: int = PREFERRED_PORT) -> int`; `main() -> int`; console script `dpi-eval-web`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`; add `import socket` to the top of the file:

```python
def test_pick_port_falls_back_when_preferred_taken():
    from dpi_eval.web import _pick_port

    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        busy = blocker.getsockname()[1]
        chosen = _pick_port(preferred=busy)
        assert chosen != busy


def test_pick_port_prefers_free_port():
    from dpi_eval.web import _pick_port

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    assert _pick_port(preferred=free) == free
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py -v`
Expected: both FAIL with `ImportError: cannot import name '_pick_port'`.

- [ ] **Step 3: Implement the launcher**

In `src/dpi_eval/web.py`, add to the stdlib imports: `import socket`, `import threading`, `import webbrowser`; add `import uvicorn` with the third-party imports. Add module constants after `RUN_ID`:

```python
HOST = "127.0.0.1"
PREFERRED_PORT = 8765
```

Add at the bottom of the file:

```python
def _pick_port(preferred: int = PREFERRED_PORT) -> int:
    """Prefer the bookmarkable port; fall back to an ephemeral one."""
    try:
        with socket.socket() as probe:
            probe.bind((HOST, preferred))
            return preferred
    except OSError:
        with socket.socket() as probe:
            probe.bind((HOST, 0))
            return probe.getsockname()[1]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    port = _pick_port()
    url = f"http://{HOST}:{port}"
    app = create_app(Path.home() / "dpi-eval-runs")
    print(f"dpi-eval-web running at {url}")
    print("Done? Close the browser tab, then close this window (or press Ctrl+C).")
    threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0
```

In `pyproject.toml`, extend `[project.scripts]`:

```toml
[project.scripts]
dpi-eval = "dpi_eval.cli:main"
dpi-eval-web = "dpi_eval.web:main"
```

Then run `uv sync` to register the script.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: 37 passed.

- [ ] **Step 5: Manual verification (superpowers:verification-before-completion)**

```bash
uv run dpi-eval-web
```

Expected: terminal prints `dpi-eval-web running at http://127.0.0.1:8765`; a browser tab opens on the form. Grade `tests/fixtures/text` as both folders (GT folder: `tests/fixtures/text`; OCR folder: `tests/fixtures/text`), confirm the results page, one per-page report, `summary.html`, and the zip download. Confirm `~/dpi-eval-runs/run-001/` exists. Ctrl+C stops the server. Also confirm the CLI is untouched: `uv run dpi-eval --help` prints usage.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/dpi_eval/web.py tests/test_web.py
git commit -m "feat: dpi-eval-web launcher with port fallback and browser open"
```

---

### Task 6: Docs — README section and findings entries

Mechanical; exact text below. (haiku tier)

**Files:**
- Modify: `README.md` (insert new section after the "Usage" section, before "Quickstart: you already have OCR files")
- Modify: `docs/findings.md` (update entry #5 status; append entry #8 —
  a parallel session already committed an entry #7 on 2026-07-17)

**Interfaces:** none — prose only.

- [ ] **Step 1: Add README section**

Insert into `README.md` after the "Usage" section:

```markdown
## Web interface (for HDC student workers)

No terminal skills needed beyond one pinned command:

    uvx --from git+https://github.com/trevormunoz/dpi-dinglehopper-eval dpi-eval-web

A browser tab opens (bookmarkable at http://127.0.0.1:8765 when free).
Pick your ground-truth folder and your OCR folder, click Run, and read
the batch summary and per-page reports. Results are saved under
`dpi-eval-runs` in your home folder; "Download reports (.zip)" packages
a run for handoff. Files never leave your computer — the page is served
from localhost only. Done? Close the browser tab and the terminal
window it came from.
```

- [ ] **Step 2: Update findings entry #5 status**

In `docs/findings.md`, at the end of entry #5 ("Web interface for student workers"), replace the line:

```markdown
**Trigger to build.** An HDC pilot is actually scheduled (take Pamela up on
the workflow tour first).
```

with:

```markdown
**Trigger to build.** An HDC pilot is actually scheduled (take Pamela up on
the workflow tour first).

**Status (2026-07-16).** Built ahead of the pilot as `dpi-eval-web` (spec:
`docs/superpowers/specs/2026-07-16-dpi-eval-web-design.md`) — localhost
FastAPI wrapper over `run_batch`, launched by the same uvx mechanism.
```

- [ ] **Step 3: Append findings entry #8**

Append to `docs/findings.md`:

```markdown
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
```

- [ ] **Step 4: Verify docs render and nothing else changed**

Run: `git diff --stat`
Expected: only `README.md` and `docs/findings.md` changed.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/findings.md
git commit -m "docs: web UI quickstart and scope-fence findings"
```

---

### Task 3 (revised 2026-07-17): Accessible results display and form polish

Supersedes the original Task 3 per the spec's Amendment section. Replace
the bare Task 1 HTML with the accessible results display: engine-produced
scores (WER first, raw CER caveated), WCAG 2.1 AA markup, labelled diff
orientation, loud skips/failures with plain-language reasons, plus the
form-page instructions and shutdown footer. The zip link renders before
Task 4 implements its endpoint — fine within this branch.

**Files:**
- Modify: `src/dpi_eval/pages.py` (replace entire file)
- Modify: `src/dpi_eval/web.py` (add `_read_json`; expand the `results` route)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: Task 1's run layout (`base_dir/run-NNN/reports/`), `_load_result`,
  engine JSON — `summary.json` keys `wer_avg`/`cer_avg`/`num_reports`
  (use `.get`; degrade missing values to "—"), per-page `<stem>.json` keys
  `wer`/`cer`/`n_words`/`n_characters`.
- Produces: `pages.results_page(run_id, succeeded, failed, missing,
  exit_code, summary=None, page_metrics=None)` (two new optional params);
  `web._read_json(path: Path) -> dict | None`. Report links unchanged:
  `/files/{run_id}/reports/{stem}.html`, `.../summary.html`; zip at
  `/runs/{run_id}/download` (Task 4).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
def test_partial_failure_shows_banner_and_names_pages(tmp_path):
    """Display-contract test: render a run whose engine verdict recorded
    one failed and one skipped page. The run dir is written directly
    because no upload payload can deterministically fail dinglehopper
    0.11.0 — it falls back to plain-text grading for unrecognized XML
    (verified 2026-07-17). Engine-level failure behavior is covered in
    tests/test_batch.py via the directory trick, which uploads cannot
    reproduce."""
    client = make_client(tmp_path)
    run_dir = tmp_path / "runs" / "run-001"
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "succeeded": ["page_0"],
                "failed": ["page_1"],
                "missing": ["page_9"],
                "exit_code": 1,
            }
        ),
        encoding="utf-8",
    )
    page = client.get("/runs/run-001").text
    assert "Too many pages failed" in page
    assert "page_1" in page  # failed, named
    assert "could not read" in page  # failure reason in plain language
    assert "page_9" in page  # missing OCR, named
    assert "no file with the same name" in page  # skip reason
    assert '/files/run-001/reports/page_0.html' in page
    assert '/files/run-001/reports/summary.html' in page


def test_nothing_graded_shows_banner(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_9.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    page = client.get(resp.headers["location"]).text
    assert "Nothing was graded" in page


def test_results_show_scores_wer_first_with_caveat(tmp_path):
    client = make_client(tmp_path)
    gt, ocr = _fixture_pair()
    resp = client.post(
        "/grade",
        files=[
            ("gt_files", ("page_0.gt.txt", gt, "text/plain")),
            ("ocr_files", ("page_0.txt", ocr, "text/plain")),
        ],
        follow_redirects=False,
    )
    page = client.get(resp.headers["location"]).text
    assert "Word error rate" in page
    assert "Raw character error rate" in page
    # WER leads: its first mention precedes CER's first mention
    assert page.index("Word error rate") < page.index("Raw character error rate")
    assert "%" in page
    assert "upper bound" in page  # findings §7 caveat
    assert "left column is the ground truth" in page
    assert "Based on 1 graded page" in page
    assert '<th scope="col">' in page
    assert '<th scope="row">' in page
    assert "<main>" in page


def test_form_page_carries_instructions_and_shutdown_note(tmp_path):
    client = make_client(tmp_path)
    text = client.get("/").text
    assert ".gt.txt" in text
    assert "Close this window" in text
    assert "never leave this computer" in text
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_web.py -v`
Expected: the four new tests FAIL (bare pages have none of these strings);
all earlier tests still pass.

- [ ] **Step 3: Replace pages.py with the accessible UI**

Replace the full contents of `src/dpi_eval/pages.py`:

```python
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
```

- [ ] **Step 4: Expand the results route**

In `src/dpi_eval/web.py`, add this helper after `_load_result`:

```python
def _read_json(path: Path) -> dict | None:
    """Best-effort read of an engine-written JSON report for display."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("unreadable report JSON %s", path)
        return None
```

Replace the body of the `results` route with:

```python
    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def results(run_id: str):
        record = _load_result(base_dir, run_id)
        if record is None:
            return HTMLResponse(
                pages.error_page("No such run."), status_code=404
            )
        reports_dir = base_dir / run_id / "reports"
        summary = _read_json(reports_dir / "summary.json")
        page_metrics = {}
        for stem in record["succeeded"]:
            metrics = _read_json(reports_dir / f"{stem}.json")
            if metrics is not None:
                page_metrics[stem] = metrics
        return pages.results_page(
            run_id,
            record["succeeded"],
            record["failed"],
            record["missing"],
            record["exit_code"],
            summary=summary,
            page_metrics=page_metrics,
        )
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: 32 passed. If `test_results_show_scores_wer_first_with_caveat`
fails on `wer_avg`/`cer_avg`, inspect an actual `summary.json` from a test
run and report the real key names as a concern rather than renaming keys
speculatively — `_pct(None)` already degrades to "—", so only the
assertion on "%" would fail.

- [ ] **Step 6: Commit**

```bash
git add src/dpi_eval/pages.py src/dpi_eval/web.py tests/test_web.py
git commit -m "feat: accessible results display — engine scores, WER-first, AA markup"
```

---

## Final verification (orchestrator)

- [ ] `uv run pytest` → 37 passed
- [ ] `git log --oneline main..HEAD` shows the spec commits plus one commit per task
- [ ] Spec section check: every component (entry point, form, grade, results, static serving, zip) has a shipped route/function and a test
- [ ] Ship / Show / Ask decision with the user (branch → PR)
