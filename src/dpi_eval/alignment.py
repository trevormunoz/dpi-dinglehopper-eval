"""Map OCR (or draft) files to session pages.

IIIF sessions align by canvas index — source_index is 0-based over all
canvases, matching iiif_ocr's page_{i} naming exactly (spec-pinned; see
the off-by-one regression test). Local sessions align by stem equality.
Auto-alignment is a convenience; the editable preview is the contract —
callers overlay manual overrides on the returned mapping.
"""

import re
from pathlib import Path

# Recognized OCR extensions, mapped to the suffixes pairing.discover_pairs
# accepts. Anything else is ignored (not an error): iiif_ocr leaves
# page_N.jpeg images beside its hOCR output.
OCR_STAGE_EXTENSIONS = {".hocr": ".hocr", ".xml": ".xml", ".txt": ".txt"}

_TRAILING_INT = re.compile(r"(\d+)$")


def trailing_int(stem: str) -> int | None:
    match = _TRAILING_INT.search(stem)
    return int(match.group(1)) if match else None


def align(pages: list[dict], filenames: list[str], by: str) -> dict:
    ocr_files = []
    ignored = []
    for name in sorted(filenames):
        if Path(name).suffix.lower() in OCR_STAGE_EXTENSIONS:
            ocr_files.append(name)
        else:
            ignored.append(name)

    matched: dict[str, str] = {}
    used: set[str] = set()
    for page in pages:
        candidate = None
        if by == "index":
            for name in ocr_files:
                if trailing_int(Path(name).stem) == page["source_index"]:
                    candidate = name
                    break
        else:
            for name in ocr_files:
                if Path(name).stem == page["stem"]:
                    candidate = name
                    break
        if candidate and candidate not in used:
            matched[page["stem"]] = candidate
            used.add(candidate)

    return {
        "matched": matched,
        "unmatched_pages": [p["stem"] for p in pages if p["stem"] not in matched],
        "unmatched_files": [n for n in ocr_files if n not in used],
        "ignored": ignored,
    }
