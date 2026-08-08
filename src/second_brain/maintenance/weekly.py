"""Weekly audit and synthesis."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from second_brain.config import BrainConfig
from second_brain.knowledge.restructuring import RestructuringService
from second_brain.models import PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan


class WeeklyMaintenance:
    def __init__(self, paths: BrainPaths, config: BrainConfig, store: SQLiteStore) -> None:
        self.paths = paths
        self.config = config
        self.store = store
        self.transactions = TransactionManager(paths, store)
        self.restructuring = RestructuringService(paths, config, store)
        self.timezone = ZoneInfo(config.vault.timezone)

    def run(self) -> dict[str, object]:
        now = datetime.now(self.timezone)
        staged_restructuring = self.restructuring.generate_proposals(limit=5)
        report = self.restructuring.analyze()
        with self.store.connect() as conn:
            projects_without_next = conn.execute(
                """
                SELECT p.id, p.title FROM projects p
                LEFT JOIN project_states ps ON ps.project_id = p.id AND ps.active = 1
                WHERE p.status = 'active' AND (ps.next_action IS NULL OR trim(ps.next_action) = '')
                """
            ).fetchall()
            unresolved_reviews = conn.execute(
                "SELECT review_id, type, risk FROM review_items WHERE status = 'pending'"
            ).fetchall()
            conflicts = conn.execute(
                "SELECT id, left_id, right_id, explanation FROM conflicts WHERE status = 'open'"
            ).fetchall()
            failures = conn.execute(
                """
                SELECT error_type, COUNT(*) AS count FROM processing_jobs
                WHERE state IN ('FAILED','QUARANTINED') GROUP BY error_type ORDER BY count DESC
                """
            ).fetchall()
        year, week, _ = now.isocalendar()
        rel = f"08 Briefs/Weekly/{year}-W{week:02d}.md"
        lines = [
            "---",
            "type: brief",
            f"title: Weekly Audit {year}-W{week:02d}",
            "status: generated",
            f"created_at: {now.isoformat()}",
            f"updated_at: {now.isoformat()}",
            "source_ids: []",
            "project_ids: []",
            "tags: []",
            "---",
            "",
            f"# Weekly Audit — {year}-W{week:02d}",
            "",
            "## Structural Metrics",
            "",
        ]
        lines.extend(f"- {key}: {value}" for key, value in sorted(report.metrics.items()))
        lines.extend(["", "## Duplicate Concept Candidates", ""])
        lines.extend(f"- {title}: {count} notes" for title, count in report.duplicate_titles)
        if not report.duplicate_titles:
            lines.append("_None detected._")
        lines.extend(["", "## Orphan / Broken Relationships", ""])
        lines.extend(f"- Broken relationship `{value}`" for value in report.broken_relationships)
        if not report.broken_relationships:
            lines.append("_No broken relationships detected._")
        lines.extend(["", "## Stale Projects", ""])
        lines.extend(f"- `{value}`" for value in report.stale_projects)
        if not report.stale_projects:
            lines.append("_None detected._")
        lines.extend(["", "## Projects Without Next Action", ""])
        lines.extend(f"- `{row['id']}` — {row['title']}" for row in projects_without_next)
        if not projects_without_next:
            lines.append("_None._")
        lines.extend(["", "## Unresolved Review Items", ""])
        lines.extend(f"- `{row['review_id']}` — {row['type']} ({row['risk']})" for row in unresolved_reviews)
        if not unresolved_reviews:
            lines.append("_None._")
        lines.extend(["", "## Conflicting Claims / Decisions", ""])
        lines.extend(
            f"- `{row['left_id']}` ↔ `{row['right_id']}` — {row['explanation']}" for row in conflicts
        )
        if not conflicts:
            lines.append("_None recorded._")
        lines.extend(["", "## Processing Failure Patterns", ""])
        lines.extend(f"- {row['error_type'] or 'unknown'}: {row['count']}" for row in failures)
        if not failures:
            lines.append("_None._")
        lines.extend(
            [
                "",
                "## Restructuring",
                "",
                "Generated maps/indexes may rebuild automatically. Concept merges, hierarchy changes, or meaning-changing moves must be staged for review rather than applied from this audit.",
            ]
        )
        target = self.paths.vault / rel
        plan = build_plan(
            "Weekly audit synthesis",
            [
                PlannedWrite(
                    path=rel,
                    content="\n".join(lines).rstrip() + "\n",
                    expected_hash=file_sha256(target) if target.exists() else None,
                )
            ],
            permission_level=1,
        )
        self.transactions.apply(plan)
        return {
            "brief": rel,
            "duplicate_candidates": len(report.duplicate_titles),
            "broken_relationships": len(report.broken_relationships),
            "stale_projects": len(report.stale_projects),
            "pending_reviews": len(unresolved_reviews),
            "restructuring_proposals": len(staged_restructuring),
        }
