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


# --- PAR C3: ocrx_line engines fell through to whole-document text ---------


def _hocr(body: str, head: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        '<title>page_0.tif</title>'
        '<meta name="ocr-system" content="test"/>'
        f'{head}</head><body>{body}</body></html>'
    )


def test_hocr_to_text_extracts_ocrx_line(tmp_path):
    """kraken, OCRopus and several ABBYY converters emit ocrx_line. These
    matched no line selector, so the whole document — <title>, <style> and
    all — was collapsed onto one line and graded as OCR output."""
    path = tmp_path / "p.hocr"
    path.write_text(_hocr(
        '<div class="ocr_page">'
        '<span class="ocrx_line">Hello world</span>'
        '<span class="ocrx_line">Second line here</span>'
        '</div>'), encoding="utf-8")
    assert hocr_to_text(path) == "Hello world\nSecond line here\n"


def test_hocr_to_text_keeps_both_line_classes(tmp_path):
    """Mixed documents took the normal path, so every ocrx_line was silently
    dropped and counted against the OCR as a deletion."""
    path = tmp_path / "p.hocr"
    path.write_text(_hocr(
        '<div class="ocr_page">'
        '<span class="ocr_line">First line</span>'
        '<span class="ocrx_line">Second line</span>'
        '</div>'), encoding="utf-8")
    assert hocr_to_text(path) == "First line\nSecond line\n"


def test_hocr_to_text_fallback_never_grades_head_or_style(tmp_path):
    """The fallback used getroot().text_content(), which includes <title>
    and <style>. Graded against line-for-line ground truth that is not an
    approximation — it is noise scored as though it were a transcription."""
    path = tmp_path / "p.hocr"
    path.write_text(_hocr(
        '<div class="ocr_page"><p>Body text only</p></div>',
        head='<style>.ocr_line{color:red}</style>'), encoding="utf-8")
    out = hocr_to_text(path)
    assert "page_0.tif" not in out
    assert "color:red" not in out
    assert "Body text only" in out
