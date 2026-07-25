"""Normalize OCR input for dinglehopper.

dinglehopper auto-detects ALTO/PAGE XML and falls back to plain text, so
everything except hOCR passes through untouched. hOCR (e.g. from iiif_ocr)
is converted to plain text, one line per ocr_line element.

Deletability contract (amended 2026-07-24): if dinglehopper gains hOCR
support upstream (docs/findings.md #2), the grading path can pass
through — BUT sessions.py now also consumes hocr_to_text/sniff_format
for correction-draft prefill, which needs actual text, not a path
dinglehopper can parse. Deleting this module requires replacing that
consumer too.
"""

from pathlib import Path

from lxml import html as lxml_html

_SNIFF_BYTES = 4096
_HOCR_MARKERS = (b"ocr_page", b'name="ocr-system"', b"name='ocr-system'")


def sniff_format(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(_SNIFF_BYTES)
    if any(marker in head for marker in _HOCR_MARKERS):
        return "hocr"
    return "passthrough"


def _has_class(name: str) -> str:
    return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'


# hOCR spec: ocr_line is the typographic line; ocrx_line is the engine-level
# line emitted by kraken, OCRopus and several ABBYY converters. Matching only
# ocr_line sent those engines down the fallback below, and silently dropped
# every ocrx_line in a mixed document (counting them as OCR deletions).
_LINE_CLASSES = ("ocr_line", "ocrx_line")


def hocr_to_text(path: Path) -> str:
    tree = lxml_html.parse(str(path))
    lines = []
    predicate = " or ".join(_has_class(name) for name in _LINE_CLASSES)
    for el in tree.xpath(f"//*[{predicate}]"):
        text = " ".join(el.text_content().split())
        if text:
            lines.append(text)
    if not lines:
        # hOCR without any line markup. This used to take
        # getroot().text_content(), which swept in <title> and <style> — page
        # furniture graded as though it were a transcription. Body text only,
        # with script/style excluded.
        parts = tree.xpath(
            "//body//text()[not(ancestor::script) and not(ancestor::style)]")
        text = " ".join(" ".join(parts).split())
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
