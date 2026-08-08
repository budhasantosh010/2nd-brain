"""Conservative contradiction/supersession candidate intelligence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from second_brain.embeddings.base import EmbeddingProvider
from second_brain.embeddings.local import cosine

NEGATION = re.compile(r"\b(no|not|never|without|cannot|can't|won't|doesn't|isn't|aren't)\b", re.I)
UNIVERSAL = re.compile(r"\b(all|every|always|any source|for everyone)\b", re.I)
RESTRICTIVE = re.compile(r"\b(only|explicitly approved|approved sources?|restricted to|unless approved)\b", re.I)
TRANSITION = re.compile(
    r"\b(now|currently|changed|moved|postponed|delayed|replaced|increased|decreased|raised|lowered|from|to)\b",
    re.I,
)
DATE = re.compile(
    r"\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s*20\d{2})?)\b",
    re.I,
)
MONEY_OR_PERCENT = re.compile(r"(?:\$\s?\d[\d,.]*|\b\d+(?:\.\d+)?\s?%)")
WORD = re.compile(r"[A-Za-z0-9]+")


class ConflictKind(StrEnum):
    NONE = "none"
    CONFLICT = "conflict"
    SUPERSESSION = "supersession"


@dataclass(frozen=True, slots=True)
class ContradictionAssessment:
    kind: ConflictKind
    score: float
    reason: str


def _words(value: str) -> set[str]:
    return {word.lower() for word in WORD.findall(value) if len(word) > 3}


def lexical_overlap(left: str, right: str) -> float:
    a = _words(left)
    b = _words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def semantic_similarity(
    left: str,
    right: str,
    provider: EmbeddingProvider | None,
) -> float:
    if provider is None or not provider.metadata.learned:
        return 0.0
    vectors = provider.embed_batch([left, right])
    if len(vectors) != 2:
        return 0.0
    return cosine(vectors[0], vectors[1])


def assess_claim_pair(
    left: str,
    right: str,
    *,
    provider: EmbeddingProvider | None = None,
) -> ContradictionAssessment:
    """Classify only a candidate relationship; evidence verification still decides truth."""

    overlap = lexical_overlap(left, right)
    semantic = semantic_similarity(left, right, provider)
    topic_score = max(overlap, semantic)
    if topic_score < 0.52:
        return ContradictionAssessment(ConflictKind.NONE, topic_score, "Statements are not close enough in topic.")

    left_dates = set(DATE.findall(left))
    right_dates = set(DATE.findall(right))
    left_values = set(MONEY_OR_PERCENT.findall(left))
    right_values = set(MONEY_OR_PERCENT.findall(right))
    different_temporal_value = (
        bool(left_dates and right_dates and left_dates != right_dates)
        or bool(left_values and right_values and left_values != right_values)
    )
    if different_temporal_value and (TRANSITION.search(left) or TRANSITION.search(right)):
        return ContradictionAssessment(
            ConflictKind.SUPERSESSION,
            topic_score,
            "Same topic with an explicit changed/moved value; preserve historical truth as superseded rather than contradictory.",
        )

    opposite_negation = bool(NEGATION.search(left)) != bool(NEGATION.search(right))
    universal_vs_restricted = (
        bool(UNIVERSAL.search(left)) and bool(RESTRICTIVE.search(right))
    ) or (bool(UNIVERSAL.search(right)) and bool(RESTRICTIVE.search(left)))
    incompatible_values = different_temporal_value and not (
        TRANSITION.search(left) or TRANSITION.search(right)
    )
    if opposite_negation or universal_vs_restricted or incompatible_values:
        reason = (
            "Opposite negation on the same topic."
            if opposite_negation
            else "Universal permission conflicts with a restrictive/approval-only statement."
            if universal_vs_restricted
            else "Same topic contains incompatible explicit values without a temporal transition."
        )
        return ContradictionAssessment(ConflictKind.CONFLICT, topic_score, reason)

    return ContradictionAssessment(
        ConflictKind.NONE,
        topic_score,
        "Semantically related evidence without a verified contradiction signal.",
    )


def contradiction_candidate(left: str, right: str) -> bool:
    """Phase 1/2 compatibility helper for deterministic conflict candidates."""
    return assess_claim_pair(left, right).kind == ConflictKind.CONFLICT
