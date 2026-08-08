"""Multi-stage concept matching: exact → lexical → semantic candidate → decision."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from second_brain.models import ConceptRecord
from second_brain.storage.repository import BrainRepository
from second_brain.storage.vector import VectorStore

TOKEN = re.compile(r"[a-z0-9]+")


class MatchAction(StrEnum):
    NEW = "NEW"
    UPDATE = "UPDATE"
    DUPLICATE = "DUPLICATE"
    RELATED = "RELATED"
    CONFLICT = "CONFLICT"
    SUPERSEDES = "SUPERSEDES"
    REVIEW = "REVIEW"
    UNRELATED = "UNRELATED"


@dataclass(frozen=True, slots=True)
class ConceptMatch:
    action: MatchAction
    existing_id: str | None
    score: float
    reason: str


def _tokens(value: str) -> set[str]:
    return set(TOKEN.findall(value.lower()))


def normalize_title(value: str) -> str:
    return " ".join(TOKEN.findall(value.lower()))


def similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class ConceptMatcher:
    def __init__(self, repository: BrainRepository, vectors: VectorStore | None = None) -> None:
        self.repository = repository
        self.vectors = vectors

    def match(self, concept: ConceptRecord) -> ConceptMatch:
        # Stage 1: exact title identity.
        exact = self.repository.concept_by_title(concept.title)
        if exact is not None:
            return self._same_identity_decision(concept, exact, "Exact title")

        # Stage 2: normalized title identity (case/punctuation/spacing variations).
        normalized = normalize_title(concept.title)
        for row in self.repository.list_concepts():
            if normalize_title(str(row["title"])) == normalized:
                return self._same_identity_decision(concept, row, "Normalized title")

        # Stage 2b: cheap lexical candidate generation, never an embedding-only merge.
        best: tuple[float, dict[str, Any]] | None = None
        for row in self.repository.list_concepts():
            metadata = json.loads(str(row.get("metadata_json") or "{}"))
            text = f"{row['title']} {row['summary']} {metadata.get('tags', [])}"
            score = similarity(f"{concept.title} {concept.summary}", text)
            if best is None or score > best[0]:
                best = (score, row)
        if best is not None and best[0] >= 0.68:
            # Similar wording with a different title is related evidence, not permission to merge.
            return ConceptMatch(
                MatchAction.RELATED,
                str(best[1]["id"]),
                best[0],
                "High lexical candidate with different identity; create separately and link as related.",
            )

        # Stage 3: learned semantic candidate search. Hashing/fuzzy vectors are explicitly not
        # treated as semantic evidence. A high semantic score only creates a RELATED candidate.
        if self.vectors is not None and self.vectors.profile.learned:
            hits = self.vectors.search(
                f"{concept.title}\n{concept.summary}",
                limit=8,
                object_types={"concept"},
            )
            if hits:
                best_hit = hits[0]
                if best_hit.score >= 0.68:
                    return ConceptMatch(
                        MatchAction.RELATED,
                        best_hit.object_id,
                        best_hit.score,
                        "Learned semantic candidate; similarity alone cannot merge canonical knowledge.",
                    )

        return ConceptMatch(
            MatchAction.NEW,
            None,
            best[0] if best else 0.0,
            "No sufficiently close canonical identity; create new provisional knowledge.",
        )

    @staticmethod
    def _same_identity_decision(
        concept: ConceptRecord,
        existing: dict[str, Any],
        stage: str,
    ) -> ConceptMatch:
        existing_summary = str(existing["summary"])
        score = similarity(existing_summary, concept.summary)
        if score >= 0.88:
            return ConceptMatch(
                MatchAction.DUPLICATE,
                str(existing["id"]),
                score,
                f"{stage} and near-identical meaning; attach provenance to canonical concept.",
            )
        return ConceptMatch(
            MatchAction.UPDATE,
            str(existing["id"]),
            score,
            f"{stage} but materially different meaning; review is required before updating canonical knowledge.",
        )
