"""Structural-friction analysis. Canonical mergers/moves remain staged."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from second_brain.observability.metrics import collect_metrics
from second_brain.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class RestructuringReport:
    metrics: dict[str, Any]
    duplicate_titles: list[tuple[str, int]]
    broken_relationships: list[str]
    stale_projects: list[str]


def analyze_structure(store: SQLiteStore) -> RestructuringReport:
    with store.connect() as conn:
        duplicates = conn.execute(
            """
            SELECT lower(title) AS normalized, COUNT(*) AS count
            FROM concepts GROUP BY lower(title) HAVING COUNT(*) > 1 ORDER BY count DESC
            """
        ).fetchall()
        all_ids: set[str] = set()
        for table in ("sources", "concepts", "claims", "entities", "projects", "decisions", "skills"):
            rows = conn.execute(f"SELECT id FROM {table}").fetchall()
            all_ids.update(str(row["id"]) for row in rows)
        relations = conn.execute("SELECT id, from_id, to_id FROM relationships").fetchall()
        broken = [
            str(row["id"])
            for row in relations
            if str(row["from_id"]) not in all_ids or str(row["to_id"]) not in all_ids
        ]
        stale_rows = conn.execute(
            """
            SELECT id FROM projects
            WHERE status = 'active' AND julianday('now') - julianday(updated_at) > 30
            ORDER BY updated_at
            """
        ).fetchall()
    return RestructuringReport(
        metrics=collect_metrics(store),
        duplicate_titles=[(str(row["normalized"]), int(row["count"])) for row in duplicates],
        broken_relationships=broken,
        stale_projects=[str(row["id"]) for row in stale_rows],
    )
