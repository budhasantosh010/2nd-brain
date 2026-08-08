from __future__ import annotations

from pathlib import Path

from conftest import StaticProvider

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.compiler import KnowledgeCompiler
from second_brain.knowledge.projects import ProjectService, ProjectSpec, ProjectStateInput
from second_brain.models import ProcessingState
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore


def _ingest_text(paths: BrainPaths, store: SQLiteStore, path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    result = IngestionService(paths, load_config(paths), store).ingest_file(path)
    assert result.source_id is not None
    assert result.state == ProcessingState.NEEDS_AI
    return result.source_id


def _payload(
    source_id: str,
    *,
    concepts: list[dict[str, object]] | None = None,
    claims: list[dict[str, object]] | None = None,
    decisions: list[dict[str, object]] | None = None,
    entities: list[dict[str, object]] | None = None,
    open_loops: list[dict[str, object]] | None = None,
    questions: list[str] | None = None,
) -> dict[str, object]:
    return {
        "purpose": "synthetic knowledge fixture",
        "entities": entities or [],
        "project_candidates": [],
        "claims": claims or [],
        "decisions": decisions or [],
        "concepts": concepts or [],
        "open_loops": open_loops or [],
        "questions": questions or [],
    }


def test_new_concept_is_provisional_persisted_and_indexed(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    source_id = _ingest_text(
        isolated_brain,
        store,
        input_dir / "new-concept.txt",
        "Hybrid retrieval combines lexical and semantic evidence.",
    )
    provider = StaticProvider(
        _payload(
            source_id,
            concepts=[
                {
                    "title": "Hybrid Retrieval",
                    "summary": "Combine lexical search with semantic vector retrieval.",
                    "status": "provisional",
                    "verification_state": "provisional",
                    "source_ids": [source_id],
                }
            ],
            claims=[
                {
                    "statement": "Hybrid retrieval combines lexical and semantic search.",
                    "source_id": source_id,
                    "source_locator": "lines 1-1",
                    "confidence_state": "provisional",
                }
            ],
        )
    )
    result = KnowledgeCompiler(isolated_brain, load_config(isolated_brain), store, provider).compile_source(source_id)
    assert result.state == ProcessingState.COMPLETE
    assert len(result.created_concepts) == 1
    concept_id = result.created_concepts[0]
    with store.connect() as conn:
        concept = conn.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone()
        claim = conn.execute("SELECT * FROM claims WHERE source_id = ?", (source_id,)).fetchone()
        vector = conn.execute("SELECT * FROM vector_items WHERE object_id = ?", (concept_id,)).fetchone()
    assert concept is not None and concept["status"] == "provisional"
    assert concept["verification_state"] == "provisional"
    assert claim is not None
    assert vector is not None
    assert (isolated_brain.brain / "ledgers" / f"knowledge-{source_id}.json").is_file()


def test_duplicate_concept_links_new_source_without_creating_second_concept(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    first_source = _ingest_text(isolated_brain, store, input_dir / "first.txt", "same concept")
    concept = {
        "title": "Evidence Fusion",
        "summary": "Combine multiple ranked evidence channels.",
        "status": "provisional",
        "verification_state": "provisional",
        "source_ids": [first_source],
    }
    first = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(_payload(first_source, concepts=[concept])),
    ).compile_source(first_source)
    assert len(first.created_concepts) == 1

    second_source = _ingest_text(isolated_brain, store, input_dir / "second.txt", "same concept again")
    second_concept = dict(concept)
    second_concept["source_ids"] = [second_source]
    second = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(_payload(second_source, concepts=[second_concept])),
    ).compile_source(second_source)
    assert second.duplicate_concepts == first.created_concepts
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 1
        linked = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE from_id = ? AND to_id = ? AND relation = 'derived-from'",
            (first.created_concepts[0], second_source),
        ).fetchone()[0]
    assert linked == 1


def test_meaning_changing_concept_update_is_staged_then_approval_updates_db_and_index(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    first_source = _ingest_text(isolated_brain, store, input_dir / "base.txt", "base understanding")
    base = {
        "title": "Current State",
        "summary": "Current state comes from the latest verified project state.",
        "status": "provisional",
        "verification_state": "provisional",
        "source_ids": [first_source],
    }
    first = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(_payload(first_source, concepts=[base])),
    ).compile_source(first_source)
    concept_id = first.created_concepts[0]

    second_source = _ingest_text(isolated_brain, store, input_dir / "update.txt", "changed understanding")
    changed = {
        "title": "Current State",
        "summary": "Current state is now defined by a materially different evidence-backed rule.",
        "status": "provisional",
        "verification_state": "provisional",
        "source_ids": [second_source],
    }
    compiler = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(_payload(second_source, concepts=[changed])),
    )
    result = compiler.compile_source(second_source)
    assert result.state == ProcessingState.NEEDS_REVIEW
    assert len(result.review_items) == 1
    with store.connect() as conn:
        before = conn.execute("SELECT summary FROM concepts WHERE id = ?", (concept_id,)).fetchone()[0]
    assert before == base["summary"]

    compiler.reviews.approve(result.review_items[0])
    with store.connect() as conn:
        after = conn.execute("SELECT summary FROM concepts WHERE id = ?", (concept_id,)).fetchone()[0]
        indexed = conn.execute(
            "SELECT text FROM search_fts WHERE object_id = ? AND object_type = 'concept'", (concept_id,)
        ).fetchone()[0]
    assert after == changed["summary"]
    assert str(changed["summary"]) in indexed


