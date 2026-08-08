"""SQLite storage with migrations, FTS5 and transaction helpers."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, cast

from second_brain.models import ParsedDocument, SourceRecord
from second_brain.storage.schema import MIGRATIONS, SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ClosingConnection(sqlite3.Connection):
    """sqlite3 context manager that also closes the handle on exit.

    The stdlib Connection context manager commits/rolls back but does not close;
    on Windows that can keep brain.sqlite locked during rebuild/replace operations.
    """

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        try:
            super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()
        return False


class SQLiteStore:
    """Generated structured store. Canonical source/Markdown files remain independently owned."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                int(row["version"])
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for version in sorted(MIGRATIONS):
                if version in applied:
                    continue
                conn.executescript(MIGRATIONS[version])
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
            conn.commit()

    def schema_version(self) -> int:
        if not self.path.exists():
            return 0
        with self.connect() as conn:
            row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            return int(row["version"] or 0) if row else 0

    def pending_migrations(self) -> list[int]:
        current = self.schema_version()
        return [version for version in sorted(MIGRATIONS) if version > current]

    def fts5_available(self) -> bool:
        try:
            with self.connect() as conn:
                conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(value)")
                conn.execute("DROP TABLE IF EXISTS _fts_probe")
                conn.commit()
            return True
        except sqlite3.OperationalError:
            return False

    def source_by_hash(self, content_hash: str) -> sqlite3.Row | None:
        if not self.path.exists():
            return None
        with self.connect() as conn:
            return cast(
                sqlite3.Row | None,
                conn.execute(
                    "SELECT * FROM sources WHERE content_hash = ?", (content_hash,)
                ).fetchone(),
            )

    def source_by_id(self, source_id: str) -> sqlite3.Row | None:
        if not self.path.exists():
            return None
        with self.connect() as conn:
            return cast(
                sqlite3.Row | None,
                conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone(),
            )

    def upsert_source(self, source: SourceRecord, *, mime_type: str | None = None) -> None:
        payload = source.model_dump(mode="json")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO sources(
                    id, content_hash, source_type, title, original_filename, original_path,
                    raw_path, extracted_path, mime_type, size_bytes, created_at, ingested_at,
                    status, authority, sensitivity, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    raw_path=excluded.raw_path,
                    extracted_path=excluded.extracted_path,
                    mime_type=excluded.mime_type,
                    status=excluded.status,
                    authority=excluded.authority,
                    sensitivity=excluded.sensitivity,
                    metadata_json=excluded.metadata_json
                """,
                (
                    source.id,
                    source.content_hash,
                    source.source_type,
                    source.title,
                    source.original_filename,
                    source.original_path,
                    source.raw_path,
                    source.extracted_path,
                    mime_type,
                    source.size_bytes,
                    source.created_at.isoformat() if source.created_at else None,
                    source.ingested_at.isoformat(),
                    source.status.value,
                    source.authority,
                    source.sensitivity.value,
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def replace_segments(self, document: ParsedDocument) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM source_segments WHERE source_id = ?", (document.source_id,))
            conn.execute("DELETE FROM search_fts WHERE source_id = ?", (document.source_id,))
            for segment in document.segments:
                conn.execute(
                    """
                    INSERT INTO source_segments(segment_id, source_id, position, locator, text, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        segment.segment_id,
                        document.source_id,
                        segment.position,
                        segment.locator,
                        segment.text,
                        json.dumps(segment.metadata, sort_keys=True),
                    ),
                )
                conn.execute(
                    "INSERT INTO search_fts(object_id, object_type, title, text, source_id, locator) "
                    "VALUES (?, 'source-segment', ?, ?, ?, ?)",
                    (
                        segment.segment_id,
                        document.title,
                        segment.text,
                        document.source_id,
                        segment.locator,
                    ),
                )

    def index_text(
        self,
        *,
        object_id: str,
        object_type: str,
        title: str,
        text: str,
        source_id: str | None = None,
        locator: str | None = None,
    ) -> None:
        with self.transaction() as conn:
            self.index_text_in_connection(
                conn,
                object_id=object_id,
                object_type=object_type,
                title=title,
                text=text,
                source_id=source_id,
                locator=locator,
            )

    @staticmethod
    def index_text_in_connection(
        conn: sqlite3.Connection,
        *,
        object_id: str,
        object_type: str,
        title: str,
        text: str,
        source_id: str | None = None,
        locator: str | None = None,
    ) -> None:
        conn.execute("DELETE FROM search_fts WHERE object_id = ?", (object_id,))
        conn.execute(
            "INSERT INTO search_fts(object_id, object_type, title, text, source_id, locator) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (object_id, object_type, title, text, source_id, locator),
        )

    def search_fts(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists() or not query.strip():
            return []
        expression = self._fts_expression(query)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT object_id, object_type, title, text, source_id, locator, bm25(search_fts) AS rank
                FROM search_fts
                WHERE search_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _fts_expression(query: str) -> str:
        stripped = query.strip()
        if stripped.startswith('"') and stripped.endswith('"') and len(stripped) > 2:
            return stripped
        tokens = [
            token.replace('"', "").replace("'", "")
            for token in stripped.replace("/", " ").replace("\\", " ").split()
        ]
        safe = [token for token in tokens if token]
        if not safe:
            return '""'
        return " OR ".join(f'"{token}"' for token in safe)

    def update_source_status(self, source_id: str, status: str, *, extracted_path: str | None = None) -> None:
        with self.transaction() as conn:
            if extracted_path is None:
                conn.execute("UPDATE sources SET status = ? WHERE id = ?", (status, source_id))
            else:
                conn.execute(
                    "UPDATE sources SET status = ?, extracted_path = ? WHERE id = ?",
                    (status, extracted_path, source_id),
                )

    def create_job(
        self,
        *,
        job_id: str,
        input_path: str,
        state: str,
        stage: str,
        source_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO processing_jobs(
                    id, source_id, input_path, state, stage, retry_count,
                    created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source_id=excluded.source_id,
                    state=excluded.state,
                    stage=excluded.stage,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    job_id,
                    source_id,
                    input_path,
                    state,
                    stage,
                    now,
                    now,
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )

    def update_job(
        self,
        job_id: str,
        *,
        state: str,
        stage: str,
        source_id: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        next_action: str | None = None,
        increment_retry: bool = False,
    ) -> None:
        retry_sql = "retry_count = retry_count + 1," if increment_retry else ""
        with self.transaction() as conn:
            safe_source_id = source_id
            if source_id is not None:
                source_exists = conn.execute(
                    "SELECT 1 FROM sources WHERE id = ?", (source_id,)
                ).fetchone()
                if source_exists is None:
                    safe_source_id = None
            conn.execute(
                f"""
                UPDATE processing_jobs SET
                    source_id = COALESCE(?, source_id),
                    state = ?, stage = ?,
                    {retry_sql}
                    error_type = ?, error_message = ?, next_action = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    safe_source_id,
                    state,
                    stage,
                    error_type,
                    error_message,
                    next_action,
                    utc_now(),
                    job_id,
                ),
            )

    def processing_jobs(self, states: list[str] | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.connect() as conn:
            if states:
                placeholders = ",".join("?" for _ in states)
                rows = conn.execute(
                    f"SELECT * FROM processing_jobs WHERE state IN ({placeholders}) ORDER BY updated_at DESC",
                    states,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM processing_jobs ORDER BY updated_at DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def table_names(self) -> set[str]:
        if not self.path.exists():
            return set()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        return {str(row["name"]) for row in rows}

    def health(self) -> dict[str, Any]:
        return {
            "exists": self.path.exists(),
            "schema_version": self.schema_version(),
            "expected_schema_version": SCHEMA_VERSION,
            "pending_migrations": self.pending_migrations(),
            "fts5": self.fts5_available(),
        }
