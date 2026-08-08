from __future__ import annotations

from second_brain.embeddings.local import LocalEmbeddingProvider
from second_brain.knowledge.projects import ProjectService, ProjectSpec, ProjectStateInput
from second_brain.models import ConceptRecord, PlannedWrite, VerificationState
from second_brain.paths import BrainPaths
from second_brain.retrieval.service import RetrievalService
from second_brain.review.service import ReviewService
from second_brain.storage.markdown import file_sha256
from second_brain.storage.repository import BrainRepository
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore
from second_brain.transactions.plan import build_plan


def _row(store: SQLiteStore, table: str, key: str, value: str):  # type: ignore[no-untyped-def]
    with store.connect() as conn:
        return conn.execute(f"SELECT * FROM {table} WHERE {key} = ?", (value,)).fetchone()


def test_approved_concept_update_rolls_back_markdown_db_fts_vector_and_survives_restart(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    concept = ConceptRecord(
        id="KNO-phase25-rollback-concept",
        title="Rollback Integrity",
        summary="Original canonical meaning.",
        status="verified",
        verification_state=VerificationState.VERIFIED,
    )
    note_rel = "03 Knowledge/Concepts/rollback-integrity--KNO-phase25-rollback-concept.md"
    note = isolated_brain.vault / note_rel
    old_markdown = "# Rollback Integrity\n\nOriginal canonical meaning.\n"
    note.write_text(old_markdown, encoding="utf-8")
    BrainRepository(store).store.initialize()
    vectors = VectorStore(store, LocalEmbeddingProvider(384))
    with store.transaction() as conn:
        BrainRepository.upsert_concept_db(conn, concept, note_rel)
        store.index_text_in_connection(
            conn,
            object_id=concept.id,
            object_type="concept",
            title=concept.title,
            text=f"{concept.title}\n{concept.summary}",
            locator=note_rel,
        )
        vectors.upsert_in_connection(
            conn,
            object_id=concept.id,
            object_type="concept",
            title=concept.title,
            text=f"{concept.title}\n{concept.summary}",
            metadata={"locator": note_rel},
        )

    updated = concept.model_copy(update={"summary": "Approved replacement meaning."})
    plan = build_plan(
        "Meaning-changing concept update",
        [
            PlannedWrite(
                path=note_rel,
                content="# Rollback Integrity\n\nApproved replacement meaning.\n",
                expected_hash=file_sha256(note),
            )
        ],
        permission_level=2,
    )
    plan.metadata.update(
        {
            "concept_update": updated.model_dump(mode="json"),
            "note_path": note_rel,
        }
    )
    reviews = ReviewService(isolated_brain, store)
    item = reviews.stage(
        plan,
        review_type="concept-update",
        risk="high",
        proposal="Replace the canonical meaning",
        reason="Phase 2.5 rollback fixture",
    )
    operation_id = reviews.approve(item.review_id)

    assert "Approved replacement meaning" in note.read_text(encoding="utf-8")
    assert str(_row(store, "concepts", "id", concept.id)["summary"]) == "Approved replacement meaning."
    assert "Approved replacement meaning" in str(_row(store, "vector_items", "object_id", concept.id)["text"])
    with store.connect() as conn:
        fts = conn.execute("SELECT text FROM search_fts WHERE object_id = ?", (concept.id,)).fetchone()
    assert fts is not None and "Approved replacement meaning" in str(fts["text"])

    reviews.rollback(item.review_id)
    assert note.read_text(encoding="utf-8") == old_markdown
    assert str(_row(store, "concepts", "id", concept.id)["summary"]) == "Original canonical meaning."
    assert "Original canonical meaning" in str(_row(store, "vector_items", "object_id", concept.id)["text"])
    with store.connect() as conn:
        fts = conn.execute("SELECT text FROM search_fts WHERE object_id = ?", (concept.id,)).fetchone()
        original_operation = conn.execute(
            "SELECT status FROM operations WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        rollback_operations = conn.execute(
            "SELECT operation_id, status, payload_json FROM operations WHERE description = ?",
            (f"Rollback of {operation_id}",),
        ).fetchall()
    assert fts is not None and "Original canonical meaning" in str(fts["text"])
    assert original_operation is not None and str(original_operation["status"]) == "applied"
    assert len(rollback_operations) == 1 and str(rollback_operations[0]["status"]) == "applied"

    restarted_store = SQLiteStore(isolated_brain.db)
    restarted_store.initialize()
    assert str(_row(restarted_store, "concepts", "id", concept.id)["summary"]) == "Original canonical meaning."
    assert "Original canonical meaning" in str(
        _row(restarted_store, "vector_items", "object_id", concept.id)["text"]
    )


def test_ambiguous_project_state_approval_and_rollback_restore_complete_logical_state(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(ProjectSpec(title="Rollback Project", goal="Prove state rollback."))
    projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="Previous trusted state.",
            last_completed="Baseline completed.",
            next_action="Keep the previous plan.",
        ),
    )
    project_row = _row(store, "projects", "id", project_id)
    folder = str(project_row["project_path"])
    state_path = isolated_brain.vault / folder / "STATE.md"
    handoff_path = isolated_brain.vault / folder / "HANDOFF.md"
    before_state = state_path.read_text(encoding="utf-8")
    before_handoff = handoff_path.read_text(encoding="utf-8")

    review_id = projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="Ambiguous proposed replacement state.",
            last_completed="Uncertain interpretation.",
            next_action="Do the risky thing.",
        ),
        ambiguous=True,
    )
    reviews = ReviewService(isolated_brain, store)
    operation_id = reviews.approve(review_id)
    assert projects.current_state(project_id).current_state == "Ambiguous proposed replacement state."
    assert "Ambiguous proposed replacement state" in state_path.read_text(encoding="utf-8")
    assert "Ambiguous proposed replacement state" in handoff_path.read_text(encoding="utf-8")
    current_hits = RetrievalService(isolated_brain, store=store).search(
        "current state Rollback Project",
        project_id=project_id,
    )
    assert any("Ambiguous proposed replacement state" in hit.text for hit in current_hits[:5])

    reviews.rollback(review_id)
    assert projects.current_state(project_id).current_state == "Previous trusted state."
    assert state_path.read_text(encoding="utf-8") == before_state
    assert handoff_path.read_text(encoding="utf-8") == before_handoff
    current_hits = RetrievalService(isolated_brain, store=store).search(
        "current state Rollback Project",
        project_id=project_id,
    )
    assert any("Previous trusted state" in hit.text for hit in current_hits[:5])
    assert not any("Ambiguous proposed replacement state" in hit.text for hit in current_hits[:3])

    with store.connect() as conn:
        active = conn.execute(
            "SELECT current_state FROM project_states WHERE project_id = ? AND active = 1",
            (project_id,),
        ).fetchall()
        rollback_ops = conn.execute(
            "SELECT operation_id FROM operations WHERE description = ?",
            (f"Rollback of {operation_id}",),
        ).fetchall()
    assert [str(row["current_state"]) for row in active] == ["Previous trusted state."]
    assert len(rollback_ops) == 1

    restarted_store = SQLiteStore(isolated_brain.db)
    restarted_store.initialize()
    restarted_projects = ProjectService(isolated_brain, restarted_store)
    assert restarted_projects.current_state(project_id).current_state == "Previous trusted state."
