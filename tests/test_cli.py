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
