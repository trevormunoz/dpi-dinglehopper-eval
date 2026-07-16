# DPI OCR-Evaluation Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thin glue around an unmodified dinglehopper so one command grades a directory of OCR output (ALTO/PAGE/text passthrough, hOCR via adapter) against plain-text ground truth and emits per-page `report.json` + batch `summary.json`.

**Architecture:** Tracer bullet first — Task 1 pushes one plain-text pair through `dinglehopper` (subprocess) and `dinglehopper-summarize` end-to-end. Later tasks widen the bullet: pair discovery, hOCR adapter, batch policy (skip-and-log, failure threshold), CLI. dinglehopper is invoked only via its console scripts (the stable public contract); no imports of its internals.

**Tech Stack:** Python ≥3.10 (uv-managed venv, 3.13 pinned), dinglehopper 0.11.x (installed), lxml (already present as dinglehopper dep), pytest (dev), argparse + subprocess (stdlib).

## Global Constraints

- dinglehopper is an **unmodified dependency** — never edit, vendor, or import from `dinglehopper.*`; invoke only the `dinglehopper` and `dinglehopper-summarize` console scripts (spec: "Adopt … Do not fork")
- OCR input formats: ALTO/PAGE/plain text pass through untouched; **hOCR converted by the adapter** (spec scope fence, amended 2026-07-16)
- GT pairing convention: `<stem>.gt.txt` grades `<stem>.hocr` / `<stem>.xml` / `<stem>.txt` (spec: iiif_ocr `page_{i}` stems)
- Error policy: skip-and-log per page; exit non-zero when failures exceed threshold (spec: "fail loudly at batch level")
- No new metrics, no custom report formats, no dashboard, no PDF-text handling (spec scope fence)
- All commits end with `Co-Authored-By:` trailer per repo convention (see `git log`)

## Model Orchestration

Per the sprint constraint, tasks are tiered by the judgment they require. When dispatching subagents via the Agent tool, pass the task's `model` value; the orchestrator (Fable) stays in the loop only where marked.

| Tier | Model | Used for |
|---|---|---|
| Mechanical | `haiku` | Fixtures, docs, single pure functions with fully specified tests |
| Standard | `sonnet` | TDD implementation tasks (test + code given in plan; integration judgment needed when reality deviates) |
| Fable-level | `fable` (orchestrator) | Reviewing each task's diff against the spec's scope fence; Task 8 spec-compliance review + findings synthesis. **Not used for code generation.** |

---

### Task 1: Package scaffold + tracer bullet (plain text end-to-end)

**Model:** `sonnet`

**Files:**
- Modify: `pyproject.toml`
- Create: `src/dpi_eval/__init__.py`
- Create: `src/dpi_eval/runner.py`
- Create: `tests/fixtures/text/page_0.gt.txt`
- Create: `tests/fixtures/text/page_0.txt`
- Test: `tests/test_tracer.py`

**Interfaces:**
- Consumes: `dinglehopper GT OCR [REPORT_PREFIX] [REPORTS_FOLDER]` and `dinglehopper-summarize [REPORTS_FOLDER]` console scripts on PATH (venv)
- Produces: `run_page(gt: Path, ocr: Path, reports_dir: Path, prefix: str) -> Path` (returns path to `<prefix>.json`; raises `subprocess.CalledProcessError` on dinglehopper failure) and `summarize(reports_dir: Path) -> Path` (returns path to `summary.json`) in `dpi_eval.runner`

- [ ] **Step 1: Convert scaffold to an installable src-layout package with pytest**

Replace `pyproject.toml` with:

```toml
[project]
name = "dpi-dinglehopper-eval"
version = "0.1.0"
description = "DPI glue around dinglehopper: grade OCR output against ground-truth samples"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "dinglehopper>=0.11.0",
]

[project.scripts]
dpi-eval = "dpi_eval.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dpi_eval"]

[dependency-groups]
dev = ["pytest>=8"]
```

Create `src/dpi_eval/__init__.py` (empty file). Then run:

```bash
uv sync
```

Expected: resolves cleanly, installs `dpi-dinglehopper-eval` in editable mode plus pytest. (`dpi-eval` script will fail to import until Task 5 creates `cli.py` — that is fine; nothing calls it yet.)

