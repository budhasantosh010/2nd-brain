from __future__ import annotations

from pathlib import Path

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.projects import ProjectService, ProjectSpec, ProjectStateInput
from second_brain.models import ProcessingState, QueryType
from second_brain.paths import BrainPaths
from second_brain.retrieval.service import RetrievalService
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.service import REFUSAL, VerificationService


def _ingest(paths: BrainPaths, store: SQLiteStore, path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    result = IngestionService(paths, load_config(paths), store).ingest_file(path)
    assert result.source_id is not None and result.state == ProcessingState.NEEDS_AI
    return result.source_id


def test_exact_identifier_filename_and_hash_lookup(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    path = input_dir / "exact-reference.txt"
    source_id = _ingest(
        isolated_brain,
        store,
        path,
        "Branch feature/global-brain-phase1-phase2 uses exact SHA abcdef1234567890.",
    )
    row = store.source_by_id(source_id)
    assert row is not None
    retrieval = RetrievalService(isolated_brain, store=store)
    assert retrieval.classify(source_id) == QueryType.EXACT
    assert any(hit.source_id == source_id or hit.object_id == source_id for hit in retrieval.search(source_id))
    assert any(hit.source_id == source_id or hit.object_id == source_id for hit in retrieval.search(path.name))
    assert any(
        hit.source_id == source_id or hit.object_id == source_id
        for hit in retrieval.search(str(row["content_hash"])[:12])
    )


def test_semantic_and_hybrid_retrieval_find_related_evidence(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    source_id = _ingest(
        isolated_brain,
        store,
        input_dir / "hybrid.txt",
        "Hybrid retrieval combines lexical search with semantic vector search and evidence fusion.",
    )
    retrieval = RetrievalService(isolated_brain, store=store)
    hits = retrieval.search("semantic vector retrieval plus lexical evidence", limit=10)
    assert any(hit.source_id == source_id for hit in hits)
    relevant = next(hit for hit in hits if hit.source_id == source_id)
    assert set(relevant.metadata.get("channels", [])) & {"lexical", "semantic"}


def test_current_project_state_is_preferred_but_history_remains_retrievable(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    old_source = _ingest(isolated_brain, store, input_dir / "old-state.txt", "The old state was architecture design.")
    new_source = _ingest(isolated_brain, store, input_dir / "new-state.txt", "The current state is validation complete.")
    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(ProjectSpec(title="State Retrieval Project", goal="Test current state."))
    projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="Architecture design is in progress.",
            next_action="Implement ingestion.",
            latest_verified_evidence=[old_source],
            source_ids=[old_source],
        ),
    )
    projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="Validation is complete.",
            next_action="Publish the final branch.",
            latest_verified_evidence=[new_source],
            source_ids=[new_source],
        ),
    )
    retrieval = RetrievalService(isolated_brain, store=store)
    current = retrieval.search("What is the current state of State Retrieval Project?", project_id=project_id)
    assert current
    assert any("Validation is complete" in hit.text for hit in current[:5])
    historical = retrieval.search("What was the old previous state of State Retrieval Project?", project_id=project_id)
    assert any(hit.object_type == "project-state-history" for hit in historical)


def test_supported_answer_contains_source_citation_and_unsupported_question_refuses_and_stores_gap(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    source_id = _ingest(
        isolated_brain,
        store,
        input_dir / "answer.txt",
        "The verified launch code is ORBIT-ALPHA-7421 and the retrieval layer preserves citations.",
    )
    verification = VerificationService(isolated_brain, store)
    supported = verification.ask("What is the verified launch code ORBIT-ALPHA-7421?")
    assert supported.answer != REFUSAL
    assert source_id in supported.citations[0]
    assert any(item.source_id == source_id for item in supported.evidence)

    unsupported = verification.ask("What is the favorite ice cream flavor of ZXQJ-UNRELATED-998877?")
    assert unsupported.answer == REFUSAL
    assert unsupported.missing_information
    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM questions WHERE question LIKE '%favorite ice cream%' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None and row["status"] == "open"
    dashboard = isolated_brain.vault / "07 Operations" / "Unanswered Questions.md"
    assert "favorite ice cream" in dashboard.read_text(encoding="utf-8")


def test_project_scoping_boosts_scoped_project_without_isolating_global_brain(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    evidence = _ingest(isolated_brain, store, input_dir / "scope.txt", "Scoped project evidence marker.")
    projects = ProjectService(isolated_brain, store)
    first = projects.create(ProjectSpec(title="Scoped Alpha", goal="Alpha retrieval."))
    second = projects.create(ProjectSpec(title="Scoped Beta", goal="Beta retrieval."))
    projects.update_state(
        first,
        ProjectStateInput(
            current_state="Scoped evidence is alpha-current.",
            next_action="Alpha next.",
            latest_verified_evidence=[evidence],
            source_ids=[evidence],
        ),
    )
    retrieval = RetrievalService(isolated_brain, store=store)
    hits = retrieval.search("Scoped evidence current state", project_id=first, limit=20)
    assert any(hit.metadata.get("project_id") == first or hit.object_id == first for hit in hits)
    assert any(hit.object_id == second or hit.metadata.get("project_id") == second for hit in retrieval.search("Scoped Beta", limit=20))
