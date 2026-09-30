"""Deterministic checks for whether extracted text is real text.

Scanned PDFs often carry a junk text layer (empty, `(cid:NN)` glyph codes,
or mojibake). Those pages must be OCRed instead of trusted.
"""

from __future__ import annotations

import re
import unicodedata

_CID = re.compile(r"\(cid:\d+\)")
MIN_CHARS = 20


def text_score(text: str) -> float:
    """0.0 (garbage) .. 1.0 (clean): share of non-space characters that are
    letters, digits or ordinary punctuation."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    good = 0
    for c in chars:
        cat = unicodedata.category(c)
        if c == "�" or cat.startswith("C"):
            continue
        if cat[0] in "LNP" or cat in ("Sm", "Sc"):
            good += 1
    return good / len(chars)


def is_usable(text: str, min_chars: int = MIN_CHARS, min_score: float = 0.85) -> bool:
    stripped = _CID.sub("", text)
    if len(_CID.findall(text)) > 5:
        return False
    if sum(1 for c in stripped if c.isalnum()) < min_chars:
        return False
    return text_score(stripped) >= min_score
