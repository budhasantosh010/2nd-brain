"""Deterministic concept matching before any merge/update decision."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from second_brain.models import ConceptRecord
from second_brain.storage.repository import BrainRepository

TOKEN = re.compile(r"[a-z0-9]+")


class MatchAction(StrEnum):
    NEW = "NEW"
    UPDATE = "UPDATE"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    SUPERSEDES = "SUPERSEDES"
    UNRELATED = "UNRELATED"


@dataclass(frozen=True, slots=True)
class ConceptMatch:
    action: MatchAction
    existing_id: str | None
    score: float
    reason: str


def _tokens(value: str) -> set[str]:
    return set(TOKEN.findall(value.lower()))


def similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class ConceptMatcher:
    def __init__(self, repository: BrainRepository) -> None:
        self.repository = repository

    def match(self, concept: ConceptRecord) -> ConceptMatch:
        exact = self.repository.concept_by_title(concept.title)
        if exact is not None:
            existing_summary = str(exact["summary"])
            score = similarity(existing_summary, concept.summary)
            if score >= 0.9:
                return ConceptMatch(
                    MatchAction.DUPLICATE,
                    str(exact["id"]),
                    score,
                    "Exact title and near-identical summary.",
                )
            return ConceptMatch(
                MatchAction.UPDATE,
                str(exact["id"]),
                score,
                "Exact title but materially different summary; meaning-changing update should be reviewed.",
            )

        best: tuple[float, dict[str, Any]] | None = None
        for row in self.repository.list_concepts():
            metadata = json.loads(str(row.get("metadata_json") or "{}"))
            text = f"{row['title']} {row['summary']} {metadata.get('tags', [])}"
            score = similarity(f"{concept.title} {concept.summary}", text)
            if best is None or score > best[0]:
                best = (score, row)
        if best is None or best[0] < 0.45:
            return ConceptMatch(MatchAction.NEW, None, best[0] if best else 0.0, "No close concept.")
        if best[0] >= 0.82:
            return ConceptMatch(
                MatchAction.DUPLICATE,
                str(best[1]["id"]),
                best[0],
                "High deterministic token overlap; keep existing concept and provenance link.",
            )
        return ConceptMatch(
            MatchAction.UNRELATED,
            str(best[1]["id"]),
            best[0],
            "Related candidate exists but similarity is insufficient for merge/update.",
        )
