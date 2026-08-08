"""Bounded one-hop relationship expansion."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from second_brain.models import SearchHit
from second_brain.storage.sqlite import SQLiteStore


class GraphRetriever:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def expand(self, hits: list[SearchHit], *, hops: int = 1, limit: int = 30) -> list[SearchHit]:
        if hops <= 0 or not hits:
            return []
        frontier = {hit.object_id for hit in hits[:limit]}
        seen = set(frontier)
        expanded: list[SearchHit] = []
        for hop in range(hops):
            if not frontier:
                break
            next_frontier: set[str] = set()
            with self.store.connect() as conn:
                for object_id in sorted(frontier):
                    rows = conn.execute(
                        """
                        SELECT * FROM relationships
                        WHERE from_id = ? OR to_id = ?
                        ORDER BY id
                        """,
                        (object_id, object_id),
                    ).fetchall()
                    for row in rows:
                        neighbor = str(row["to_id"] if row["from_id"] == object_id else row["from_id"])
                        if neighbor in seen:
                            continue
                        hit = self._resolve(conn, neighbor)
                        if hit is None:
                            continue
                        hit.score = 1.0 / (hop + 2)
                        hit.metadata.update(
                            {
                                "channel": "graph",
                                "graph_hop": hop + 1,
                                "relation": str(row["relation"]),
                                "via": object_id,
                            }
                        )
                        expanded.append(hit)
                        seen.add(neighbor)
                        next_frontier.add(neighbor)
                        if len(expanded) >= limit:
                            return expanded
            frontier = next_frontier
        return expanded

    @staticmethod
    def _resolve(conn, object_id: str) -> SearchHit | None:  # type: ignore[no-untyped-def]
        fts = conn.execute(
            "SELECT * FROM search_fts WHERE object_id = ? LIMIT 1", (object_id,)
        ).fetchone()
        if fts is not None:
            return SearchHit(
                object_id=object_id,
                object_type=str(fts["object_type"]),
                title=str(fts["title"]),
                text=str(fts["text"]),
                score=0.0,
                source_id=str(fts["source_id"]) if fts["source_id"] else None,
                locator=str(fts["locator"]) if fts["locator"] else None,
            )
        lookups: tuple[tuple[str, str, str, str], ...] = (
            ("concepts", "concept", "title", "summary"),
            ("claims", "claim", "statement", "statement"),
            ("entities", "entity", "name", "name"),
            ("decisions", "decision", "decision", "reasoning"),
            ("projects", "project", "title", "project_path"),
            ("sources", "source", "title", "original_path"),
        )
        for table, object_type, title_column, text_column in lookups:
            row = conn.execute(f"SELECT * FROM {table} WHERE id = ? LIMIT 1", (object_id,)).fetchone()
            if row is None:
                continue
            metadata: dict[str, Any] = {}
            if "metadata_json" in row and row["metadata_json"]:
                try:
                    value = json.loads(str(row["metadata_json"]))
                    if isinstance(value, dict):
                        metadata = value
                except json.JSONDecodeError:
                    pass
            updated: datetime | None = None
            for key in ("updated_at", "ingested_at", "created_at", "decided_at"):
                if key in row and row[key]:
                    try:
                        updated = datetime.fromisoformat(str(row[key]))
                        break
                    except ValueError:
                        continue
            return SearchHit(
                object_id=object_id,
                object_type=object_type,
                title=str(row[title_column]),
                text=str(row[text_column] or row[title_column]),
                score=0.0,
                source_id=object_id if object_type == "source" else None,
                updated_at=updated,
                metadata=metadata,
            )
        return None
