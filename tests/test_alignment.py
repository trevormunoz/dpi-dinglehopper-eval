from dpi_eval.alignment import align, trailing_int


def _pages(indices):
    return [{"stem": f"p{i:04d}-label", "source_index": i} for i in indices]


def test_trailing_int():
    assert trailing_int("page_0") == 0
    assert trailing_int("page_11") == 11
    assert trailing_int("0042_scan") is None
    assert trailing_int("cover") is None


def test_index_alignment_is_zero_based_no_off_by_one():
    """Regression pin (PAR round 2): iiif_ocr writes page_0.hocr for the
    FIRST canvas. p0000-* must pair page_0.hocr, never page_1.hocr."""
    files = [f"page_{i}.hocr" for i in range(12)]
    result = align(_pages(range(12)), files, by="index")
    assert result["matched"]["p0000-label"] == "page_0.hocr"
    assert result["matched"]["p0007-label"] == "page_7.hocr"
    assert result["unmatched_pages"] == []
    assert result["unmatched_files"] == []


def test_index_alignment_reports_unmatched_both_sides():
    result = align(_pages([0, 1]), ["page_0.hocr", "vendor-scan-A.hocr"], by="index")
    assert result["matched"] == {"p0000-label": "page_0.hocr"}
    assert result["unmatched_pages"] == ["p0001-label"]
    assert result["unmatched_files"] == ["vendor-scan-A.hocr"]


def test_non_ocr_files_are_ignored_not_reported():
    """iiif_ocr leaves page_N.jpeg / page_N_scaled.jpeg beside its hOCR."""
    result = align(_pages([0]), ["page_0.hocr", "page_0.jpeg", "notes.md"], by="index")
    assert result["matched"] == {"p0000-label": "page_0.hocr"}
    assert result["ignored"] == ["notes.md", "page_0.jpeg"]
    assert result["unmatched_files"] == []


def test_stem_alignment_for_local_sessions():
    pages = [{"stem": "scan-A", "source_index": 0}, {"stem": "scan-B", "source_index": 1}]
    result = align(pages, ["scan-A.xml", "other.txt"], by="stem")
    assert result["matched"] == {"scan-A": "scan-A.xml"}
    assert result["unmatched_pages"] == ["scan-B"]
    assert result["unmatched_files"] == ["other.txt"]
