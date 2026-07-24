from dpi_eval.conventions import CONVENTIONS_VERSION, normalize


def test_version_is_stringy_and_stable():
    assert CONVENTIONS_VERSION == "1"


def test_preserves_interior_newlines_line_for_line():
    text = "First line\nSecond line\n"
    out, changes = normalize(text)
    assert out == "First line\nSecond line\n"
    assert changes == 0


def test_crlf_becomes_lf_and_counts_as_change():
    out, changes = normalize("a\r\nb\r\n")
    assert out == "a\nb\n"
    assert changes == 1


def test_strips_trailing_spaces_per_line():
    out, changes = normalize("word   \nnext\n")
    assert out == "word\nnext\n"
    assert changes == 1


def test_nfc_normalization():
    decomposed = "e\u0301tude\n"  # e + combining acute
    out, changes = normalize(decomposed)
    assert out == "étude\n"
    assert changes == 1


def test_ensures_single_trailing_newline():
    out, changes = normalize("last line")
    assert out == "last line\n"
    assert changes == 1


def test_multiple_trailing_newlines_count_as_one_change():
    out, changes = normalize("last line\n\n\n")
    assert out == "last line\n"
    assert changes == 1
