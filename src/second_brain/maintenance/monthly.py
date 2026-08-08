"""Monthly synthesis without destructive archival/deletion."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from second_brain.config import BrainConfig
from second_brain.models import PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan


class MonthlyMaintenance:
    def __init__(self, paths: BrainPaths, config: BrainConfig, store: SQLiteStore) -> None:
        self.paths = paths
        self.config = config
        self.store = store
        self.transactions = TransactionManager(paths, store)
        self.timezone = ZoneInfo(config.vault.timezone)

    def run(self) -> dict[str, object]:
        now = datetime.now(self.timezone)
        with self.store.connect() as conn:
            completed = conn.execute(
                "SELECT id, title FROM projects WHERE status IN ('complete','completed','closed') ORDER BY updated_at DESC"
            ).fetchall()
            stale = conn.execute(
                """
                SELECT id, title, updated_at FROM projects
                WHERE status = 'active' AND julianday('now') - julianday(updated_at) > 60
                ORDER BY updated_at
                """
            ).fetchall()
            concepts = conn.execute(
                "SELECT title, COUNT(*) AS count FROM concepts GROUP BY lower(title) ORDER BY count DESC, title LIMIT 30"
            ).fetchall()
            conflicts = conn.execute(
                "SELECT left_id, right_id, explanation FROM conflicts WHERE status = 'open'"
            ).fetchall()
            open_questions = conn.execute(
                "SELECT id, question FROM questions WHERE status = 'open' ORDER BY created_at"
            ).fetchall()
        rel = f"08 Briefs/Monthly/{now.year}-{now.month:02d}.md"
        lines = [
            "---",
            "type: brief",
            f"title: Monthly Synthesis {now.year}-{now.month:02d}",
            "status: generated",
            f"created_at: {now.isoformat()}",
            f"updated_at: {now.isoformat()}",
            "source_ids: []",
            "project_ids: []",
            "tags: []",
            "---",
            "",
            f"# Monthly Synthesis — {now.year}-{now.month:02d}",
            "",
            "## Completed Projects — Archive Candidates",
            "",
        ]
        lines.extend(f"- `{row['id']}` — {row['title']}" for row in completed)
        if not completed:
            lines.append("_None._")
        lines.extend(["", "## Potentially Abandoned / Stale Projects", ""])
        lines.extend(f"- `{row['id']}` — {row['title']} — last update {row['updated_at']}" for row in stale)
        if not stale:
            lines.append("_None detected._")
        lines.extend(["", "## Emerging / Repeated Knowledge Clusters", ""])
        lines.extend(f"- {row['title']} — {row['count']} compiled record(s)" for row in concepts)
        if not concepts:
            lines.append("_No compiled concepts yet._")
        lines.extend(["", "## Stale / Conflicting Assumptions", ""])
        lines.extend(f"- `{row['left_id']}` ↔ `{row['right_id']}` — {row['explanation']}" for row in conflicts)
        if not conflicts:
            lines.append("_No open conflicts recorded._")
        lines.extend(["", "## Persistent Knowledge Gaps", ""])
        lines.extend(f"- `{row['id']}` — {row['question']}" for row in open_questions)
        if not open_questions:
            lines.append("_None._")
        lines.extend(
            [
                "",
                "## Higher-Level Structural Changes",
                "",
                "Any canonical archive move, merge, or meaning-changing structural change identified here must pass review policy. This synthesis never automatically deletes old knowledge.",
            ]
        )
        target = self.paths.vault / rel
        plan = build_plan(
            "Monthly synthesis",
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
            "archive_candidates": len(completed),
            "stale_projects": len(stale),
            "open_questions": len(open_questions),
        }
