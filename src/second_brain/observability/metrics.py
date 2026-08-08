"""Computed operational metrics from generated SQLite state."""

from __future__ import annotations

from typing import Any

from second_brain.storage.sqlite import SQLiteStore


def collect_metrics(store: SQLiteStore) -> dict[str, Any]:
    queries = {
        "sources": "SELECT COUNT(*) FROM sources",
        "concepts": "SELECT COUNT(*) FROM concepts",
        "claims": "SELECT COUNT(*) FROM claims",
        "projects": "SELECT COUNT(*) FROM projects WHERE status = 'active'",
        "pending_reviews": "SELECT COUNT(*) FROM review_items WHERE status = 'pending'",
        "open_questions": "SELECT COUNT(*) FROM questions WHERE status = 'open'",
        "open_conflicts": "SELECT COUNT(*) FROM conflicts WHERE status = 'open'",
        "failed_jobs": "SELECT COUNT(*) FROM processing_jobs WHERE state IN ('FAILED','QUARANTINED')",
        "needs_ai": "SELECT COUNT(*) FROM processing_jobs WHERE state = 'NEEDS_AI'",
        "retrieval_events": "SELECT COUNT(*) FROM retrieval_events",
    }
    result: dict[str, Any] = {}
    with store.connect() as conn:
        for name, sql in queries.items():
            result[name] = int(conn.execute(sql).fetchone()[0])
        total = int(conn.execute("SELECT COUNT(*) FROM retrieval_events").fetchone()[0])
        unanswered = int(
            conn.execute("SELECT COUNT(*) FROM retrieval_events WHERE answered = 0").fetchone()[0]
        )
        result["retrieval_failure_rate"] = unanswered / total if total else 0.0
        orphans = conn.execute(
            """
            SELECT COUNT(*) FROM concepts c
            WHERE NOT EXISTS (
                SELECT 1 FROM relationships r WHERE r.from_id = c.id OR r.to_id = c.id
            )
            """
        ).fetchone()[0]
        result["orphan_concepts"] = int(orphans)
    return result
