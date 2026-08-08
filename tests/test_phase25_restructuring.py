from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from second_brain.config import load_config
from second_brain.knowledge.projects import ProjectService, ProjectSpec
from second_brain.knowledge.restructuring import RestructuringService
from second_brain.models import ConceptRecord, VerificationState
from second_brain.paths import BrainPaths
from second_brain.review.service import ReviewService
from second_brain.storage.repository import BrainRepository
from second_brain.storage.sqlite import SQLiteStore


def test_structural_analyzer_detects_friction_and_stages_advisory_review(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(
        ProjectSpec(title="Stale Structure Project", goal="Exercise structural hardening.")
    )
    stale = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    with store.transaction() as conn:
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (stale, project_id))
        conn.execute(
            "UPDATE project_states SET next_action='', verified_at=?, evidence_json='[]' "
            "WHERE project_id=? AND active=1",
            (stale, project_id),
        )

    concept = ConceptRecord(
        id="KNO-phase25-orphan",
        title="Orphan Retrieval Knowledge",
        summary="A useful concept with no links and no provenance yet.",
        status="provisional",
        verification_state=VerificationState.PROVISIONAL,
    )
    note_rel = "03 Knowledge/Concepts/orphan-retrieval--KNO-phase25-orphan.md"
    (isolated_brain.vault / note_rel).write_text(
        "# Orphan Retrieval Knowledge\n\nHuman canonical note.\n",
        encoding="utf-8",
    )
    with store.transaction() as conn:
        BrainRepository.upsert_concept_db(conn, concept, note_rel)
        for _index in range(3):
            conn.execute(
                "INSERT INTO retrieval_events(query,query_type,results_json,created_at,answered,metadata_json) "
                "VALUES (?,?,?,?,0,'{}')",
                (
                    "Where is the customer churn playbook?",
                    "CONCEPTUAL",
                    json.dumps([]),
                    datetime.now(UTC).isoformat(),
                ),
            )

    service = RestructuringService(isolated_brain, load_config(isolated_brain), store)
    report = service.analyze()
    kinds = {finding.finding_type for finding in report.findings}
    assert "orphan-concept" in kinds
    assert "concept-without-provenance" in kinds
    assert "stale-active-project" in kinds
    assert "project-without-next-action" in kinds
    assert "stale-current-state-evidence" in kinds
    assert "repeated-retrieval-failure" in kinds

    review_ids = service.generate_proposals(limit=8)
    assert review_ids
    review = ReviewService(isolated_brain, store).get(review_ids[0])
    assert review.type == "restructuring-candidate"
    assert review.risk in {"high", "medium"}
    assert review.reason
    assert review.risks
    assert review.rollback
    assert (isolated_brain.vault / "07 Operations" / "Structural Audit.md").is_file()

    # Structural suggestions are advisory: review cannot accidentally auto-apply a canonical mutation.
    with pytest.raises(ValueError, match="Advisory review proposals cannot auto-apply"):
        ReviewService(isolated_brain, store).approve(review_ids[0])
