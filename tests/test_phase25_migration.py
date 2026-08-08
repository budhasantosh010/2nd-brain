from __future__ import annotations

import json
import sqlite3

from second_brain.migration import migrate_phase2_runtime
from second_brain.paths import BrainPaths
from second_brain.storage.durable import read_jsonl, read_resolution
from second_brain.storage.schema import MIGRATION_1, SCHEMA_VERSION
from second_brain.storage.sqlite import SQLiteStore


def test_phase2_runtime_migrates_to_phase25_without_loss_and_is_idempotent(
    isolated_brain: BrainPaths,
) -> None:
    db = isolated_brain.db
    db.unlink(missing_ok=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    source_id = "SRC-migration-fixture"
    concept_id = "KNO-migration-fixture"
    project_id = "PRJ-migration-fixture"
    question_id = "QUE-migration-fixture"
    now = "2026-08-08T00:00:00+00:00"
    raw = isolated_brain.raw / "Documents" / source_id / "legacy.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("legacy raw evidence", encoding="utf-8")
    concept_note = isolated_brain.vault / "03 Knowledge" / "Concepts" / "legacy.md"
    concept_note.parent.mkdir(parents=True, exist_ok=True)
    concept_bytes = b"---\nid: KNO-migration-fixture\ntype: concept\ntitle: Legacy Canonical\n---\n\n# Legacy Canonical\n"
    concept_note.write_bytes(concept_bytes)

    conn = sqlite3.connect(db)
    try:
        conn.executescript(MIGRATION_1)
        conn.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(1,?)", (now,))
        conn.execute(
            """
            INSERT INTO sources(id,content_hash,source_type,title,original_filename,original_path,raw_path,
                size_bytes,ingested_at,status,authority,sensitivity,metadata_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                source_id,
                "a" * 64,
                "text",
                "Legacy",
                "legacy.txt",
                "legacy.txt",
                str(raw),
                raw.stat().st_size,
                now,
                "COMPLETE",
                "unknown",
                "local_only",
                "{}",
            ),
        )
        concept_payload = {
            "id": concept_id,
            "title": "Legacy Canonical",
            "summary": "Old canonical meaning survives.",
            "status": "verified",
            "verification_state": "verified",
            "source_ids": [source_id],
            "project_ids": [],
            "tags": [],
        }
        conn.execute(
            """
            INSERT INTO concepts(id,title,summary,status,verification_state,note_path,created_at,updated_at,metadata_json)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                concept_id,
                "Legacy Canonical",
                "Old canonical meaning survives.",
                "verified",
                "verified",
                "03 Knowledge/Concepts/legacy.md",
                now,
                now,
                json.dumps(concept_payload),
            ),
        )
        project_path = f"04 Projects/Active Projects/Legacy--{project_id}"
        project_dir = isolated_brain.vault / project_path
        project_dir.mkdir(parents=True, exist_ok=True)
        state_file = project_dir / "STATE.md"
        state_bytes = b"# Current Project State\n\n## Current State\n\nLegacy state\n"
        state_file.write_bytes(state_bytes)
        conn.execute(
            "INSERT INTO projects(id,title,status,project_path,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?)",
            (project_id, "Legacy Project", "active", project_path, now, now, "{}"),
        )
        conn.execute(
            """
            INSERT INTO project_states(project_id,current_state,next_action,blockers_json,open_questions_json,
                evidence_json,verified_at,created_at,active) VALUES(?,?,?,?,?,?,?,?,1)
            """,
            (project_id, "Legacy state", "Continue", "[]", "[]", json.dumps([source_id]), now, now),
        )
        conn.execute(
            """
            INSERT INTO questions(id,question,status,searched_json,found_json,missing_evidence,created_at,metadata_json)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (question_id, "What is still unknown?", "open", "[]", "[]", "Need evidence", now, "{}"),
        )
        conn.commit()
    finally:
        conn.close()

    legacy = isolated_brain.brain / "ledgers" / f"knowledge-{source_id}.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        json.dumps(
            {
                "source_id": source_id,
                "source_hash": "a" * 64,
                "schema": "knowledge-extraction-v1",
                "provider": "mock",
                "model": "old",
                "compiled_at": now,
                "extraction": {
                    "purpose": "legacy fixture",
                    "concepts": [concept_payload],
                    "claims": [],
                    "entities": [],
                    "decisions": [],
                    "project_candidates": [],
                    "open_loops": [],
                    "questions": [],
                },
            }
        ),
        encoding="utf-8",
    )

    store = SQLiteStore(db)
    first = migrate_phase2_runtime(isolated_brain, store)
    assert first.schema_before == 1
    assert first.schema_after == SCHEMA_VERSION == 2
    assert first.resolution_ledgers_created == 1
    assert first.project_events_created == 1
    assert first.gap_events_created == 1
    with store.connect() as check:
        assert check.execute("SELECT title FROM concepts WHERE id=?", (concept_id,)).fetchone()[0] == "Legacy Canonical"
        assert check.execute("SELECT current_state FROM project_states WHERE project_id=? AND active=1", (project_id,)).fetchone()[0] == "Legacy state"
    resolution = read_resolution(isolated_brain.brain / "ledgers" / "resolutions" / f"{source_id}.json")
    assert resolution is not None
    assert resolution.concept_resolutions[0].canonical_id == concept_id
    assert concept_note.read_bytes() == concept_bytes
    assert state_file.read_bytes() == state_bytes
    assert raw.read_text(encoding="utf-8") == "legacy raw evidence"

    project_history = read_jsonl(isolated_brain.brain / "ledgers" / "projects" / f"{project_id}.jsonl")
    gap_history = read_jsonl(isolated_brain.brain / "ledgers" / "knowledge-gaps.jsonl")
    second = migrate_phase2_runtime(isolated_brain, store)
    assert second.resolution_ledgers_created == 0
    assert second.project_events_created == 0
    assert second.gap_events_created == 0
    assert read_jsonl(isolated_brain.brain / "ledgers" / "projects" / f"{project_id}.jsonl") == project_history
    assert read_jsonl(isolated_brain.brain / "ledgers" / "knowledge-gaps.jsonl") == gap_history
