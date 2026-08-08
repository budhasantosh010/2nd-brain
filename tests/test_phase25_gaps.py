from __future__ import annotations

from pathlib import Path

from conftest import StaticProvider

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.compiler import KnowledgeCompiler
from second_brain.knowledge.gaps import GapResolver
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.service import REFUSAL, VerificationService


def test_unknown_question_is_resolved_when_later_evidence_arrives(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    verification = VerificationService(isolated_brain, store)
    answer = verification.ask("What is the Project Orion launch code?")
    assert answer.answer == REFUSAL

    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM questions WHERE question=? ORDER BY created_at DESC LIMIT 1",
            ("What is the Project Orion launch code?",),
        ).fetchone()
    assert row is not None
    question_id = str(row["id"])
    assert row["status"] == "open"

    source = input_dir / "later-orion-evidence.txt"
    source.write_text(
        "Project Orion launch code is ORN-7319. This identifier is the approved launch code.",
        encoding="utf-8",
    )
    ingested = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(source)
    assert ingested.source_id is not None
    payload = {
        "purpose": "resolve knowledge gap",
        "entities": [],
        "project_candidates": [],
        "claims": [
            {
                "statement": "Project Orion launch code is ORN-7319.",
                "source_id": ingested.source_id,
                "source_locator": "lines 1-1",
                "confidence_state": "supported",
            }
        ],
        "decisions": [],
        "concepts": [],
        "open_loops": [],
        "questions": [],
    }
    KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(payload),
    ).compile_source(ingested.source_id)

    with store.connect() as conn:
        resolved = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    assert resolved is not None
    assert resolved["status"] in {"candidate_evidence", "resolved"}
    assert ingested.source_id in str(resolved["found_json"])

    history = GapResolver(isolated_brain, store).history(question_id)
    events = [str(event["event"]) for event in history]
    assert events[0] == "opened"
    assert "candidate_evidence_found" in events
    if resolved["status"] == "resolved":
        assert "resolved" in events
        assert resolved["resolved_at"] is not None
    assert (isolated_brain.vault / "07 Operations" / "Unanswered Questions.md").is_file()
    assert (isolated_brain.vault / "07 Operations" / "Knowledge Gaps.md").is_file()