- [ ] **Step 2: Create text fixtures**

`tests/fixtures/text/page_0.gt.txt`:

```
The quick brown fox jumps over the lazy dog.
A second line of perfectly ordinary prose.
```

`tests/fixtures/text/page_0.txt` (simulated OCR with two character errors):

```
The quick brovvn fox jumps over the 1azy dog.
A second line of perfectly ordinary prose.
```

- [ ] **Step 3: Write the failing tracer test**

`tests/test_tracer.py`:

```python
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_run_page_produces_parseable_report(tmp_path):
    from dpi_eval.runner import run_page

    report = run_page(
        gt=FIXTURES / "text" / "page_0.gt.txt",
        ocr=FIXTURES / "text" / "page_0.txt",
        reports_dir=tmp_path,
        prefix="page_0",
    )
    assert report == tmp_path / "page_0.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert 0 < data["cer"] < 0.5
    assert 0 < data["wer"] <= 1
    assert data["n_characters"] > 0


def test_summarize_rolls_up_reports(tmp_path):
    from dpi_eval.runner import run_page, summarize

    run_page(
        gt=FIXTURES / "text" / "page_0.gt.txt",
        ocr=FIXTURES / "text" / "page_0.txt",
        reports_dir=tmp_path,
        prefix="page_0",
    )
    summary = summarize(tmp_path)
    assert summary == tmp_path / "summary.json"
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data  # parses and is non-empty
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_tracer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dpi_eval.runner'`

- [ ] **Step 5: Write minimal runner**

`src/dpi_eval/runner.py`:

```python
"""Run dinglehopper over GT/OCR pairs via its console scripts."""

import subprocess
from pathlib import Path


def run_page(gt: Path, ocr: Path, reports_dir: Path, prefix: str) -> Path:
    """Grade one OCR file against one GT file. Returns path to the JSON report."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["dinglehopper", str(gt), str(ocr), prefix, str(reports_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return reports_dir / f"{prefix}.json"


def summarize(reports_dir: Path) -> Path:
    """Roll up all per-page reports in reports_dir into summary.{json,html}."""
    subprocess.run(
        ["dinglehopper-summarize", str(reports_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return reports_dir / "summary.json"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_tracer.py -v`
Expected: 2 PASSED. If `summary.json` lands elsewhere, run `uv run dinglehopper-summarize --help` and adjust `summarize()`'s return path to match actual behavior — the test asserts the real contract.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/ tests/
git commit -m "feat: tracer bullet — one text pair through dinglehopper to summary.json

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Pair discovery

**Model:** `haiku`

**Files:**
- Create: `src/dpi_eval/pairing.py`
- Test: `tests/test_pairing.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure function)
- Produces: `discover_pairs(gt_dir: Path, ocr_dir: Path) -> tuple[list[tuple[Path, Path]], list[str]]` in `dpi_eval.pairing` — first element is sorted `(gt, ocr)` pairs, second is sorted stems of GT files with no OCR match. OCR extensions tried in order: `.hocr`, `.xml`, `.txt`.

- [ ] **Step 1: Write the failing test**

`tests/test_pairing.py`:

```python
from pathlib import Path

from dpi_eval.pairing import discover_pairs


def make(p: Path, name: str) -> Path:
    f = p / name
    f.write_text("x", encoding="utf-8")
    return f


def test_pairs_by_stem_across_extensions(tmp_path):
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    g0 = make(gt_dir, "page_0.gt.txt")
    g1 = make(gt_dir, "page_1.gt.txt")
    g2 = make(gt_dir, "page_2.gt.txt")
    o0 = make(ocr_dir, "page_0.hocr")
    o1 = make(ocr_dir, "page_1.xml")
    # page_2 has no OCR file; stray file must be ignored
    make(ocr_dir, "notes.md")

    pairs, missing = discover_pairs(gt_dir, ocr_dir)
    assert pairs == [(g0, o0), (g1, o1)]
    assert missing == ["page_2"]


def test_hocr_preferred_over_txt_for_same_stem(tmp_path):
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    make(gt_dir, "page_0.gt.txt")
    hocr = make(ocr_dir, "page_0.hocr")
    make(ocr_dir, "page_0.txt")

    pairs, missing = discover_pairs(gt_dir, ocr_dir)
    assert pairs[0][1] == hocr
    assert missing == []


