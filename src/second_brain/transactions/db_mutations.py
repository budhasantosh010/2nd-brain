"""Persisted reversible database mutation scopes and row snapshots.

Phase 2.5 deliberately keeps database mutation scopes explicit.  The callback that
performs a mutation may still be ordinary Python, but rollback/recovery never has
to understand or re-run that callback: it restores the exact rows captured for
its declared logical scope.
"""

from __future__ import annotations

import base64
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Tables that are part of the generated/structured brain and are safe to restore
# with row-level snapshots. schema_migrations is intentionally excluded.
ALLOWED_SNAPSHOT_TABLES = {
    "sources",
    "source_segments",
    "notes",
    "concepts",
    "claims",
    "entities",
    "projects",
    "project_states",
    "decisions",
    "relationships",
    "skills",
    "processing_jobs",
    "review_items",
    "operations",
    "conflicts",
    "open_loops",
    "project_candidates",
    "questions",
    "retrieval_events",
    "feedback",
    "ai_cache",
    "vector_items",
    "search_fts",
}

# Delete children before parents, then insert in the reverse direction.
_TABLE_DEPENDENCY_RANK = {
    "feedback": 100,
    "source_segments": 95,
    "project_states": 95,
    "relationships": 90,
    "conflicts": 90,
    "open_loops": 90,
    "project_candidates": 90,
    "claims": 90,
    "decisions": 90,
    "processing_jobs": 90,
    "search_fts": 85,
    "vector_items": 85,
    "review_items": 80,
    "notes": 70,
    "concepts": 70,
    "entities": 70,
    "skills": 70,
    "questions": 70,
    "retrieval_events": 60,
    "ai_cache": 60,
    "projects": 30,
    "sources": 20,
    "operations": 10,
}


class DatabaseRowScope(BaseModel):
    """A bounded set of rows affected by one logical mutation."""

    table: str
    where_sql: str
    params: list[Any] = Field(default_factory=list)
    label: str = ""

    @field_validator("table")
    @classmethod
    def validate_table(cls, value: str) -> str:
        if not _IDENTIFIER.match(value) or value not in ALLOWED_SNAPSHOT_TABLES:
            raise ValueError(f"Unsupported snapshot table: {value}")
        return value

    @field_validator("where_sql")
    @classmethod
    def validate_where(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or ";" in normalized:
            raise ValueError("Snapshot scope requires one bounded WHERE expression")
        return normalized


class DatabaseRowSnapshot(BaseModel):
    scope: DatabaseRowScope
    columns: list[str]
    rows: list[list[Any]] = Field(default_factory=list)


class DatabaseMutationPlan(BaseModel):
    """Declared logical database/index mutation boundary for a transaction."""

    scopes: list[DatabaseRowScope] = Field(default_factory=list)
    fts_object_ids: list[str] = Field(default_factory=list)
    vector_object_ids: list[str] = Field(default_factory=list)
    description: str = ""

    def expanded_scopes(self) -> list[DatabaseRowScope]:
        result = list(self.scopes)
        result.extend(
            DatabaseRowScope(
                table="search_fts",
                where_sql="object_id = ?",
                params=[object_id],
                label=f"FTS {object_id}",
            )
            for object_id in self.fts_object_ids
        )
        result.extend(
            DatabaseRowScope(
                table="vector_items",
                where_sql="object_id = ?",
                params=[object_id],
                label=f"Vector {object_id}",
            )
            for object_id in self.vector_object_ids
        )
        seen: set[str] = set()
        unique: list[DatabaseRowScope] = []
        for scope in result:
            key = scope.model_dump_json()
            if key in seen:
                continue
            seen.add(key)
            unique.append(scope)
        return unique


class TransactionSnapshot(BaseModel):
    captured_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    rows: list[DatabaseRowSnapshot] = Field(default_factory=list)


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__sqlite_bytes__": base64.b64encode(value).decode("ascii")}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__sqlite_bytes__"}:
        return base64.b64decode(str(value["__sqlite_bytes__"]))
    return value


def capture_snapshot(conn: sqlite3.Connection, plan: DatabaseMutationPlan) -> TransactionSnapshot:
    snapshots: list[DatabaseRowSnapshot] = []
    for scope in plan.expanded_scopes():
        cursor = conn.execute(
            f"SELECT * FROM {scope.table} WHERE {scope.where_sql}",
            tuple(scope.params),
        )
        columns = [str(value[0]) for value in (cursor.description or [])]
        rows = [[_encode(value) for value in tuple(row)] for row in cursor.fetchall()]
        snapshots.append(DatabaseRowSnapshot(scope=scope, columns=columns, rows=rows))
    return TransactionSnapshot(rows=snapshots)


def restore_snapshot(conn: sqlite3.Connection, snapshot: TransactionSnapshot) -> None:
    """Restore only declared rows, preserving unrelated later operations."""

    ordered = sorted(
        snapshot.rows,
        key=lambda item: (_TABLE_DEPENDENCY_RANK.get(item.scope.table, 50), item.scope.table),
        reverse=True,
    )
    for item in ordered:
        conn.execute(
            f"DELETE FROM {item.scope.table} WHERE {item.scope.where_sql}",
            tuple(item.scope.params),
        )

    for item in reversed(ordered):
        if not item.rows:
            continue
        columns = item.columns
        if not columns or any(not _IDENTIFIER.match(column) for column in columns):
            raise ValueError(f"Invalid snapshot columns for {item.scope.table}")
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        for row in item.rows:
            conn.execute(
                f"INSERT INTO {item.scope.table} ({column_sql}) VALUES ({placeholders})",
                tuple(_decode(value) for value in row),
            )


def snapshot_signature(snapshot: TransactionSnapshot) -> list[tuple[str, str, tuple[str, ...], tuple[tuple[str, ...], ...]]]:
    """Stable comparison form used to verify a restore before releasing the lock."""

    result: list[tuple[str, str, tuple[str, ...], tuple[tuple[str, ...], ...]]] = []
    for item in snapshot.rows:
        encoded_rows = tuple(
            sorted(tuple(repr(value) for value in row) for row in item.rows)
        )
        result.append(
            (
                item.scope.table,
                item.scope.model_dump_json(),
                tuple(item.columns),
                encoded_rows,
            )
        )
    return sorted(result)


def snapshots_equal(left: TransactionSnapshot, right: TransactionSnapshot) -> bool:
    return snapshot_signature(left) == snapshot_signature(right)
