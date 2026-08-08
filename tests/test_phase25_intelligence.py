from __future__ import annotations

from pathlib import Path

from second_brain.embeddings.learned import LearnedLocalEmbeddingProvider
from second_brain.knowledge.contradiction import ConflictKind, assess_claim_pair
from second_brain.knowledge.matcher import ConceptMatcher, MatchAction
from second_brain.models import ConceptRecord, VerificationState
from second_brain.paths import BrainPaths
from second_brain.storage.repository import BrainRepository
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore


def _learned() -> LearnedLocalEmbeddingProvider:
    return LearnedLocalEmbeddingProvider(
        cache_dir=str(Path.cwd() / "vault" / ".brain" / "cache" / "embeddings")
    )


def test_semantically_close_different_identity_is_related_not_duplicate(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    repository = BrainRepository(store)
    existing = ConceptRecord(
        id="KNO-existing-attrition",
        title="Employee Attrition",
        summary="Employee attrition increased sharply during the last quarter.",
        status="verified",
        verification_state=VerificationState.VERIFIED,
    )
    with store.transaction() as conn:
        BrainRepository.upsert_concept_db(
            conn,
            existing,
            "03 Knowledge/Concepts/employee-attrition--KNO-existing-attrition.md",
        )
    vectors = VectorStore(store, _learned())
    vectors.upsert(
        object_id=existing.id,
        object_type="concept",
        title=existing.title,
        text=f"{existing.title}\n{existing.summary}",
    )
    incoming = ConceptRecord(
        id="KNO-incoming-turnover",
        title="Staff Turnover",
        summary="More staff are leaving the company than before.",
        status="provisional",
        verification_state=VerificationState.PROVISIONAL,
    )
    match = ConceptMatcher(repository, vectors).match(incoming)
    assert match.action == MatchAction.RELATED
    assert match.existing_id == existing.id
    assert match.score >= 0.68


def test_semantic_permission_conflict_detected_without_negation_words() -> None:
    assessment = assess_claim_pair(
        "Cloud AI is enabled for all sources.",
        "Only explicitly approved sources may use cloud AI.",
        provider=_learned(),
    )
    assert assessment.kind == ConflictKind.CONFLICT
    assert "restrictive" in assessment.reason.lower() or "approval" in assessment.reason.lower()


def test_launch_date_move_is_temporal_supersession_not_contradiction() -> None:
    assessment = assess_claim_pair(
        "Launch date is September 10.",
        "The launch has been moved to October 4.",
        provider=_learned(),
    )
    assert assessment.kind == ConflictKind.SUPERSESSION
    assert "historical" in assessment.reason.lower() or "superseded" in assessment.reason.lower()


def test_unrelated_semantic_negative_is_not_conflict() -> None:
    assessment = assess_claim_pair(
        "Customer acquisition cost is rising across paid channels.",
        "The office cafeteria changed its lunch menu.",
        provider=_learned(),
    )
    assert assessment.kind == ConflictKind.NONE
