from __future__ import annotations

from pathlib import Path

from conftest import StaticProvider
from pypdf import PdfWriter

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.compiler import KnowledgeCompiler
from second_brain.knowledge.projects import ProjectService, ProjectSpec, ProjectStateInput
from second_brain.paths import BrainPaths
from second_brain.retrieval.service import RetrievalService
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.service import REFUSAL, VerificationService


def _ingest(paths: BrainPaths, store: SQLiteStore, path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    result = IngestionService(paths, load_config(paths), store).ingest_file(path)
    assert result.source_id is not None
    return result.source_id


def test_complete_synthetic_old_new_project_conflict_exact_and_gap_flow(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    old_chat = _ingest(
        isolated_brain,
        store,
        input_dir / "old-chat.txt",
        "OLD POSITION: Project Atlas should use lexical search only. Exact old marker OLD-ATLAS-101.",
    )
    new_chat = _ingest(
        isolated_brain,
        store,
        input_dir / "new-chat.txt",
        "CURRENT POSITION: Project Atlas uses hybrid lexical and semantic retrieval. Exact commit 53609aad71c49759ff15cf82e6a9918b163b3f20.",
    )
    handoff_source = _ingest(
        isolated_brain,
        store,
        input_dir / "handoff-source.txt",
        "Project Atlas current state is acceptance validation. Next action is push the verified branch.",
    )

    pdf_path = input_dir / "research.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf_path.open("wb") as handle:
        writer.write(handle)
    pdf_result = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(pdf_path)
    assert pdf_result.source_id is not None and pdf_result.raw_path is not None

    old_payload = {
        "purpose": "old project chat",
        "entities": [],
        "project_candidates": [],
        "claims": [
            {
                "statement": "Project Atlas uses lexical search only for retrieval.",
                "source_id": old_chat,
                "source_locator": "lines 1-1",
                "confidence_state": "supported",
            }
        ],
        "decisions": [
            {
                "decision": "Use lexical search only for Project Atlas.",
                "reasoning": "Old position before semantic retrieval was added.",
                "status": "active",
                "source_ids": [old_chat],
            }
        ],
        "concepts": [
            {
                "title": "Retrieval",
                "summary": "Project Atlas retrieval combines evidence search channels.",
                "status": "provisional",
                "verification_state": "provisional",
                "source_ids": [old_chat],
            }
        ],
        "open_loops": [],
        "questions": [],
    }
    old_compiled = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(old_payload),
    ).compile_source(old_chat)
    old_decision = old_compiled.decisions[0]

    new_payload = {
        "purpose": "new project chat",
        "entities": [],
        "project_candidates": [],
        "claims": [
            {
                "statement": "Project Atlas does not use lexical search only for retrieval.",
                "source_id": new_chat,
                "source_locator": "lines 1-1",
                "confidence_state": "supported",
            }
        ],
        "decisions": [
            {
                "decision": "Use hybrid lexical and semantic retrieval for Project Atlas.",
                "reasoning": "Exact IDs need lexical search while conceptual questions benefit from semantic search.",
                "status": "active",
                "supersedes": old_decision,
                "source_ids": [new_chat],
            }
        ],
        "concepts": [
            {
                "title": "Retrieval",
                "summary": "Project Atlas retrieval combines evidence search channels.",
                "status": "provisional",
                "verification_state": "provisional",
                "source_ids": [new_chat],
            }
        ],
        "open_loops": [
            {
                "text": "Push the verified Project Atlas branch.",
                "source_id": new_chat,
                "status": "open",
            }
        ],
        "questions": [],
    }
    new_compiled = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(new_payload),
    ).compile_source(new_chat)
    assert new_compiled.duplicate_concepts == old_compiled.created_concepts

    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(
        ProjectSpec(
            title="Project Atlas",
            goal="Build trustworthy hybrid retrieval.",
            source_ids=[old_chat, new_chat, handoff_source],
        )
    )
    projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="Old implementation work was in progress.",
            next_action="Add semantic search.",
            latest_verified_evidence=[old_chat],
            source_ids=[old_chat],
        ),
    )
    projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="Acceptance validation is the current state.",
            last_completed="Hybrid retrieval implementation completed.",
            next_action="Push the verified branch.",
            latest_verified_evidence=[handoff_source, new_chat],
            source_ids=[handoff_source, new_chat],
        ),
    )
    projects.create_handoff(project_id)

    retrieval = RetrievalService(isolated_brain, store=store)
    verification = VerificationService(isolated_brain, store, retrieval)

    current_hits = retrieval.search("What is the current state of Project Atlas?", project_id=project_id)
    assert any("Acceptance validation is the current state" in hit.text for hit in current_hits[:5])

    exact_hits = retrieval.search("53609aad71c49759ff15cf82e6a9918b163b3f20")
    assert any(hit.source_id == new_chat for hit in exact_hits)

    history_hits = retrieval.search("What was the old previous position for Project Atlas retrieval?", project_id=project_id)
    assert any(old_chat == hit.source_id or "Old implementation" in hit.text for hit in history_hits)

    with store.connect() as conn:
        old_row = conn.execute("SELECT status, superseded_by FROM decisions WHERE id = ?", (old_decision,)).fetchone()
        conflicts = conn.execute("SELECT COUNT(*) FROM conflicts WHERE status = 'open'").fetchone()[0]
    assert old_row is not None and old_row["status"] == "superseded"
    assert old_row["superseded_by"] == new_compiled.decisions[0]
    assert conflicts >= 1

    decision_hits = retrieval.search("Why did we make the current hybrid retrieval decision?")
    assert any("Exact IDs need lexical search" in hit.text for hit in decision_hits)

    conflict_answer = verification.ask("Which Project Atlas retrieval sources disagree?")
    assert conflict_answer.conflicts or conflicts >= 1

    unknown = verification.ask("What database password is used by Project Atlas? PASSWORD-NOT-STORED-7788")
    assert unknown.answer == REFUSAL
    with store.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM questions WHERE question LIKE '%PASSWORD-NOT-STORED-7788%'"
        ).fetchone()[0] == 1
