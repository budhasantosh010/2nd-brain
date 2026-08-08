"""Rebuildable local vector index with explicit embedding schema metadata."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from second_brain.embeddings.base import EmbeddingMetadata, EmbeddingProvider
from second_brain.embeddings.local import cosine
from second_brain.models import SearchHit
from second_brain.storage.sqlite import SQLiteStore


class VectorStore:
    def __init__(self, store: SQLiteStore, embedding: EmbeddingProvider) -> None:
        self.store = store
        self.embedding = embedding
        self.store.initialize()
        self.profile = self._ensure_profile(embedding.metadata)

    def _ensure_profile(self, metadata: EmbeddingMetadata) -> EmbeddingMetadata:
        target = metadata.with_timestamp()
        stable = {
            "provider": target.provider,
            "model": target.model,
            "revision": target.revision,
            "dimensions": target.dimensions,
            "schema_version": target.schema_version,
            "learned": target.learned,
        }
        profile_id = hashlib.sha256(
            json.dumps(stable, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        with self.store.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM embedding_profiles WHERE active = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            current_key = (
                (
                    str(row["provider"]),
                    str(row["model"]),
                    str(row["revision"]),
                    int(row["dimensions"]),
                    str(row["schema_version"]),
                )
                if row is not None
                else None
            )
            mismatch = current_key != target.profile_key()
            if mismatch:
                # Generated vectors are disposable; never mix incompatible vector schemas.
                conn.execute("DELETE FROM vector_items")
                conn.execute("UPDATE embedding_profiles SET active = 0")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO embedding_profiles(
                        profile_id,provider,model,revision,dimensions,schema_version,
                        learned,created_at,active,metadata_json
                    ) VALUES (?,?,?,?,?,?,?,?,1,?)
                    """,
                    (
                        profile_id,
                        target.provider,
                        target.model,
                        target.revision,
                        target.dimensions,
                        target.schema_version,
                        int(target.learned),
                        target.created_at,
                        json.dumps(stable, sort_keys=True),
                    ),
                )
            elif row is not None:
                target = target.model_copy(update={"created_at": str(row["created_at"])})
        return target

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
        if len(vector) != self.profile.dimensions:
            raise ValueError(
                f"Vector dimension mismatch: profile={self.profile.dimensions} actual={len(vector)}"
            )
        payload = dict(metadata or {})
        payload["_embedding"] = {
            "provider": self.profile.provider,
            "model": self.profile.model,
            "revision": self.profile.revision,
            "dimensions": self.profile.dimensions,
            "schema_version": self.profile.schema_version,
        }
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
                json.dumps(payload, sort_keys=True),
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
        scored.sort(key=lambda hit: (-hit.score, hit.object_id))
        return scored[:limit]

    def clear(self) -> None:
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM vector_items")
