"""Typed repositories over generated SQLite state."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from second_brain.models import (
    ClaimRecord,
    ConceptRecord,
    DecisionRecord,
    EntityRecord,
    RelationshipRecord,
)
from second_brain.storage.sqlite import SQLiteStore


def _now() -> str:
    return datetime.now(UTC).isoformat()


class BrainRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.store.initialize()

    def list_concepts(self) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM concepts").fetchall()]

    def concept_by_id(self, concept_id: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone()
        return dict(row) if row is not None else None

    def concept_by_title(self, title: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM concepts WHERE lower(title) = lower(?) LIMIT 1", (title,)
            ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def upsert_concept_db(conn: sqlite3.Connection, concept: ConceptRecord, note_path: str) -> None:
        now = _now()
        metadata = concept.model_dump(mode="json")
        conn.execute(
            """
            INSERT INTO concepts(
                id, title, summary, status, verification_state, note_path,
                created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                summary=excluded.summary,
                status=excluded.status,
                verification_state=excluded.verification_state,
                note_path=excluded.note_path,
                updated_at=excluded.updated_at,
                metadata_json=excluded.metadata_json
            """,
            (
                concept.id,
                concept.title,
                concept.summary,
                concept.status,
                concept.verification_state.value,
                note_path,
                now,
                now,
                json.dumps(metadata, sort_keys=True),
            ),
        )

    @staticmethod
    def insert_claim_db(conn: sqlite3.Connection, claim: ClaimRecord, materialized_path: str | None) -> None:
        if claim.supersedes:
            conn.execute(
                "UPDATE claims SET superseded_by = ?, status = 'superseded' WHERE id = ?",
                (claim.id, claim.supersedes),
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO claims(
                id, statement, status, confidence_state, source_id, source_locator,
                valid_from, valid_to, supersedes, superseded_by, materialized_path, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.id,
                claim.statement,
                claim.status,
                claim.confidence_state.value,
                claim.source_id,
                claim.source_locator,
                claim.valid_from.isoformat() if claim.valid_from else None,
                claim.valid_to.isoformat() if claim.valid_to else None,
                claim.supersedes,
                claim.superseded_by,
                materialized_path,
                json.dumps(claim.model_dump(mode="json"), sort_keys=True),
            ),
        )

    @staticmethod
    def insert_entity_db(conn: sqlite3.Connection, entity: EntityRecord, note_path: str | None) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO entities(id, name, entity_type, note_path, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                entity.id,
                entity.name,
                entity.entity_type,
                note_path,
                json.dumps(entity.model_dump(mode="json"), sort_keys=True),
            ),
        )

    @staticmethod
    def insert_decision_db(conn: sqlite3.Connection, decision: DecisionRecord) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO decisions(
                id, project_id, decision, context, reasoning, status, decided_at,
                supersedes, superseded_by, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.id,
                decision.project_id,
                decision.decision,
                decision.context,
                decision.reasoning,
                decision.status,
                decision.decided_at.isoformat() if decision.decided_at else None,
                decision.supersedes,
                decision.superseded_by,
                json.dumps(decision.model_dump(mode="json"), sort_keys=True),
            ),
        )
        if decision.supersedes:
            conn.execute(
                "UPDATE decisions SET superseded_by = ?, status = 'superseded' WHERE id = ?",
                (decision.id, decision.supersedes),
            )

    @staticmethod
    def insert_relationship_db(conn: sqlite3.Connection, relation: RelationshipRecord) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO relationships(
                id, from_id, to_id, relation, source_id, provisional, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relation.id,
                relation.from_id,
                relation.to_id,
                relation.relation.value,
                relation.source_id,
                int(relation.provisional),
                json.dumps(relation.model_dump(mode="json"), sort_keys=True),
            ),
        )

    @staticmethod
    def insert_question_db(
        conn: sqlite3.Connection,
        *,
        question_id: str,
        question: str,
        source_id: str | None = None,
        missing_evidence: str = "",
    ) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO questions(
                id, question, status, searched_json, found_json, missing_evidence,
                created_at, metadata_json
            ) VALUES (?, ?, 'open', '[]', '[]', ?, ?, ?)
            """,
            (
                question_id,
                question,
                missing_evidence,
                _now(),
                json.dumps({"source_id": source_id}, sort_keys=True),
            ),
        )

    @staticmethod
    def insert_open_loop_db(
        conn: sqlite3.Connection,
        *,
        loop_id: str,
        text: str,
        project_id: str | None,
        source_id: str | None,
    ) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO open_loops(
                id, text, project_id, source_id, status, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, 'open', ?, '{}')
            """,
            (loop_id, text, project_id, source_id, _now()),
        )

    @staticmethod
    def insert_project_candidate_db(
        conn: sqlite3.Connection,
        *,
        candidate_id: str,
        name: str,
        rationale: str,
        confidence_state: str,
        source_id: str,
    ) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO project_candidates(
                id, name, rationale, confidence_state, source_id, status, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, 'candidate', ?, '{}')
            """,
            (candidate_id, name, rationale, confidence_state, source_id, _now()),
        )

    def get_ai_cache(self, cache_key: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT result_json FROM ai_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        if row is None:
            return None
        value = json.loads(str(row["result_json"]))
        return value if isinstance(value, dict) else None

    def put_ai_cache(
        self,
        *,
        cache_key: str,
        task_type: str,
        source_hash: str,
        task_version: str,
        provider: str,
        model: str,
        schema_version: str,
        result: dict[str, Any],
    ) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ai_cache(
                    cache_key, task_type, source_hash, task_version, provider, model,
                    schema_version, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    task_type,
                    source_hash,
                    task_version,
                    provider,
                    model,
                    schema_version,
                    json.dumps(result, sort_keys=True),
                    _now(),
                ),
            )
