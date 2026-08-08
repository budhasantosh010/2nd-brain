"""Canonical project creation, current-state history and handoff maintenance."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import yaml

from second_brain.config import load_config
from second_brain.embeddings.factory import create_embedding_provider
from second_brain.models import PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.review.service import ReviewService
from second_brain.storage.durable import ProjectStateEvent, append_jsonl_event
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore
from second_brain.transactions.db_mutations import DatabaseMutationPlan, DatabaseRowScope
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan

SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) or "_None._"


@dataclass(slots=True)
class ProjectSpec:
    title: str
    goal: str
    desired_outcome: str = ""
    success_criteria: list[str] = field(default_factory=list)
    scope: str = ""
    constraints: list[str] = field(default_factory=list)
    related_areas: list[str] = field(default_factory=list)
    important_resources: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProjectStateInput:
    current_state: str
    last_completed: str = ""
    currently_working_on: str = ""
    next_action: str = ""
    blockers: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    latest_verified_evidence: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


class ProjectService:
    def __init__(self, paths: BrainPaths | None = None, store: SQLiteStore | None = None) -> None:
        self.paths = paths or BrainPaths.discover()
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        self.transactions = TransactionManager(self.paths, self.store)
        self.reviews = ReviewService(self.paths, self.store, self.transactions)
        self.vectors = VectorStore(
            self.store,
            create_embedding_provider(load_config(self.paths), self.paths),
        )

    def create(self, spec: ProjectSpec) -> str:
        project_id = f"PRJ-{uuid4()}"
        folder = self._project_folder(spec.title, project_id)
        now = datetime.now(UTC)
        state = ProjectStateInput(
            current_state="Project created; no execution progress recorded yet.",
            next_action="Define or begin the first concrete action.",
            source_ids=spec.source_ids,
        )
        writes = [
            PlannedWrite(path=f"{folder}/PROJECT.md", content=self._render_project(project_id, spec, now)),
            PlannedWrite(path=f"{folder}/STATE.md", content=self._render_state(project_id, spec.title, state, now)),
            PlannedWrite(path=f"{folder}/DECISIONS.md", content="# Project Decisions\n\n_No decisions recorded._\n"),
            PlannedWrite(path=f"{folder}/OPEN LOOPS.md", content="# Open Loops\n\n_None recorded._\n"),
            PlannedWrite(path=f"{folder}/CONTEXT.md", content="# Project Context\n\n_No compiled context yet._\n"),
            PlannedWrite(path=f"{folder}/SOURCES.md", content=self._render_sources(spec.source_ids)),
            PlannedWrite(path=f"{folder}/HANDOFF.md", content=self._render_handoff(project_id, spec.title, spec, state, now)),
            PlannedWrite(path=f"{folder}/Inputs/.keep", content=""),
            PlannedWrite(path=f"{folder}/Working/.keep", content=""),
            PlannedWrite(path=f"{folder}/Outputs/.keep", content=""),
            PlannedWrite(path=f"{folder}/Feedback/.keep", content=""),
        ]
        plan = build_plan(f"Create project {spec.title}", writes, permission_level=1)
        event = self._state_event(
            project_id,
            state,
            operation_id=plan.operation_id,
            timestamp=now,
            status="created",
        )
        plan.metadata["project_state_event"] = event.model_dump(mode="json")

        def db_action(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO projects(id, title, status, project_path, created_at, updated_at, metadata_json)
                VALUES (?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    project_id,
                    spec.title,
                    folder,
                    now.isoformat(),
                    now.isoformat(),
                    json.dumps({"source_ids": spec.source_ids}, sort_keys=True),
                ),
            )
            conn.execute(
                """
                INSERT INTO project_states(
                    project_id, current_state, next_action, blockers_json, open_questions_json,
                    evidence_json, verified_at, created_at, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    project_id,
                    state.current_state,
                    state.next_action,
                    json.dumps(state.blockers),
                    json.dumps(state.open_questions),
                    json.dumps(state.latest_verified_evidence),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self._index_project_db(conn, project_id, spec.title, folder, spec.goal, state)

        self.transactions.apply(
            plan,
            db_action=db_action,
            db_plan=self._project_db_plan(project_id),
        )
        self._append_state_event(event)
        return project_id

    def update_state(
        self,
        project_id: str,
        state: ProjectStateInput,
        *,
        ambiguous: bool = False,
    ) -> str:
        project = self._get_project(project_id)
        folder = str(project["project_path"])
        title = str(project["title"])
        project_path = self.paths.vault / folder / "PROJECT.md"
        state_path = self.paths.vault / folder / "STATE.md"
        handoff_path = self.paths.vault / folder / "HANDOFF.md"
        spec = self._spec_from_project_file(project_path)
        now = datetime.now(UTC)
        writes = [
            PlannedWrite(
                path=f"{folder}/STATE.md",
                content=self._render_state(project_id, title, state, now),
                expected_hash=file_sha256(state_path) if state_path.exists() else None,
            ),
            PlannedWrite(
                path=f"{folder}/HANDOFF.md",
                content=self._render_handoff(project_id, title, spec, state, now),
                expected_hash=file_sha256(handoff_path) if handoff_path.exists() else None,
            ),
        ]
        plan = build_plan(f"Update current state for {title}", writes, permission_level=2 if ambiguous else 1)
        plan.metadata.update(
            {
                "project_state_update": {
                    "project_id": project_id,
                    "current_state": state.current_state,
                    "next_action": state.next_action,
                    "blockers": state.blockers,
                    "open_questions": state.open_questions,
                    "evidence": state.latest_verified_evidence,
                    "verified_at": now.isoformat(),
                }
            }
        )
        event = self._state_event(
            project_id,
            state,
            operation_id=plan.operation_id,
            timestamp=now,
            status="applied",
        )
        plan.metadata["project_state_event"] = event.model_dump(mode="json")
        if ambiguous:
            item = self.reviews.stage(
                plan,
                review_type="project-state-change",
                risk="high",
                proposal=f"Change important current state for project '{title}'.",
                reason="The evidence-to-state interpretation was marked ambiguous.",
                evidence=state.latest_verified_evidence,
                current_state=self.current_state(project_id).current_state,
                proposed_state=state.current_state,
                risks="Applying the wrong interpretation would make current-state retrieval misleading.",
                rollback="Restore prior STATE/HANDOFF from the operation history.",
            )
            return item.review_id

        def db_action(conn: sqlite3.Connection) -> None:
            self._write_state_db(conn, project_id, state, now)
            self._index_project_db(conn, project_id, title, folder, spec.goal, state)

        operation_id = self.transactions.apply(
            plan,
            db_action=db_action,
            db_plan=self._project_db_plan(project_id),
        )
        self._append_state_event(event)
        return operation_id

    def create_handoff(self, project_id: str) -> str:
        project = self._get_project(project_id)
        folder = str(project["project_path"])
        title = str(project["title"])
        spec = self._spec_from_project_file(self.paths.vault / folder / "PROJECT.md")
        state = self.current_state(project_id)
        target = self.paths.vault / folder / "HANDOFF.md"
        plan = build_plan(
            f"Refresh handoff for {title}",
            [
                PlannedWrite(
                    path=f"{folder}/HANDOFF.md",
                    content=self._render_handoff(project_id, title, spec, state, datetime.now(UTC)),
                    expected_hash=file_sha256(target) if target.exists() else None,
                )
            ],
            permission_level=1,
        )
        return self.transactions.apply(plan)

    def current_state(self, project_id: str) -> ProjectStateInput:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM project_states
                WHERE project_id = ? AND active = 1
                ORDER BY id DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Current project state not found: {project_id}")
        return ProjectStateInput(
            current_state=str(row["current_state"]),
            next_action=str(row["next_action"] or ""),
            blockers=[str(value) for value in json.loads(str(row["blockers_json"]))],
            open_questions=[str(value) for value in json.loads(str(row["open_questions_json"]))],
            latest_verified_evidence=[str(value) for value in json.loads(str(row["evidence_json"]))],
        )

    def history(self, project_id: str) -> list[dict[str, object]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM project_states WHERE project_id = ? ORDER BY id DESC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _write_state_db(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        state: ProjectStateInput,
        now: datetime,
    ) -> None:
        conn.execute("UPDATE project_states SET active = 0 WHERE project_id = ?", (project_id,))
        conn.execute(
            """
            INSERT INTO project_states(
                project_id, current_state, next_action, blockers_json, open_questions_json,
                evidence_json, verified_at, created_at, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                project_id,
                state.current_state,
                state.next_action,
                json.dumps(state.blockers),
                json.dumps(state.open_questions),
                json.dumps(state.latest_verified_evidence),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?", (now.isoformat(), project_id)
        )

    def _state_event(
        self,
        project_id: str,
        state: ProjectStateInput,
        *,
        operation_id: str,
        timestamp: datetime,
        status: str,
        compensates_event_id: str | None = None,
    ) -> ProjectStateEvent:
        return ProjectStateEvent(
            project_id=project_id,
            timestamp=timestamp.isoformat(),
            current_state=state.current_state,
            last_completed=state.last_completed,
            currently_working_on=state.currently_working_on,
            next_action=state.next_action,
            blockers=state.blockers,
            open_questions=state.open_questions,
            evidence=state.latest_verified_evidence,
            source_ids=state.source_ids,
            verified_at=timestamp.isoformat(),
            operation_id=operation_id,
            status=status,  # type: ignore[arg-type]
            compensates_event_id=compensates_event_id,
        )

    def _append_state_event(self, event: ProjectStateEvent) -> None:
        append_jsonl_event(
            self.paths.brain / "ledgers" / "projects" / f"{event.project_id}.jsonl",
            event.model_dump(mode="json"),
            event_id=event.event_id,
        )

    @staticmethod
    def _project_db_plan(project_id: str) -> DatabaseMutationPlan:
        state_id = f"PST-{project_id[4:]}"
        return DatabaseMutationPlan(
            scopes=[
                DatabaseRowScope(
                    table="projects",
                    where_sql="id = ?",
                    params=[project_id],
                    label=f"Project {project_id}",
                ),
                DatabaseRowScope(
                    table="project_states",
                    where_sql="project_id = ?",
                    params=[project_id],
                    label=f"Project state history {project_id}",
                ),
            ],
            fts_object_ids=[project_id, state_id],
            vector_object_ids=[project_id, state_id],
            description=f"Project logical state {project_id}",
        )

    def _index_project_db(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        title: str,
        folder: str,
        goal: str,
        state: ProjectStateInput,
    ) -> None:
        project_text = f"{title}\nGoal: {goal}"
        state_text = (
            f"{title}\nCurrent state: {state.current_state}\n"
            f"Last completed: {state.last_completed}\n"
            f"Currently working on: {state.currently_working_on}\n"
            f"Next action: {state.next_action}\n"
            f"Blockers: {'; '.join(state.blockers)}\n"
            f"Open questions: {'; '.join(state.open_questions)}"
        )
        self.store.index_text_in_connection(
            conn,
            object_id=project_id,
            object_type="project",
            title=title,
            text=project_text,
            locator=f"{folder}/PROJECT.md",
        )
        state_id = f"PST-{project_id[4:]}"
        evidence_source = next(
            (value for value in state.latest_verified_evidence if value.startswith("SRC-")),
            None,
        )
        self.store.index_text_in_connection(
            conn,
            object_id=state_id,
            object_type="project-state",
            title=f"{title} — Current State",
            text=state_text,
            source_id=evidence_source,
            locator=f"{folder}/STATE.md",
        )
        self.vectors.upsert_in_connection(
            conn,
            object_id=project_id,
            object_type="project",
            title=title,
            text=project_text,
            metadata={"project_id": project_id, "locator": f"{folder}/PROJECT.md"},
        )
        self.vectors.upsert_in_connection(
            conn,
            object_id=state_id,
            object_type="project-state",
            title=f"{title} — Current State",
            text=state_text,
            source_id=evidence_source,
            metadata={
                "project_id": project_id,
                "evidence": state.latest_verified_evidence,
                "locator": f"{folder}/STATE.md",
            },
        )

    def _get_project(self, project_id: str):  # type: ignore[no-untyped-def]
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        return row

    @staticmethod
    def _project_folder(title: str, project_id: str) -> str:
        safe = SAFE_NAME.sub("-", title).strip(" .-")[:80] or "Untitled Project"
        return f"04 Projects/Active Projects/{safe}--{project_id}"

    @staticmethod
    def _render_project(project_id: str, spec: ProjectSpec, now: datetime) -> str:
        metadata = {
            "id": project_id,
            "type": "project",
            "title": spec.title,
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "source_ids": spec.source_ids,
            "project_ids": [project_id],
            "tags": [],
        }
        header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
        return (
            f"---\n{header}\n---\n\n# {spec.title}\n\n"
            f"## Goal\n\n{spec.goal}\n\n"
            f"## Desired Outcome\n\n{spec.desired_outcome or '_Not specified._'}\n\n"
            f"## Success Criteria\n\n{_bullets(spec.success_criteria)}\n\n"
            f"## Scope\n\n{spec.scope or '_Not specified._'}\n\n"
            f"## Constraints\n\n{_bullets(spec.constraints)}\n\n"
            f"## Related Areas\n\n{_bullets(spec.related_areas)}\n\n"
            f"## Important Resources\n\n{_bullets(spec.important_resources)}\n"
        )

    @staticmethod
    def _render_state(project_id: str, title: str, state: ProjectStateInput, now: datetime) -> str:
        metadata = {
            "id": f"PST-{project_id[4:]}",
            "type": "project-state",
            "title": f"{title} — Current State",
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "source_ids": state.source_ids,
            "project_ids": [project_id],
            "tags": [],
        }
        header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
        return (
            f"---\n{header}\n---\n\n# Current Project State\n\n"
            f"## Current State\n\n{state.current_state}\n\n"
            f"## Last Completed\n\n{state.last_completed or '_None recorded._'}\n\n"
            f"## Currently Working On\n\n{state.currently_working_on or '_None recorded._'}\n\n"
            f"## Next Action\n\n{state.next_action or '_Not defined._'}\n\n"
            f"## Blockers\n\n{_bullets(state.blockers)}\n\n"
            f"## Open Questions\n\n{_bullets(state.open_questions)}\n\n"
            f"## Latest Verified Evidence\n\n{_bullets(state.latest_verified_evidence)}\n\n"
            f"## Last Verified Timestamp\n\n{now.isoformat()}\n"
        )

    @staticmethod
    def _render_sources(source_ids: list[str]) -> str:
        values = "\n".join(f"- `{value}`" for value in source_ids) or "_None linked yet._"
        return f"# Project Sources\n\n{values}\n"

    @staticmethod
    def _render_handoff(
        project_id: str,
        title: str,
        spec: ProjectSpec,
        state: ProjectStateInput,
        now: datetime,
    ) -> str:
        metadata = {
            "id": f"HOF-{project_id[4:]}",
            "type": "project-handoff",
            "title": f"{title} — Handoff",
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "source_ids": sorted(set(spec.source_ids + state.source_ids)),
            "project_ids": [project_id],
            "tags": [],
        }
        header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
        evidence = "\n".join(f"- `{value}`" for value in state.latest_verified_evidence) or "_None linked._"
        blockers = "\n".join(f"- {value}" for value in state.blockers) or "_None._"
        return (
            f"---\n{header}\n---\n\n# Project Handoff\n\n"
            f"## What are we doing?\n\n{spec.goal}\n\n"
            f"## Where exactly are we?\n\n{state.current_state}\n\n"
            f"## What has been completed?\n\n{state.last_completed or '_None recorded._'}\n\n"
            "## What decisions matter?\n\nSee `DECISIONS.md` and active structured decisions.\n\n"
            f"## What changed?\n\n{state.last_completed or 'Current state was refreshed.'}\n\n"
            f"## What evidence exists?\n\n{evidence}\n\n"
            f"## What is blocked?\n\n{blockers}\n\n"
            f"## What should happen next?\n\n{state.next_action or '_No next action defined._'}\n\n"
            "## What should NOT happen?\n\nDo not infer current state from older chats when this state/handoff has newer verified evidence.\n\n"
            "## How should another AI session resume?\n\nRead PROJECT.md, STATE.md, DECISIONS.md, OPEN LOOPS.md, CONTEXT.md, SOURCES.md, and this HANDOFF.md; then retrieve supporting brain evidence and check supersession/conflicts.\n"
        )

    @staticmethod
    def _spec_from_project_file(path) -> ProjectSpec:  # type: ignore[no-untyped-def]
        import frontmatter

        post = frontmatter.load(path)
        body = post.content

        def section(name: str) -> str:
            marker = f"## {name}"
            if marker not in body:
                return ""
            tail = body.split(marker, 1)[1]
            return tail.split("\n## ", 1)[0].strip()

        def bullet_values(value: str) -> list[str]:
            return [line[2:].strip() for line in value.splitlines() if line.startswith("- ")]

        source_values = post.metadata.get("source_ids", [])
        source_ids = [str(value) for value in source_values] if isinstance(source_values, list) else []
        return ProjectSpec(
            title=str(post.metadata.get("title", path.parent.name)),
            goal=section("Goal"),
            desired_outcome=section("Desired Outcome").replace("_Not specified._", ""),
            success_criteria=bullet_values(section("Success Criteria")),
            scope=section("Scope").replace("_Not specified._", ""),
            constraints=bullet_values(section("Constraints")),
            related_areas=bullet_values(section("Related Areas")),
            important_resources=bullet_values(section("Important Resources")),
            source_ids=source_ids,
        )
