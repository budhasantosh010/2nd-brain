from __future__ import annotations

from second_brain.knowledge.projects import ProjectService, ProjectSpec, ProjectStateInput
from second_brain.models import (
    ConceptRecord,
    RelationshipRecord,
    RelationshipType,
    VerificationState,
)
from second_brain.paths import BrainPaths
from second_brain.storage.repository import BrainRepository
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.consistency import ConsistencyVerifier


def test_consistency_verifier_fails_markdown_db_and_graph_disagreement(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    concept = ConceptRecord(
        id="KNO-phase25-consistency",
        title="Canonical Agreement",
        summary="Database and Markdown agree.",
        status="verified",
        verification_state=VerificationState.VERIFIED,
    )
    note_rel = "03 Knowledge/Concepts/canonical-agreement--KNO-phase25-consistency.md"
    note = isolated_brain.vault / note_rel
    note.write_text(
        "---\nid: KNO-phase25-consistency\ntype: concept\ntitle: Canonical Agreement\n---\n\n"
        "# Canonical Agreement\n\n## Summary\n\nMarkdown says something else.\n",
        encoding="utf-8",
    )
    with store.transaction() as conn:
        BrainRepository.upsert_concept_db(conn, concept, note_rel)
        relation = RelationshipRecord(
            id="REL-phase25-dangling",
            from_id=concept.id,
            to_id="KNO-missing-endpoint",
            relation=RelationshipType.RELATED_TO,
        )
        BrainRepository.insert_relationship_db(conn, relation)

    report = ConsistencyVerifier(isolated_brain, store).verify()
    codes = {item.check for item in report.canonical_errors}
    assert not report.ok
    assert "concept_markdown" in codes
    assert "relationship_endpoint" in codes


def test_project_state_disagreement_is_meaning_bearing_but_generated_drift_is_warning(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(ProjectSpec(title="Consistency Project", goal="Test state parity."))
    projects.update_state(
        project_id,
        ProjectStateInput(current_state="Database current state", next_action="Continue"),
    )
    with store.connect() as conn:
        path_value = conn.execute("SELECT project_path FROM projects WHERE id=?", (project_id,)).fetchone()[0]
    state_path = isolated_brain.vault / str(path_value) / "STATE.md"
    text = state_path.read_text(encoding="utf-8")
    state_path.write_text(text.replace("Database current state", "Different Markdown state"), encoding="utf-8")
    with store.transaction() as conn:
        store.index_text_in_connection(
            conn,
            object_id="KNO-generated-missing",
            object_type="concept",
            title="Missing generated object",
            text="generated drift",
        )

    report = ConsistencyVerifier(isolated_brain, store).verify()
    assert any(item.check == "project_state_markdown" for item in report.canonical_errors)
    assert any(item.check == "fts_orphans" for item in report.generated_warnings)
    assert not report.ok
