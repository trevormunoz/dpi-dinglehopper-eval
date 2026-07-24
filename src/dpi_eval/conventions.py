"""Transcription conventions, applied at save time.

Cornerstone (spec, Trevor 2026-07-24): transcription is LINE-FOR-LINE —
students press Enter at each printed line end, so interior newlines are
data and are never stripped. Rules here normalize within lines only.

Bump CONVENTIONS_VERSION whenever any rule changes; sessions stamped
with a different version become read-only (sessions.py enforces this).
Remaining conventions content (hyphenation, ligatures, long s) is spec
open decision #1 and lands here as new rules + a version bump.
"""

import unicodedata

CONVENTIONS_VERSION = "1"


def normalize(text: str) -> tuple[str, int]:
    """Apply conventions v1. Returns (normalized_text, change_count) where
    change_count is the number of rules that altered the text (not the
    number of characters changed) — surfaced to the student as
    "N changes applied by conventions v1"."""
    changes = 0

    crlf_fixed = text.replace("\r\n", "\n").replace("\r", "\n")
    if crlf_fixed != text:
        changes += 1
    text = crlf_fixed

    nfc = unicodedata.normalize("NFC", text)
    if nfc != text:
        changes += 1
    text = nfc

    stripped = "\n".join(line.rstrip() for line in text.split("\n"))
    if stripped != text:
        changes += 1
    text = stripped

    if text and not text.endswith("\n"):
        text += "\n"
        changes += 1
    elif text.endswith("\n\n"):
        while text.endswith("\n\n"):
            text = text[:-1]
        changes += 1

    return text, changes
