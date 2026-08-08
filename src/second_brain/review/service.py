"""Stage risky changes and apply/reject them through the transaction manager."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from second_brain.config import load_config
from second_brain.embeddings.local import LocalEmbeddingProvider
from second_brain.models import ConceptRecord, OperationPlan, PlannedWrite, ReviewItemModel
from second_brain.paths import BrainPaths
from second_brain.review.renderer import render_dashboard, render_review
from second_brain.storage.markdown import file_sha256
from second_brain.storage.repository import BrainRepository
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan


class ReviewService:
    def __init__(
        self,
        paths: BrainPaths | None = None,
        store: SQLiteStore | None = None,
        transactions: TransactionManager | None = None,
    ) -> None:
        self.paths = paths or BrainPaths.discover()
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        self.transactions = transactions or TransactionManager(self.paths, self.store)
        config = load_config(self.paths)
        self.vectors = VectorStore(
            self.store,
            LocalEmbeddingProvider(config.embeddings.dimensions),
        )

    def stage(
        self,
        proposed_plan: OperationPlan,
        *,
        review_type: str,
        risk: str,
        proposal: str,
        reason: str,
        evidence: list[str] | None = None,
        current_state: str = "",
        proposed_state: str = "",
        risks: str = "",
        rollback: str = "",
        recommendation: str = "Review the evidence and approve only if the meaning change is intended.",
    ) -> ReviewItemModel:
        if proposed_plan.permission_level != 2:
            proposed_plan.permission_level = 2
        item = ReviewItemModel(
            type=review_type,
            risk=risk,
            created_at=datetime.now(UTC),
            operation_id=proposed_plan.operation_id,
            affected_paths=[write.path for write in proposed_plan.writes],
            proposal=proposal,
            reason=reason,
            evidence=evidence or [],
            current_state=current_state,
            proposed_state=proposed_state,
            risks=risks,
            rollback=rollback,
            recommendation=recommendation,
        )
        proposal_path = self.paths.transactions / proposed_plan.operation_id / "proposal.json"
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_json(proposal_path, proposed_plan.model_dump(mode="json"))
        note_rel = self._review_note_rel(item)
        stage_plan = build_plan(
            f"Stage review item {item.review_id}",
            [PlannedWrite(path=note_rel, content=render_review(item))],
            permission_level=1,
        )

        def db_action(conn):  # type: ignore[no-untyped-def]
            conn.execute(
                """
                INSERT INTO review_items(
                    review_id, type, risk, status, created_at, operation_id,
                    affected_paths_json, decision, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.review_id,
                    item.type,
                    item.risk,
                    item.status,
                    item.created_at.isoformat(),
                    item.operation_id,
                    json.dumps(item.affected_paths),
                    item.decision,
                    json.dumps(item.model_dump(mode="json"), sort_keys=True),
                ),
            )

        self.transactions.apply(stage_plan, db_action=db_action)
        self.refresh_dashboard()
        return item

    def list(self, *, status: str | None = None) -> list[ReviewItemModel]:
        with self.store.connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT payload_json, status, decision FROM review_items WHERE status = ? ORDER BY created_at",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT payload_json, status, decision FROM review_items ORDER BY created_at"
                ).fetchall()
        result: list[ReviewItemModel] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            payload["status"] = str(row["status"])
            payload["decision"] = str(row["decision"])
            result.append(ReviewItemModel.model_validate(payload))
        return result

    def get(self, review_id: str) -> ReviewItemModel:
        for item in self.list():
            if item.review_id == review_id:
                return item
        raise KeyError(f"Review item not found: {review_id}")

    def approve(self, review_id: str) -> str:
        item = self.get(review_id)
        if item.status != "pending":
            raise ValueError(f"Review item is not pending: {review_id} ({item.status})")
        plan = self._load_proposal(item.operation_id)

        def db_action(conn):  # type: ignore[no-untyped-def]
            concept_payload = plan.metadata.get("concept_update")
            note_path = plan.metadata.get("note_path")
            if isinstance(concept_payload, dict) and isinstance(note_path, str):
                concept = ConceptRecord.model_validate(concept_payload)
                BrainRepository.upsert_concept_db(conn, concept, note_path)
            state_payload = plan.metadata.get("project_state_update")
            if isinstance(state_payload, dict):
                project_id = str(state_payload.get("project_id", ""))
                if project_id:
                    conn.execute(
                        "UPDATE project_states SET active = 0 WHERE project_id = ?",
                        (project_id,),
                    )
                    conn.execute(
                        """
                        INSERT INTO project_states(
                            project_id, current_state, next_action, blockers_json,
                            open_questions_json, evidence_json, verified_at, created_at, active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            project_id,
                            str(state_payload.get("current_state", "")),
                            str(state_payload.get("next_action", "")),
                            json.dumps(state_payload.get("blockers", [])),
                            json.dumps(state_payload.get("open_questions", [])),
                            json.dumps(state_payload.get("evidence", [])),
                            str(state_payload.get("verified_at", datetime.now(UTC).isoformat())),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                    conn.execute(
                        "UPDATE projects SET updated_at = ? WHERE id = ?",
                        (datetime.now(UTC).isoformat(), project_id),
                    )

        operation_id = self.transactions.apply(plan, db_action=db_action)
        self._refresh_indexes(plan)
        item.status = "applied"
        item.decision = "approved"
        self._persist_item_and_views(item)
        return operation_id

    def reject(self, review_id: str, decision: str = "rejected") -> None:
        item = self.get(review_id)
        if item.status != "pending":
            raise ValueError(f"Review item is not pending: {review_id} ({item.status})")
        item.status = "rejected"
        item.decision = decision
        self._persist_item_and_views(item)

    def rollback(self, review_id: str) -> None:
        item = self.get(review_id)
        if item.status != "applied":
            raise ValueError(f"Only applied review items can be rolled back: {review_id}")
        self.transactions.rollback(item.operation_id)
        item.status = "rolled_back"
        item.decision = "approved then rolled back"
        self._persist_item_and_views(item)

    def _refresh_indexes(self, plan: OperationPlan) -> None:
        concept_payload = plan.metadata.get("concept_update")
        note_path = plan.metadata.get("note_path")
        if isinstance(concept_payload, dict) and isinstance(note_path, str):
            concept = ConceptRecord.model_validate(concept_payload)
            text = f"{concept.title}\n{concept.summary}"
            source_id = concept.source_ids[0] if concept.source_ids else None
            self.store.index_text(
                object_id=concept.id,
                object_type="concept",
                title=concept.title,
                text=text,
                source_id=source_id,
                locator=note_path,
            )
            self.vectors.upsert(
                object_id=concept.id,
                object_type="concept",
                title=concept.title,
                text=text,
                source_id=source_id,
                metadata={
                    "source_ids": concept.source_ids,
                    "project_ids": concept.project_ids,
                    "verification_state": concept.verification_state.value,
                    "locator": note_path,
                },
            )

        state_payload = plan.metadata.get("project_state_update")
        if not isinstance(state_payload, dict):
            return
        project_id = str(state_payload.get("project_id", ""))
        if not project_id:
            return
        with self.store.connect() as conn:
            project = conn.execute(
                "SELECT title, project_path FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if project is None:
            return
        title = str(project["title"])
        state_text = (
            f"{title}\nCurrent state: {state_payload.get('current_state', '')}\n"
            f"Next action: {state_payload.get('next_action', '')}\n"
            f"Blockers: {'; '.join(str(value) for value in state_payload.get('blockers', []))}\n"
            f"Open questions: {'; '.join(str(value) for value in state_payload.get('open_questions', []))}"
        )
        evidence = state_payload.get("evidence", [])
        evidence_values = [str(value) for value in evidence] if isinstance(evidence, list) else []
        source_id = next((value for value in evidence_values if value.startswith("SRC-")), None)
        state_id = f"PST-{project_id[4:]}"
        locator = f"{project['project_path']}/STATE.md"
        self.store.index_text(
            object_id=state_id,
            object_type="project-state",
            title=f"{title} — Current State",
            text=state_text,
            source_id=source_id,
            locator=locator,
        )
        self.vectors.upsert(
            object_id=state_id,
            object_type="project-state",
            title=f"{title} — Current State",
            text=state_text,
            source_id=source_id,
            metadata={
                "project_id": project_id,
                "evidence": evidence_values,
                "locator": locator,
            },
        )

    def refresh_dashboard(self) -> None:
        content = render_dashboard(self.list())
        path = self.paths.vault / "00 Home" / "Needs Review.md"
        plan = build_plan(
            "Refresh Needs Review dashboard",
            [
                PlannedWrite(
                    path="00 Home/Needs Review.md",
                    content=content,
                    expected_hash=file_sha256(path) if path.exists() else None,
                )
            ],
            permission_level=1,
        )
        self.transactions.apply(plan)

    def _persist_item_and_views(self, item: ReviewItemModel) -> None:
        items = self.list()
        rendered_items = [item if current.review_id == item.review_id else current for current in items]
        note_rel = self._review_note_rel(item)
        note_path = self.paths.vault / note_rel
        dashboard_path = self.paths.vault / "00 Home" / "Needs Review.md"
        plan = build_plan(
            f"Update review state {item.review_id}",
            [
                PlannedWrite(
                    path=note_rel,
                    content=render_review(item),
                    expected_hash=file_sha256(note_path) if note_path.exists() else None,
                ),
                PlannedWrite(
                    path="00 Home/Needs Review.md",
                    content=render_dashboard(rendered_items),
                    expected_hash=(
                        file_sha256(dashboard_path) if dashboard_path.exists() else None
                    ),
                ),
            ],
            permission_level=1,
        )

        def db_action(conn):  # type: ignore[no-untyped-def]
            conn.execute(
                "UPDATE review_items SET status = ?, decision = ?, payload_json = ? WHERE review_id = ?",
                (
                    item.status,
                    item.decision,
                    json.dumps(item.model_dump(mode="json"), sort_keys=True),
                    item.review_id,
                ),
            )

        self.transactions.apply(plan, db_action=db_action)

    def _load_proposal(self, operation_id: str) -> OperationPlan:
        path = self.paths.transactions / operation_id / "proposal.json"
        if not path.exists():
            raise FileNotFoundError(f"Review proposal is missing: {path}")
        return OperationPlan.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _review_bucket(review_type: str) -> str:
        lowered = review_type.lower()
        if "restruct" in lowered or "merge" in lowered:
            return "Restructuring"
        if "project" in lowered:
            return "Project Changes"
        if "system" in lowered or "identity" in lowered:
            return "System Changes"
        return "Knowledge Changes"

    def _review_note_rel(self, item: ReviewItemModel) -> str:
        return f"12 Staging/{self._review_bucket(item.type)}/{item.review_id}.md"

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(path)