def test_claim_conflict_is_preserved_and_decision_supersession_marks_old_decision(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    source_one = _ingest_text(isolated_brain, store, input_dir / "old.txt", "old claims and decision")
    compiler_one = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(
            _payload(
                source_one,
                claims=[
                    {
                        "statement": "The system uses cloud AI for all source processing.",
                        "source_id": source_one,
                        "source_locator": "lines 1-1",
                        "confidence_state": "supported",
                    }
                ],
                decisions=[
                    {
                        "decision": "Use lexical search only.",
                        "reasoning": "Old architecture decision.",
                        "status": "active",
                        "source_ids": [source_one],
                    }
                ],
            )
        ),
    )
    first = compiler_one.compile_source(source_one)
    old_decision = first.decisions[0]

    source_two = _ingest_text(isolated_brain, store, input_dir / "new.txt", "new claims and decision")
    compiler_two = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(
            _payload(
                source_two,
                claims=[
                    {
                        "statement": "The system does not use cloud AI for all source processing.",
                        "source_id": source_two,
                        "source_locator": "lines 1-1",
                        "confidence_state": "supported",
                    }
                ],
                decisions=[
                    {
                        "decision": "Use hybrid lexical and semantic retrieval.",
                        "reasoning": "Current architecture needs exact and conceptual retrieval.",
                        "status": "active",
                        "supersedes": old_decision,
                        "source_ids": [source_two],
                    }
                ],
            )
        ),
    )
    second = compiler_two.compile_source(source_two)
    assert second.state == ProcessingState.COMPLETE
    with store.connect() as conn:
        old_row = conn.execute("SELECT * FROM decisions WHERE id = ?", (old_decision,)).fetchone()
        conflict = conn.execute("SELECT * FROM conflicts WHERE status = 'open'").fetchone()
        contradict = conn.execute(
            "SELECT * FROM relationships WHERE relation = 'contradicts'"
        ).fetchone()
    assert old_row is not None
    assert old_row["status"] == "superseded"
    assert old_row["superseded_by"] == second.decisions[0]
    assert conflict is not None
    assert contradict is not None


def test_project_state_history_and_handoff_are_preserved(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    evidence_source = _ingest_text(
        isolated_brain, store, input_dir / "evidence.txt", "Project reached milestone two."
    )
    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(
        ProjectSpec(
            title="Synthetic Project",
            goal="Build and verify the synthetic project.",
            desired_outcome="Verified completion.",
            success_criteria=["State can resume correctly"],
            source_ids=[evidence_source],
        )
    )
    operation = projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="Milestone two is complete.",
            last_completed="Milestone two",
            currently_working_on="Validation",
            next_action="Run acceptance tests.",
            latest_verified_evidence=[evidence_source],
            source_ids=[evidence_source],
        ),
    )
    assert operation.startswith("OP-")
    history = projects.history(project_id)
    assert len(history) == 2
    assert sum(int(row["active"]) for row in history) == 1
    assert projects.current_state(project_id).current_state == "Milestone two is complete."
    projects.create_handoff(project_id)
    with store.connect() as conn:
        project = conn.execute("SELECT project_path FROM projects WHERE id = ?", (project_id,)).fetchone()
    assert project is not None
    handoff = isolated_brain.vault / str(project["project_path"]) / "HANDOFF.md"
    content = handoff.read_text(encoding="utf-8")
    assert "Milestone two is complete." in content
    assert "Run acceptance tests." in content
    assert evidence_source in content


def test_ambiguous_project_state_change_is_staged_for_review(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(ProjectSpec(title="Ambiguous Project", goal="Keep state truthful."))
    review_id = projects.update_state(
        project_id,
        ProjectStateInput(current_state="Maybe the objective changed.", next_action="Unknown."),
        ambiguous=True,
    )
    assert review_id.startswith("RVW-")
    assert projects.current_state(project_id).current_state != "Maybe the objective changed."
    item = projects.reviews.get(review_id)
    assert item.status == "pending"
    assert item.type == "project-state-change"
