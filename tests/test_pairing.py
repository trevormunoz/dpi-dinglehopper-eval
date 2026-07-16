from pathlib import Path

from dpi_eval.pairing import discover_pairs


def make(p: Path, name: str) -> Path:
    f = p / name
    f.write_text("x", encoding="utf-8")
    return f


def test_pairs_by_stem_across_extensions(tmp_path):
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    g0 = make(gt_dir, "page_0.gt.txt")
    g1 = make(gt_dir, "page_1.gt.txt")
    g2 = make(gt_dir, "page_2.gt.txt")
    o0 = make(ocr_dir, "page_0.hocr")
    o1 = make(ocr_dir, "page_1.xml")
    # page_2 has no OCR file; stray file must be ignored
    make(ocr_dir, "notes.md")

    pairs, missing = discover_pairs(gt_dir, ocr_dir)
    assert pairs == [(g0, o0), (g1, o1)]
    assert missing == ["page_2"]


def test_hocr_preferred_over_txt_for_same_stem(tmp_path):
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    make(gt_dir, "page_0.gt.txt")
    hocr = make(ocr_dir, "page_0.hocr")
    make(ocr_dir, "page_0.txt")

    pairs, missing = discover_pairs(gt_dir, ocr_dir)
    assert pairs[0][1] == hocr
    assert missing == []


def test_empty_dirs_yield_nothing(tmp_path):
    gt_dir = tmp_path / "gt"
    ocr_dir = tmp_path / "ocr"
    gt_dir.mkdir()
    ocr_dir.mkdir()
    assert discover_pairs(gt_dir, ocr_dir) == ([], [])
