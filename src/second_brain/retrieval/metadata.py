"""Exact metadata lookup for IDs, hashes, filenames, projects and decisions."""

from __future__ import annotations

import json
import re
from datetime import datetime

from second_brain.models import SearchHit
from second_brain.storage.sqlite import SQLiteStore

ID_PATTERN = re.compile(
    r"\b(?:SRC|KNO|CLM|DEC|PRJ|ENT|SKL|RVW|OP|QUE|LOP)-[A-Za-z0-9-]{6,}\b",
    re.IGNORECASE,
)
HASH_PATTERN = re.compile(r"\b[a-fA-F0-9]{7,64}\b")


class MetadataRetriever:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def search(self, query: str, *, limit: int = 30) -> list[SearchHit]:
        candidates: dict[str, SearchHit] = {}
        identifiers = {value.upper() for value in ID_PATTERN.findall(query)}
        hashes = {value.lower() for value in HASH_PATTERN.findall(query) if len(value) >= 7}
        query_lower = query.lower().strip().strip('"')

        with self.store.connect() as conn:
            for identifier in identifiers:
                for table, object_type, title_column, text_column in (
                    ("sources", "source", "title", "original_path"),
                    ("concepts", "concept", "title", "summary"),
                    ("decisions", "decision", "decision", "reasoning"),
                    ("entities", "entity", "name", "name"),
                    ("projects", "project", "title", "project_path"),
                ):
                    row = conn.execute(
                        f"SELECT * FROM {table} WHERE upper(id) = ? LIMIT 1", (identifier,)
                    ).fetchone()
                    if row is not None:
                        object_id = str(row["id"])
                        candidates[object_id] = SearchHit(
                            object_id=object_id,
                            object_type=object_type,
                            title=str(row[title_column]),
                            text=str(row[text_column] or row[title_column]),
                            score=1.0,
                            source_id=(
                                object_id
                                if object_type == "source"
                                else self._source_from_metadata(row)
                            ),
                            updated_at=self._updated_at(row),
                            metadata={"channel": "metadata", "exact_identifier": True},
                        )

            for hash_value in hashes:
                rows = conn.execute(
                    "SELECT * FROM sources WHERE lower(content_hash) LIKE ? LIMIT ?",
                    (f"{hash_value}%", limit),
                ).fetchall()
                for row in rows:
                    object_id = str(row["id"])
                    candidates[object_id] = SearchHit(
                        object_id=object_id,
                        object_type="source",
                        title=str(row["title"]),
                        text=f"{row['original_filename']}\n{row['original_path']}",
                        score=1.0,
                        source_id=object_id,
                        updated_at=self._updated_at(row),
                        metadata={"channel": "metadata", "hash_prefix": hash_value},
                    )

            if query_lower:
                filename_rows = conn.execute(
                    """
                    SELECT * FROM sources
                    WHERE lower(original_filename) = ? OR lower(original_path) LIKE ?
                    ORDER BY ingested_at DESC LIMIT ?
                    """,
                    (query_lower, f"%{query_lower}%", limit),
                ).fetchall()
                for row in filename_rows:
                    object_id = str(row["id"])
                    candidates.setdefault(
                        object_id,
                        SearchHit(
                            object_id=object_id,
                            object_type="source",
                            title=str(row["title"]),
                            text=f"{row['original_filename']}\n{row['original_path']}",
                            score=0.9,
                            source_id=object_id,
                            updated_at=self._updated_at(row),
                            metadata={"channel": "metadata", "path_match": True},
                        ),
                    )

                project_rows = conn.execute(
                    "SELECT * FROM projects WHERE lower(title) LIKE ? ORDER BY updated_at DESC LIMIT ?",
                    (f"%{query_lower}%", limit),
                ).fetchall()
                for row in project_rows:
                    object_id = str(row["id"])
                    candidates.setdefault(
                        object_id,
                        SearchHit(
                            object_id=object_id,
                            object_type="project",
                            title=str(row["title"]),
                            text=str(row["project_path"]),
                            score=0.85,
                            updated_at=self._updated_at(row),
                            metadata={"channel": "metadata", "project_match": True},
                        ),
                    )

                state_rows = conn.execute(
                    """
                    SELECT ps.*, p.title AS project_title
                    FROM project_states ps
                    JOIN projects p ON p.id = ps.project_id
                    WHERE lower(ps.current_state) LIKE ?
                       OR lower(COALESCE(ps.next_action, '')) LIKE ?
                       OR lower(p.title) LIKE ?
                    ORDER BY ps.active DESC, ps.created_at DESC
                    LIMIT ?
                    """,
                    (
                        f"%{query_lower}%",
                        f"%{query_lower}%",
                        f"%{query_lower}%",
                        limit,
                    ),
                ).fetchall()
                for row in state_rows:
                    active = bool(row["active"])
                    object_id = (
                        f"PST-{str(row['project_id'])[4:]}"
                        if active
                        else f"PSTH-{row['id']}"
                    )
                    try:
                        evidence = json.loads(str(row["evidence_json"] or "[]"))
                    except json.JSONDecodeError:
                        evidence = []
                    source_id = next(
                        (
                            str(value)
                            for value in evidence
                            if isinstance(value, str) and value.startswith("SRC-")
                        ),
                        None,
                    ) if isinstance(evidence, list) else None
                    candidates.setdefault(
                        object_id,
                        SearchHit(
                            object_id=object_id,
                            object_type="project-state" if active else "project-state-history",
                            title=f"{row['project_title']} — {'Current' if active else 'Historical'} State",
                            text=(
                                f"Current state: {row['current_state']}\n"
                                f"Next action: {row['next_action'] or ''}"
                            ),
                            score=0.95 if active else 0.72,
                            source_id=source_id,
                            updated_at=self._updated_at(row),
                            metadata={
                                "channel": "metadata",
                                "project_id": str(row["project_id"]),
                                "active": active,
                                "evidence": evidence if isinstance(evidence, list) else [],
                            },
                        ),
                    )

        return sorted(candidates.values(), key=lambda item: item.score, reverse=True)[:limit]

    @staticmethod
    def _source_from_metadata(row) -> str | None:  # type: ignore[no-untyped-def]
        try:
            import json

            payload = json.loads(str(row["metadata_json"] or "{}"))
        except (KeyError, TypeError, ValueError):
            return None
        values = payload.get("source_ids", []) if isinstance(payload, dict) else []
        return str(values[0]) if isinstance(values, list) and values else None

    @staticmethod
    def _updated_at(row) -> datetime | None:  # type: ignore[no-untyped-def]
        keys = set(row.keys())
        for key in ("updated_at", "ingested_at", "created_at", "decided_at"):
            if key in keys and row[key]:
                try:
                    return datetime.fromisoformat(str(row[key]))
                except ValueError:
                    continue
        return None
