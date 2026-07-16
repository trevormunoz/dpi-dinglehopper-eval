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
