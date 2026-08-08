"""Rebuildable local vector index stored in SQLite for V1 portability."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from second_brain.embeddings.local import LocalEmbeddingProvider, cosine
from second_brain.models import SearchHit
from second_brain.storage.sqlite import SQLiteStore


class VectorStore:
    def __init__(self, store: SQLiteStore, embedding: LocalEmbeddingProvider) -> None:
        self.store = store
        self.embedding = embedding
        self.store.initialize()

    def upsert(
        self,
        *,
        object_id: str,
        object_type: str,
        title: str,
        text: str,
        source_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.store.transaction() as conn:
            self.upsert_in_connection(
                conn,
                object_id=object_id,
                object_type=object_type,
                title=title,
                text=text,
                source_id=source_id,
                metadata=metadata,
            )

    def upsert_in_connection(
        self,
        conn: sqlite3.Connection,
        *,
        object_id: str,
        object_type: str,
        title: str,
        text: str,
        source_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        vector = self.embedding.embed(text)
        conn.execute(
            """
            INSERT INTO vector_items(
                object_id, object_type, source_id, title, text, vector_json, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(object_id) DO UPDATE SET
                object_type=excluded.object_type,
                source_id=excluded.source_id,
                title=excluded.title,
                text=excluded.text,
                vector_json=excluded.vector_json,
                updated_at=excluded.updated_at,
                metadata_json=excluded.metadata_json
            """,
            (
                object_id,
                object_type,
                source_id,
                title,
                text,
                json.dumps(vector),
                datetime.now(UTC).isoformat(),
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        object_types: set[str] | None = None,
    ) -> list[SearchHit]:
        query_vector = self.embedding.embed(query)
        with self.store.connect() as conn:
            rows = conn.execute("SELECT * FROM vector_items").fetchall()
        scored: list[SearchHit] = []
        for row in rows:
            object_type = str(row["object_type"])
            if object_types and object_type not in object_types:
                continue
            vector = json.loads(str(row["vector_json"]))
            if not isinstance(vector, list):
                continue
            numeric_vector = [float(value) for value in vector]
            score = cosine(query_vector, numeric_vector)
            metadata_value = json.loads(str(row["metadata_json"] or "{}"))
            metadata = metadata_value if isinstance(metadata_value, dict) else {}
            scored.append(
                SearchHit(
                    object_id=str(row["object_id"]),
                    object_type=object_type,
                    title=str(row["title"]),
                    text=str(row["text"]),
                    score=score,
                    source_id=str(row["source_id"]) if row["source_id"] else None,
                    updated_at=datetime.fromisoformat(str(row["updated_at"])),
                    metadata=metadata,
                )
            )
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:limit]

    def clear(self) -> None:
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM vector_items")
