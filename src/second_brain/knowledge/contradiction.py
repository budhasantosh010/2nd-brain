"""Conservative deterministic contradiction candidate detection."""

from __future__ import annotations

import re

NEGATION = re.compile(r"\b(no|not|never|without|cannot|can't|won't|doesn't|isn't|aren't)\b", re.I)


def contradiction_candidate(left: str, right: str) -> bool:
    """Return only a candidate signal; semantic conflict still requires evidence review."""
    left_words = {word.lower() for word in re.findall(r"[A-Za-z0-9]+", left) if len(word) > 3}
    right_words = {word.lower() for word in re.findall(r"[A-Za-z0-9]+", right) if len(word) > 3}
    if not left_words or not right_words:
        return False
    overlap = len(left_words & right_words) / min(len(left_words), len(right_words))
    return overlap >= 0.6 and bool(NEGATION.search(left)) != bool(NEGATION.search(right))
