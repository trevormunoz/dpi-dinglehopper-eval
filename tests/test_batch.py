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


def test_hocr_batch_creates_normalized_dir_and_summary_still_works(tmp_path):
    """hOCR input forces _normalized/ inside reports_dir before summarize runs."""
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    gt = (FIXTURES / "hocr" / "page_0.gt.txt").read_text(encoding="utf-8")
    hocr = (FIXTURES / "hocr" / "page_0.hocr").read_text(encoding="utf-8")
    (gt_dir / "page_0.gt.txt").write_text(gt, encoding="utf-8")
    (ocr_dir / "page_0.hocr").write_text(hocr, encoding="utf-8")
    reports = tmp_path / "reports"
    result, code = run_batch(gt_dir, ocr_dir, reports)
    assert code == 0
    # Proves the scenario is actually exercised: normalization wrote into
    # reports_dir / "_normalized" and summarize still succeeded around it.
    assert (reports / "_normalized" / "page_0.txt").exists()
    assert json.loads((reports / "page_0.json").read_text(encoding="utf-8"))
    assert json.loads(result.summary.read_text(encoding="utf-8"))


def test_stale_reports_cleared_before_rerun(tmp_path):
    """Re-running into a populated reports_dir must not poison summary.json
    with stale per-page reports from a prior run."""
    gt_dir, ocr_dir = _setup_batch(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "page_9.json").write_text(json.dumps({"cer": 0.9}), encoding="utf-8")
    (reports / "summary.json").write_text(json.dumps({"num_reports": 99}), encoding="utf-8")

    result, code = run_batch(gt_dir, ocr_dir, reports)

    assert code == 0
    assert not (reports / "page_9.json").exists()
    summary = json.loads(result.summary.read_text(encoding="utf-8"))
    assert summary["num_reports"] == 2


def test_empty_batch_exits_nonzero(tmp_path):
    (tmp_path / "gt").mkdir()
    (tmp_path / "ocr").mkdir()
    result, code = run_batch(tmp_path / "gt", tmp_path / "ocr", tmp_path / "reports")
    assert code == 1
    assert result.succeeded == []