def test_empty_dirs_yield_nothing(tmp_path):
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    assert discover_pairs(gt_dir, ocr_dir) == ([], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pairing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dpi_eval.pairing'`

- [ ] **Step 3: Write minimal implementation**

`src/dpi_eval/pairing.py`:

```python
"""Pair ground-truth files with OCR files by shared stem.

Convention (spec + iiif_ocr): GT is <stem>.gt.txt; OCR is <stem> plus the
first existing extension among .hocr, .xml, .txt.
"""

from pathlib import Path

GT_SUFFIX = ".gt.txt"
OCR_EXTENSIONS = (".hocr", ".xml", ".txt")


def discover_pairs(
    gt_dir: Path, ocr_dir: Path
) -> tuple[list[tuple[Path, Path]], list[str]]:
    pairs: list[tuple[Path, Path]] = []
    missing: list[str] = []
    for gt in sorted(gt_dir.glob(f"*{GT_SUFFIX}")):
        stem = gt.name[: -len(GT_SUFFIX)]
        for ext in OCR_EXTENSIONS:
            candidate = ocr_dir / f"{stem}{ext}"
            if candidate.exists():
                pairs.append((gt, candidate))
                break
        else:
            missing.append(stem)
    return pairs, missing
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pairing.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/pairing.py tests/test_pairing.py
git commit -m "feat: discover GT/OCR pairs by stem convention

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: hOCR adapter

**Model:** `sonnet`

**Files:**
- Create: `src/dpi_eval/adapter.py`
- Create: `tests/fixtures/hocr/page_0.hocr`
- Create: `tests/fixtures/hocr/page_0.gt.txt`
- Test: `tests/test_adapter.py`

**Interfaces:**
- Consumes: nothing from other tasks
- Produces, in `dpi_eval.adapter`:
  - `sniff_format(path: Path) -> str` — returns `"hocr"` or `"passthrough"`
  - `hocr_to_text(path: Path) -> str` — line-per-`ocr_line` plain text, single spaces, trailing newline
  - `normalize_ocr_input(path: Path, workdir: Path) -> Path` — passthrough returns `path` unchanged; hOCR writes `<workdir>/<stem>.txt` and returns it

- [ ] **Step 1: Create hOCR fixture (mirrors iiif_ocr output shape: ocr_page div, ocr_line spans containing ocrx_word spans)**

`tests/fixtures/hocr/page_0.hocr`:

```html
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
 <head>
  <title></title>
  <meta name="ocr-system" content="iiif_ocr test fixture" />
  <meta name="ocr-capabilities" content="ocr_page ocr_line ocrx_word" />
 </head>
 <body>
  <div class="ocr_page" title='image "page_0.jpg"; bbox 0 0 1000 1400'>
   <span class="ocr_line" title="bbox 10 10 600 40">
    <span class="ocrx_word" title="bbox 10 10 90 40">The</span>
    <span class="ocrx_word" title="bbox 100 10 220 40">quick</span>
    <span class="ocrx_word" title="bbox 230 10 380 40">brovvn</span>
    <span class="ocrx_word" title="bbox 390 10 470 40">fox</span>
   </span>
   <span class="ocr_line" title="bbox 10 60 600 90">
    <span class="ocrx_word" title="bbox 10 60 140 90">jumps</span>
    <span class="ocrx_word" title="bbox 150 60 250 90">high.</span>
   </span>
  </div>
 </body>
</html>
```

`tests/fixtures/hocr/page_0.gt.txt`:

```
The quick brown fox
jumps high.
```

- [ ] **Step 2: Write the failing tests**

`tests/test_adapter.py`:

```python
from pathlib import Path

from dpi_eval.adapter import hocr_to_text, normalize_ocr_input, sniff_format

FIXTURES = Path(__file__).parent / "fixtures"
HOCR = FIXTURES / "hocr" / "page_0.hocr"
PLAIN = FIXTURES / "text" / "page_0.txt"


def test_sniff_detects_hocr():
    assert sniff_format(HOCR) == "hocr"


def test_sniff_passes_through_plain_text():
    assert sniff_format(PLAIN) == "passthrough"


def test_sniff_passes_through_alto_xml(tmp_path):
    alto = tmp_path / "page_0.xml"
    alto.write_text(
        '<?xml version="1.0"?><alto xmlns="http://www.loc.gov/standards/alto/ns-v4#"></alto>',
        encoding="utf-8",
    )
    assert sniff_format(alto) == "passthrough"


def test_hocr_to_text_extracts_lines():
    assert hocr_to_text(HOCR) == "The quick brovvn fox\njumps high.\n"


def test_normalize_converts_hocr_to_workdir_txt(tmp_path):
    out = normalize_ocr_input(HOCR, tmp_path)
    assert out == tmp_path / "page_0.txt"
    assert out.read_text(encoding="utf-8") == "The quick brovvn fox\njumps high.\n"


def test_normalize_passthrough_returns_original(tmp_path):
    assert normalize_ocr_input(PLAIN, tmp_path) == PLAIN
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dpi_eval.adapter'`

- [ ] **Step 4: Write minimal implementation**

`src/dpi_eval/adapter.py`:

```python
"""Normalize OCR input for dinglehopper.

dinglehopper auto-detects ALTO/PAGE XML and falls back to plain text, so
everything except hOCR passes through untouched. hOCR (e.g. from iiif_ocr)
is converted to plain text, one line per ocr_line element.

This shim is intentionally deletable: if dinglehopper gains hOCR support
upstream (see docs/findings.md #2), remove this module and pass paths through.
"""

from pathlib import Path

from lxml import html as lxml_html

_SNIFF_BYTES = 4096
_HOCR_MARKERS = (b"ocr_page", b'name="ocr-system"', b"name='ocr-system'")


def sniff_format(path: Path) -> str:
    head = path.open("rb").read(_SNIFF_BYTES)
    if any(marker in head for marker in _HOCR_MARKERS):
        return "hocr"
    return "passthrough"


def hocr_to_text(path: Path) -> str:
    tree = lxml_html.parse(str(path))
    lines = []
    for el in tree.xpath(
        '//*[contains(concat(" ", normalize-space(@class), " "), " ocr_line ")]'
    ):
        text = " ".join(el.text_content().split())
        if text:
            lines.append(text)
    if not lines:  # hOCR without ocr_line markup: fall back to page text
        text = " ".join(tree.getroot().text_content().split())
        if text:
            lines.append(text)
    return "\n".join(lines) + "\n" if lines else ""


def normalize_ocr_input(path: Path, workdir: Path) -> Path:
    if sniff_format(path) != "hocr":
        return path
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / f"{path.stem}.txt"
    out.write_text(hocr_to_text(path), encoding="utf-8")
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_adapter.py -v`
Expected: 6 PASSED

- [ ] **Step 6: Commit**

```bash
git add src/dpi_eval/adapter.py tests/fixtures/hocr/ tests/test_adapter.py
git commit -m "feat: hOCR input adapter (sniff + convert to plain text)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Batch runner with skip-and-log + failure threshold

**Model:** `sonnet`

**Files:**
- Modify: `src/dpi_eval/runner.py` (append; keep `run_page` and `summarize` unchanged)
- Test: `tests/test_batch.py`

**Interfaces:**
- Consumes: `discover_pairs` (Task 2), `normalize_ocr_input` (Task 3), `run_page`/`summarize` (Task 1)
- Produces, in `dpi_eval.runner`:
  - `@dataclass BatchResult` with fields `succeeded: list[str]`, `failed: list[str]`, `missing: list[str]`, `summary: Path | None`
  - `run_batch(gt_dir: Path, ocr_dir: Path, reports_dir: Path, max_failure_rate: float = 0.2) -> tuple[BatchResult, int]` — second element is the process exit code (0 ok, 1 over threshold or nothing to grade). Failures and missing stems are logged via `logging.getLogger("dpi_eval")` and never raise.

- [ ] **Step 1: Write the failing tests**

`tests/test_batch.py`:

```python
import json
from pathlib import Path

from dpi_eval.runner import run_batch

FIXTURES = Path(__file__).parent / "fixtures"


def _setup_batch(tmp_path, *, corrupt_page_1=False, orphan_gt=False):
    """Two-page batch from the text fixtures; optional broken/missing pages."""
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    gt = (FIXTURES / "text" / "page_0.gt.txt").read_text(encoding="utf-8")
    ocr = (FIXTURES / "text" / "page_0.txt").read_text(encoding="utf-8")
    for i in (0, 1):
        (gt_dir / f"page_{i}.gt.txt").write_text(gt, encoding="utf-8")
        (ocr_dir / f"page_{i}.txt").write_text(ocr, encoding="utf-8")
    if corrupt_page_1:
        # Point page_1's OCR at a nonexistent file by deleting it after pairing
        # is impossible — instead make it a directory, which dinglehopper
        # cannot read, forcing a per-page failure.
        (ocr_dir / "page_1.txt").unlink()
        (ocr_dir / "page_1.txt").mkdir()
    if orphan_gt:
        (gt_dir / "page_9.gt.txt").write_text(gt, encoding="utf-8")
    return gt_dir, ocr_dir


def test_clean_batch_grades_all_pages_exit_zero(tmp_path):
    gt_dir, ocr_dir = _setup_batch(tmp_path)
    reports = tmp_path / "reports"
    result, code = run_batch(gt_dir, ocr_dir, reports)
    assert code == 0
    assert result.succeeded == ["page_0", "page_1"]
    assert result.failed == []
    assert result.summary == reports / "summary.json"
    assert json.loads(result.summary.read_text(encoding="utf-8"))
    assert (reports / "page_0.json").exists()
    assert (reports / "page_1.json").exists()


def test_failures_over_threshold_exit_nonzero(tmp_path):
    gt_dir, ocr_dir = _setup_batch(tmp_path, corrupt_page_1=True)
    result, code = run_batch(gt_dir, ocr_dir, tmp_path / "reports", max_failure_rate=0.2)
    assert result.failed == ["page_1"]
    assert result.succeeded == ["page_0"]
    assert code == 1  # 1/2 = 0.5 > 0.2


def test_failures_under_threshold_exit_zero_but_logged(tmp_path, caplog):
    gt_dir, ocr_dir = _setup_batch(tmp_path, corrupt_page_1=True)
    with caplog.at_level("WARNING", logger="dpi_eval"):
        result, code = run_batch(
            gt_dir, ocr_dir, tmp_path / "reports", max_failure_rate=0.6
        )
    assert code == 0
    assert result.failed == ["page_1"]
    assert any("page_1" in r.message for r in caplog.records)


def test_missing_ocr_is_reported_not_fatal(tmp_path):
    gt_dir, ocr_dir = _setup_batch(tmp_path, orphan_gt=True)
    result, code = run_batch(gt_dir, ocr_dir, tmp_path / "reports")
    assert code == 0
    assert result.missing == ["page_9"]


def test_empty_batch_exits_nonzero(tmp_path):
    (tmp_path / "gt").mkdir()
    (tmp_path / "ocr").mkdir()
    result, code = run_batch(tmp_path / "gt", tmp_path / "ocr", tmp_path / "reports")
    assert code == 1
    assert result.succeeded == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_batch.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_batch'`

- [ ] **Step 3: Implement run_batch**

Append to `src/dpi_eval/runner.py`:

```python
import logging
from dataclasses import dataclass, field

from dpi_eval.adapter import normalize_ocr_input
from dpi_eval.pairing import discover_pairs

logger = logging.getLogger("dpi_eval")


@dataclass
class BatchResult:
    succeeded: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    summary: Path | None = None


def run_batch(
    gt_dir: Path,
    ocr_dir: Path,
    reports_dir: Path,
    max_failure_rate: float = 0.2,
) -> tuple[BatchResult, int]:
    result = BatchResult()
    pairs, result.missing = discover_pairs(gt_dir, ocr_dir)
    for stem in result.missing:
        logger.warning("no OCR file found for GT stem %r — skipping", stem)
    if not pairs:
        logger.error("nothing to grade: no GT/OCR pairs in %s / %s", gt_dir, ocr_dir)
        return result, 1

    workdir = reports_dir / "_normalized"
    for gt, ocr in pairs:
        stem = gt.name[: -len(".gt.txt")]
        try:
            normalized = normalize_ocr_input(ocr, workdir)
            run_page(gt, normalized, reports_dir, prefix=stem)
            result.succeeded.append(stem)
        except Exception as exc:  # skip-and-log per spec; batch verdict below
            logger.warning("page %r failed: %s", stem, exc)
            result.failed.append(stem)

    if result.succeeded:
        result.summary = summarize(reports_dir)

    failure_rate = len(result.failed) / len(pairs)
    if failure_rate > max_failure_rate:
        logger.error(
            "failure rate %.0f%% exceeds threshold %.0f%%",
            failure_rate * 100,
            max_failure_rate * 100,
        )
        return result, 1
    return result, 0
```

Note: `from pathlib import Path` is already imported at the top of `runner.py` from Task 1 — do not duplicate it. Place the new imports alongside the existing ones.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch.py -v`
Expected: 5 PASSED. Also run the full suite: `uv run pytest -v` — all tests from Tasks 1–3 must still pass. Note: `summarize()` may include `_normalized/` noise or fail on non-report files; if `test_clean_batch_grades_all_pages_exit_zero` fails on summary content, move `workdir` outside `reports_dir` (`reports_dir.parent / "_normalized"`) and update the test's expectations accordingly — the JSON reports folder must contain only reports.

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/runner.py tests/test_batch.py
git commit -m "feat: batch runner with skip-and-log and failure threshold

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: CLI entry point + hOCR end-to-end

**Model:** `sonnet`

**Files:**
- Create: `src/dpi_eval/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_batch` (Task 4)
- Produces: console script `dpi-eval GT_DIR OCR_DIR REPORTS_DIR [--max-failure-rate 0.2]` → exit code from `run_batch`; `main(argv: list[str] | None = None) -> int` in `dpi_eval.cli` (already wired in `pyproject.toml` from Task 1)

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
import json
import shutil
from pathlib import Path

from dpi_eval.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_grades_hocr_end_to_end(tmp_path):
    """The full amended-spec data flow: hOCR in, summary.json out."""
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    reports = tmp_path / "reports"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    shutil.copy(FIXTURES / "hocr" / "page_0.gt.txt", gt_dir / "page_0.gt.txt")
    shutil.copy(FIXTURES / "hocr" / "page_0.hocr", ocr_dir / "page_0.hocr")

    code = main([str(gt_dir), str(ocr_dir), str(reports)])
    assert code == 0
    report = json.loads((reports / "page_0.json").read_text(encoding="utf-8"))
    # fixture has exactly one error: brovvn vs brown
    assert 0 < report["cer"] < 0.2
    assert json.loads((reports / "summary.json").read_text(encoding="utf-8"))


def test_cli_exit_code_propagates_for_empty_batch(tmp_path):
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    assert main([str(gt_dir), str(ocr_dir), str(tmp_path / "reports")]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dpi_eval.cli'`

- [ ] **Step 3: Implement CLI**

`src/dpi_eval/cli.py`:

```python
"""dpi-eval: grade a directory of OCR output against ground-truth samples."""

import argparse
import logging
import sys
from pathlib import Path

from dpi_eval.runner import run_batch


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="dpi-eval",
        description=(
            "Grade OCR output (ALTO/PAGE/text/hOCR) against plain-text ground "
            "truth using dinglehopper. GT files are <stem>.gt.txt; OCR files "
            "share the stem with extension .hocr, .xml, or .txt."
        ),
    )
    parser.add_argument("gt_dir", type=Path, help="directory of <stem>.gt.txt files")
    parser.add_argument("ocr_dir", type=Path, help="directory of OCR output files")
    parser.add_argument("reports_dir", type=Path, help="output directory for reports")
    parser.add_argument(
        "--max-failure-rate",
        type=float,
        default=0.2,
        help="fail the batch when this fraction of pages errors (default 0.2)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result, code = run_batch(
        args.gt_dir, args.ocr_dir, args.reports_dir, args.max_failure_rate
    )
    print(
        f"graded {len(result.succeeded)} page(s), "
        f"{len(result.failed)} failed, {len(result.missing)} missing OCR"
    )
    if result.summary:
        print(f"summary: {result.summary}")
    return code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Verify the installed console script works**

Run: `uv run dpi-eval --help`
Expected: usage text printed, exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/dpi_eval/cli.py tests/test_cli.py
git commit -m "feat: dpi-eval CLI — hOCR-to-summary end-to-end

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: ALTO passthrough integration test

**Model:** `haiku`

**Files:**
- Create: `tests/fixtures/alto/page_0.xml`
- Create: `tests/fixtures/alto/page_0.gt.txt`
- Test: `tests/test_alto_passthrough.py`

**Interfaces:**
- Consumes: `main` (Task 5)
- Produces: regression coverage that ALTO input reaches dinglehopper *unconverted* (spec: passthrough formats untouched)

- [ ] **Step 1: Create ALTO fixture**

`tests/fixtures/alto/page_0.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
  <Description>
    <MeasurementUnit>pixel</MeasurementUnit>
  </Description>
  <Layout>
    <Page ID="page_0" WIDTH="1000" HEIGHT="1400" PHYSICAL_IMG_NR="1">
      <PrintSpace HPOS="0" VPOS="0" WIDTH="1000" HEIGHT="1400">
        <TextBlock ID="block_1" HPOS="10" VPOS="10" WIDTH="600" HEIGHT="80">
          <TextLine ID="line_1" HPOS="10" VPOS="10" WIDTH="600" HEIGHT="30">
            <String CONTENT="The" HPOS="10" VPOS="10" WIDTH="80" HEIGHT="30"/>
            <SP WIDTH="10" VPOS="10" HPOS="90"/>
            <String CONTENT="quick" HPOS="100" VPOS="10" WIDTH="120" HEIGHT="30"/>
            <SP WIDTH="10" VPOS="10" HPOS="220"/>
            <String CONTENT="brovvn" HPOS="230" VPOS="10" WIDTH="150" HEIGHT="30"/>
            <SP WIDTH="10" VPOS="10" HPOS="380"/>
            <String CONTENT="fox" HPOS="390" VPOS="10" WIDTH="80" HEIGHT="30"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
```

`tests/fixtures/alto/page_0.gt.txt`:

```
The quick brown fox
```

- [ ] **Step 2: Write the test**

`tests/test_alto_passthrough.py`:

```python
import json
import shutil
from pathlib import Path

from dpi_eval.adapter import sniff_format
from dpi_eval.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_alto_is_not_converted():
    assert sniff_format(FIXTURES / "alto" / "page_0.xml") == "passthrough"


def test_cli_grades_alto_end_to_end(tmp_path):
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    reports = tmp_path / "reports"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    shutil.copy(FIXTURES / "alto" / "page_0.gt.txt", gt_dir / "page_0.gt.txt")
    shutil.copy(FIXTURES / "alto" / "page_0.xml", ocr_dir / "page_0.xml")

    code = main([str(gt_dir), str(ocr_dir), str(reports)])
    assert code == 0
    report = json.loads((reports / "page_0.json").read_text(encoding="utf-8"))
    assert 0 < report["cer"] < 0.5
```

- [ ] **Step 3: Run the test**

Run: `uv run pytest tests/test_alto_passthrough.py -v`
Expected: 2 PASSED. If dinglehopper rejects the ALTO namespace (`ns-v3#`), check which namespaces it accepts with `uv run python -c "import dinglehopper.ocr_files, inspect; print(inspect.getsource(dinglehopper.ocr_files.alto_namespace))"` and adjust the fixture's `xmlns` to a supported version — the fixture bends to reality, never the reverse. (Reading dinglehopper source to learn its contract is fine; importing it in shipped code is not.)

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -v`
Expected: all tests pass (tracer 2, pairing 3, adapter 6, batch 5, cli 2, alto 2 = 20).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/alto/ tests/test_alto_passthrough.py
git commit -m "test: ALTO passthrough integration coverage

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: README + demo runbook

**Model:** `haiku`

**Files:**
- Modify: `README.md` (replace uv-init stub entirely)

**Interfaces:**
- Consumes: CLI contract from Task 5 (`dpi-eval GT_DIR OCR_DIR REPORTS_DIR [--max-failure-rate]`)
- Produces: instructions a colleague can follow unaided

- [ ] **Step 1: Write README**

Replace `README.md` with:

```markdown
# dpi-dinglehopper-eval

DPI glue around [dinglehopper](https://github.com/qurator-spk/dinglehopper)
(unmodified dependency — we do not fork) to grade OCR output against
ground-truth samples and emit machine-readable quality metrics.

## Setup

    uv sync

## Usage

    uv run dpi-eval GT_DIR OCR_DIR REPORTS_DIR [--max-failure-rate 0.2]

- `GT_DIR` — plain-text ground truth, one file per page, named `<stem>.gt.txt`
- `OCR_DIR` — OCR output sharing the stem: `<stem>.hocr` (e.g. from
  [iiif_ocr](https://github.com/aguilarm-umd/iiif_ocr)), `<stem>.xml`
  (ALTO/PAGE), or `<stem>.txt`. hOCR is converted internally; everything
  else goes to dinglehopper untouched.
- `REPORTS_DIR` — receives per-page `<stem>.json` / `<stem>.html` and
  batch-level `summary.json` / `summary.html`.

Exit code is non-zero when more than `--max-failure-rate` of pages fail
or when there is nothing to grade. Pages with no matching OCR file are
logged and skipped.

## Demo runbook (iiif_ocr path)

1. Run your manifest through iiif_ocr:
   `iiif_ocr https://example.org/manifest.json`
   → hOCR lands in `downloads/<manifest-uuid>/page_{i}.hocr`
2. Pick 10–20 pages; transcribe each carefully into `gt/page_{i}.gt.txt`
   (plain text, one file per sampled page — match the stem exactly).
3. Grade: `uv run dpi-eval gt/ downloads/<manifest-uuid>/ reports/`
4. Read `reports/summary.json` (machine) or `reports/summary.html` (human);
   per-page visual diffs are in `reports/page_{i}.html`.

## Project docs

- Design spec: `docs/superpowers/specs/2026-07-16-dpi-ocr-eval-demo-design.md`
- Findings log (upstream-PR candidates, deferred ideas): `docs/findings.md`
```

- [ ] **Step 2: Verify instructions against reality**

Run: `uv run dpi-eval --help`
Expected: flags and argument names in the README match the help output exactly.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README with usage and iiif_ocr demo runbook

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Spec-compliance review + findings synthesis

**Model:** `fable` (orchestrator — judgment task, no code generation)

**Files:**
- Modify: `docs/findings.md` (only if review surfaces new findings)

**Interfaces:**
- Consumes: the full diff of Tasks 1–7 and the spec at `docs/superpowers/specs/2026-07-16-dpi-ocr-eval-demo-design.md`

- [ ] **Step 1: Verify every spec success criterion has a passing test or artifact**

Checklist against the spec's "Testing / success criteria":
- smoke-tested against fixtures before real data → full pytest suite green (`uv run pytest -v`)
- `summary.json` parses → asserted in `test_tracer.py`, `test_cli.py`, `test_batch.py`
- swappable input (amended fence) → hOCR e2e (`test_cli.py`) + ALTO passthrough (`test_alto_passthrough.py`)
- skip-and-log + loud batch failure → `test_batch.py`
- dinglehopper unmodified → `git diff` touches no vendored code; `pyproject.toml` pins it as a plain dependency; `grep -rn "from dinglehopper" src/` returns nothing

- [ ] **Step 2: Review scope-fence adherence**

Confirm nothing crept in: no new metrics, no custom report schema, no PDF handling, no viewer overlay. If anything did, remove it or move it to `docs/findings.md` as a triaged entry.

- [ ] **Step 3: Update findings note if the implementation taught anything**

Typical candidates: dinglehopper CLI quirks discovered via subprocess, `summarize()` behavior with non-report files in the folder, hOCR variations the adapter should tolerate. Each entry follows the existing "upstream-PR candidate vs. wrapper work" triage format.

- [ ] **Step 4: Commit (if findings changed) and report**

```bash
git add docs/findings.md
git commit -m "docs: post-implementation findings

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Report to Trevor: suite status, spec-compliance verdict, and what remains human work — selecting the real manifest/batch and transcribing the GT sample (spec's "open questions").

---

## What this plan deliberately does not include

Real-data demo execution (choosing the manifest, hand-transcribing GT) is human
work gated on data access — the runbook in Task 7 covers it. hOCR→IIIF-annotation
viewer overlay stays deferred (findings #3). Upstream PRs (findings #1, #2) are
post-sprint.
