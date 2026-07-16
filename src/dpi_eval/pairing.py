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
