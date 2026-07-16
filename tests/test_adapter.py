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
