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
