from __future__ import annotations

from pathlib import Path

from conftest import StaticProvider

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.compiler import KnowledgeCompiler
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.manager import TransactionManager
from second_brain.verification.consistency import ConsistencyVerifier


def _ingest(paths: BrainPaths, store: SQLiteStore, path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    result = IngestionService(paths, load_config(paths), store).ingest_file(path)
    assert result.source_id is not None
    return result.source_id


def test_decision_supersession_updates_markdown_db_indexes_and_rolls_back_together(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    old_source = _ingest(
        isolated_brain,
        store,
        input_dir / "old-decision.txt",
        "The launch decision is September 10.",
    )
    old_payload = {
        "purpose": "old decision",
        "entities": [],
        "project_candidates": [],
        "claims": [],
        "decisions": [
            {
                "decision": "Launch on September 10.",
                "reasoning": "Original launch plan.",
                "status": "active",
                "source_ids": [old_source],
            }
        ],
        "concepts": [],
        "open_loops": [],
        "questions": [],
    }
    old_result = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(old_payload),
    ).compile_source(old_source)
    old_id = old_result.decisions[0]

    new_source = _ingest(
        isolated_brain,
        store,
        input_dir / "new-decision.txt",
        "The launch moved to October 4.",
    )
    new_payload = {
        "purpose": "superseding decision",
        "entities": [],
        "project_candidates": [],
        "claims": [],
        "decisions": [
            {
                "decision": "Launch on October 4.",
                "reasoning": "The schedule changed after the September plan.",
                "status": "active",
                "supersedes": old_id,
                "source_ids": [new_source],
            }
        ],
        "concepts": [],
        "open_loops": [],
        "questions": [],
    }
    new_result = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(new_payload),
    ).compile_source(new_source)
    new_id = new_result.decisions[0]

    with store.connect() as conn:
        old_row = conn.execute("SELECT status,superseded_by FROM decisions WHERE id=?", (old_id,)).fetchone()
        vector = conn.execute("SELECT metadata_json FROM vector_items WHERE object_id=?", (old_id,)).fetchone()
        operation_id = str(
            conn.execute(
                "SELECT operation_id FROM operations WHERE description=? AND status='applied' ORDER BY created_at DESC LIMIT 1",
                (f"Compile validated knowledge from {new_source}",),
            ).fetchone()[0]
        )
    assert old_row is not None and old_row["status"] == "superseded"
    assert old_row["superseded_by"] == new_id
    assert vector is not None and '"status": "superseded"' in str(vector["metadata_json"])
    old_note = isolated_brain.vault / "03 Knowledge" / "Decisions" / f"{old_id}.md"
    assert "status: superseded" in old_note.read_text(encoding="utf-8")
    assert ConsistencyVerifier(isolated_brain, store).verify().ok

    TransactionManager(isolated_brain, store).rollback(operation_id)
    reopened = SQLiteStore(isolated_brain.db)
    reopened.initialize()
    with reopened.connect() as conn:
        restored_old = conn.execute("SELECT status,superseded_by FROM decisions WHERE id=?", (old_id,)).fetchone()
        removed_new = conn.execute("SELECT 1 FROM decisions WHERE id=?", (new_id,)).fetchone()
        restored_vector = conn.execute("SELECT metadata_json FROM vector_items WHERE object_id=?", (old_id,)).fetchone()
    assert restored_old is not None and restored_old["status"] == "active"
    assert restored_old["superseded_by"] is None
    assert removed_new is None
    assert restored_vector is not None and '"status": "active"' in str(restored_vector["metadata_json"])
    assert "status: active" in old_note.read_text(encoding="utf-8")
    assert not (isolated_brain.vault / "03 Knowledge" / "Decisions" / f"{new_id}.md").exists()
    assert ConsistencyVerifier(isolated_brain, reopened).verify().ok
