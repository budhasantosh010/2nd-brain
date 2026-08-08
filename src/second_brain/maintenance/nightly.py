"""Idempotent nightly processing, dashboards, handoffs and daily brief."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from second_brain.config import BrainConfig
from second_brain.ingest.archive import discover_folder_files
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.compiler import KnowledgeCompiler
from second_brain.knowledge.graph_materializer import MarkdownGraphMaterializer
from second_brain.knowledge.maps import MapGenerator
from second_brain.knowledge.projects import ProjectService
from second_brain.maintenance.health import verify_source_integrity
from second_brain.models import PlannedWrite, ProcessingState
from second_brain.observability.metrics import collect_metrics
from second_brain.paths import BrainPaths
from second_brain.providers import create_provider
from second_brain.review.service import ReviewService
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan
from second_brain.verification.service import VerificationService


class NightlyMaintenance:
    def __init__(self, paths: BrainPaths, config: BrainConfig, store: SQLiteStore) -> None:
        self.paths = paths
        self.config = config
        self.store = store
        self.ingestion = IngestionService(paths, config, store)
        self.compiler = KnowledgeCompiler(paths, config, store)
        self.projects = ProjectService(paths, store)
        self.reviews = ReviewService(paths, store)
        self.verification = VerificationService(paths, store)
        self.transactions = TransactionManager(paths, store)
        self.graph_materializer = MarkdownGraphMaterializer(paths, store)
        self.maps = MapGenerator(paths, store)
        self.timezone = ZoneInfo(config.vault.timezone)

    def run(self) -> dict[str, object]:
        ingested = self.process_inbox()
        compiled = self.retry_ai_work()
        refreshed_handoffs = self.refresh_handoffs()
        self.verification.refresh_unanswered_dashboard()
        self.reviews.refresh_dashboard()
        writes = self._dashboard_writes()
        writes.append(self._daily_brief_write())
        plan = build_plan("Nightly generated dashboards and daily brief", writes, permission_level=1)
        self.transactions.apply(plan)
        graph = self.graph_materializer.materialize()
        maps = self.maps.generate()
        integrity = verify_source_integrity(self.store, limit=25)
        corrupt = [finding.source_id for finding in integrity if not finding.ok]
        return {
            "ingested": ingested,
            "compiled": compiled,
            "handoffs": refreshed_handoffs,
            "graph": graph,
            "maps": maps,
            "integrity_checked": len(integrity),
            "corrupt_sources": corrupt,
        }

    def process_inbox(self) -> int:
        if not self.paths.inbox.exists():
            return 0
        count = 0
        files = sorted(discover_folder_files(self.paths.inbox))
        for path in files:
            if path.name.startswith(".") or path.name == "DROP FILES HERE.md":
                continue
            results = self.ingestion.ingest(path)
            count += sum(
                1
                for result in results
                if result.state
                not in {ProcessingState.DUPLICATE, ProcessingState.QUARANTINED, ProcessingState.FAILED}
            )
        return count

    def retry_ai_work(self) -> int:
        provider = create_provider(self.config)
        if provider is None or not provider.health_check().available:
            return 0
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT source_id FROM processing_jobs WHERE state = 'NEEDS_AI' AND source_id IS NOT NULL"
            ).fetchall()
        compiled = 0
        for row in rows:
            result = self.compiler.compile_source(str(row["source_id"]))
            if result.state in {ProcessingState.COMPLETE, ProcessingState.NEEDS_REVIEW}:
                compiled += 1
        return compiled

    def refresh_handoffs(self) -> int:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT id FROM projects WHERE status = 'active'").fetchall()
        refreshed = 0
        for row in rows:
            try:
                self.projects.create_handoff(str(row["id"]))
                refreshed += 1
            except (KeyError, FileNotFoundError):
                continue
        return refreshed

    def _dashboard_writes(self) -> list[PlannedWrite]:
        now = datetime.now(self.timezone)
        with self.store.connect() as conn:
            jobs = conn.execute(
                "SELECT * FROM processing_jobs ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()
            sources = conn.execute(
                "SELECT * FROM sources ORDER BY ingested_at DESC LIMIT 200"
            ).fetchall()
            projects = conn.execute(
                "SELECT * FROM projects WHERE status = 'active' ORDER BY updated_at DESC"
            ).fetchall()
            states = conn.execute(
                """
                SELECT ps.*, p.title FROM project_states ps
                JOIN projects p ON p.id = ps.project_id
                WHERE ps.active = 1 ORDER BY ps.created_at DESC
                """
            ).fetchall()
            loops = conn.execute(
                "SELECT * FROM open_loops WHERE status = 'open' ORDER BY created_at DESC"
            ).fetchall()
            decisions = conn.execute(
                "SELECT * FROM decisions ORDER BY decided_at DESC, rowid DESC LIMIT 100"
            ).fetchall()
            conflicts = conn.execute(
                "SELECT * FROM conflicts WHERE status = 'open' ORDER BY created_at DESC"
            ).fetchall()
            questions = conn.execute(
                "SELECT * FROM questions WHERE status = 'open' ORDER BY created_at DESC"
            ).fetchall()
        metrics = collect_metrics(self.store)

        processing_lines = ["# Processing Status", "", "> Generated from durable processing jobs.", ""]
        for state in ("FAILED", "QUARANTINED", "NEEDS_AI", "NEEDS_REVIEW", "COMPLETE"):
            processing_lines.extend([f"## {state}", ""])
            matched = [row for row in jobs if str(row["state"]) == state]
            if not matched:
                processing_lines.append("_None._")
            else:
                for row in matched[:30]:
                    detail = f" — {row['error_type']}: {row['error_message']}" if row["error_type"] else ""
                    processing_lines.append(f"- `{row['id']}` `{row['source_id'] or ''}` {row['input_path']}{detail}")
            processing_lines.append("")

        source_lines = ["# Source Index", "", "> Generated index of preserved sources.", ""]
        source_lines.extend(
            f"- `{row['id']}` — {row['title']} — {row['status']} — `{row['original_filename']}`"
            for row in sources
        )
        if not sources:
            source_lines.append("_No sources ingested yet._")

        project_lines = ["# Project Index", "", "## Active Projects", ""]
        project_lines.extend(
            f"- `{row['id']}` — **{row['title']}** — `{row['project_path']}`" for row in projects
        )
        if not projects:
            project_lines.append("_None yet._")

        current_lines = ["# Current Operations", "", f"> Generated {now.isoformat()}", "", "## Active Projects", ""]
        for row in states:
            current_lines.extend(
                [
                    f"### {row['title']} (`{row['project_id']}`)",
                    "",
                    str(row["current_state"]),
                    "",
                    f"Next: {row['next_action'] or '_not defined_'}",
                    "",
                ]
            )
        if not states:
            current_lines.append("_None._")

        loop_lines = ["# Open Loops", "", "> Generated cross-project view.", ""]
        loop_lines.extend(f"- {row['text']} (`{row['project_id'] or row['source_id'] or 'global'}`)" for row in loops)
        if not loops:
            loop_lines.append("_No open loops recorded._")

        decision_lines = ["# Recent Decisions", "", "> Generated newest-first view.", ""]
        decision_lines.extend(
            f"- `{row['id']}` — {row['decision']} — status: {row['status']}" for row in decisions
        )
        if not decisions:
            decision_lines.append("_No decisions recorded._")

        conflict_lines = ["# Contradictions", "", "> Conflicts are preserved rather than overwritten.", ""]
        conflict_lines.extend(
            f"- `{row['left_id']}` ↔ `{row['right_id']}` — {row['explanation']}" for row in conflicts
        )
        if not conflicts:
            conflict_lines.append("_None detected._")

        gap_lines = ["# Knowledge Gaps", "", "> Unanswered question → missing evidence → future matching source → resolved.", ""]
        gap_lines.extend(f"- `{row['id']}` — {row['question']} — missing: {row['missing_evidence']}" for row in questions)
        if not questions:
            gap_lines.append("_None recorded._")

        failed_lines = ["# Failed Processing", "", "> Generated from failed/quarantined jobs.", ""]
        failed = [row for row in jobs if str(row["state"]) in {"FAILED", "QUARANTINED"}]
        failed_lines.extend(
            f"- `{row['id']}` stage={row['stage']} error={row['error_type'] or 'unknown'} retry={row['retry_count']} next={row['next_action'] or ''}"
            for row in failed
        )
        if not failed:
            failed_lines.append("_None._")

        context_lines = ["# Current Context", "", f"> Generated {now.isoformat()}", "", "## Active Projects", ""]
        context_lines.extend(
            f"- **{row['title']}** — {row['current_state']} — Next: {row['next_action'] or 'not defined'}"
            for row in states[:10]
        )
        if not states:
            context_lines.append("_No active project state compiled yet._")

        brain_lines = ["# Brain Status", "", f"> Generated {now.isoformat()}", ""]
        brain_lines.extend(f"- {key}: {value}" for key, value in sorted(metrics.items()))

        pages = {
            "00 Home/Processing Status.md": "\n".join(processing_lines).rstrip() + "\n",
            "02 Sources/Source Index.md": "\n".join(source_lines).rstrip() + "\n",
            "04 Projects/PROJECT INDEX.md": "\n".join(project_lines).rstrip() + "\n",
            "07 Operations/CURRENT.md": "\n".join(current_lines).rstrip() + "\n",
            "07 Operations/Open Loops.md": "\n".join(loop_lines).rstrip() + "\n",
            "07 Operations/Tasks.md": "\n".join(loop_lines).replace("# Open Loops", "# Tasks", 1).rstrip() + "\n",
            "07 Operations/Recent Decisions.md": "\n".join(decision_lines).rstrip() + "\n",
            "07 Operations/Contradictions.md": "\n".join(conflict_lines).rstrip() + "\n",
            "07 Operations/Knowledge Gaps.md": "\n".join(gap_lines).rstrip() + "\n",
            "07 Operations/Stale Knowledge.md": "# Stale Knowledge\n\n> Generated candidates are flagged by verification/audits.\n\n_None currently marked stale._\n",
            "07 Operations/Failed Processing.md": "\n".join(failed_lines).rstrip() + "\n",
            "00 Home/Current Context.md": "\n".join(context_lines).rstrip() + "\n",
            "00 Home/Brain Status.md": "\n".join(brain_lines).rstrip() + "\n",
        }
        writes: list[PlannedWrite] = []
        for rel, content in pages.items():
            path = self.paths.vault / rel
            writes.append(
                PlannedWrite(
                    path=rel,
                    content=content,
                    expected_hash=file_sha256(path) if path.exists() else None,
                )
            )
        return writes

    def _daily_brief_write(self) -> PlannedWrite:
        now = datetime.now(self.timezone)
        rel = f"08 Briefs/Daily/{now.date().isoformat()}.md"
        with self.store.connect() as conn:
            states = conn.execute(
                """
                SELECT ps.*, p.title FROM project_states ps JOIN projects p ON p.id = ps.project_id
                WHERE ps.active = 1 ORDER BY ps.created_at DESC
                """
            ).fetchall()
            loops = conn.execute("SELECT * FROM open_loops WHERE status = 'open' ORDER BY created_at DESC LIMIT 20").fetchall()
            questions = conn.execute("SELECT * FROM questions WHERE status = 'open' ORDER BY created_at DESC LIMIT 10").fetchall()
            reviews = conn.execute("SELECT * FROM review_items WHERE status = 'pending' ORDER BY created_at LIMIT 10").fetchall()
            concepts = conn.execute("SELECT * FROM concepts ORDER BY updated_at DESC LIMIT 10").fetchall()
        lines = [
            "---",
            "type: brief",
            f"title: Daily Brief {now.date().isoformat()}",
            "status: generated",
            f"created_at: {now.isoformat()}",
            f"updated_at: {now.isoformat()}",
            "source_ids: []",
            "project_ids: []",
            "tags: []",
            "---",
            "",
            f"# Daily Brief — {now.date().isoformat()}",
            "",
            "## Main Priority",
            "",
            (f"{states[0]['title']}: {states[0]['next_action'] or states[0]['current_state']}" if states else "_No active project priority compiled._"),
            "",
            "## Active Projects",
            "",
        ]
        lines.extend(f"- **{row['title']}** — {row['current_state']}" for row in states)
        if not states:
            lines.append("_None._")
        lines.extend(["", "## Current State", ""])
        lines.extend(f"- {row['title']}: {row['current_state']}" for row in states)
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {row['title']}: {row['next_action'] or 'not defined'}" for row in states)
        lines.extend(["", "## Open Loops", ""])
        lines.extend(f"- {row['text']}" for row in loops)
        if not loops:
            lines.append("_None._")
        lines.extend(["", "## New Important Knowledge", ""])
        lines.extend(f"- {row['title']} — {row['summary']}" for row in concepts)
        if not concepts:
            lines.append("_None._")
        lines.extend(["", "## Knowledge Gaps", ""])
        lines.extend(f"- {row['question']}" for row in questions)
        if not questions:
            lines.append("_None._")
        lines.extend(["", "## Needs Review", ""])
        lines.extend(f"- `{row['review_id']}` — {row['type']} ({row['risk']})" for row in reviews)
        if not reviews:
            lines.append("_None._")
        lines.extend(["", "## Potentially Stalled Work", ""])
        stalled = [row for row in states if not row["next_action"]]
        lines.extend(f"- {row['title']} has no next action." for row in stalled)
        if not stalled:
            lines.append("_None detected._")
        path = self.paths.vault / rel
        return PlannedWrite(
            path=rel,
            content="\n".join(lines).rstrip() + "\n",
            expected_hash=file_sha256(path) if path.exists() else None,
        )
