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
