"""Policy-safe MCP write/proposal tools. No direct unrestricted filesystem mutation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from second_brain.config import BrainConfig
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.compiler import KnowledgeCompiler
from second_brain.knowledge.projects import ProjectService, ProjectStateInput
from second_brain.maintenance.nightly import NightlyMaintenance
from second_brain.models import PlannedWrite, ProcessingState
from second_brain.paths import BrainPaths
from second_brain.review.service import ReviewService
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.plan import build_plan

BLOCKED_PREFIXES = ("02 Sources/Raw", "10 System", ".brain")
BLOCKED_FILES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}


class BrainWriteTools:
    def __init__(self, paths: BrainPaths, config: BrainConfig, store: SQLiteStore) -> None:
        self.paths = paths
        self.config = config
        self.store = store
        self.ingestion = IngestionService(paths, config, store)
        self.compiler = KnowledgeCompiler(paths, config, store)
        self.projects = ProjectService(paths, store)
        self.reviews = ReviewService(paths, store)

    def ingest(self, path: str) -> list[dict[str, Any]]:
        results = self.ingestion.ingest(Path(path))
        output: list[dict[str, Any]] = []
        for result in results:
            item: dict[str, Any] = {
                "input_path": str(result.input_path),
                "source_id": result.source_id,
                "state": result.state.value,
                "message": result.message,
            }
            if result.source_id and result.state == ProcessingState.CLASSIFIED:
                compiled = self.compiler.compile_source(result.source_id)
                item["compile_state"] = compiled.state.value
                item["review_items"] = compiled.review_items
            output.append(item)
        return output

    def process_inbox(self) -> dict[str, int]:
        count = NightlyMaintenance(self.paths, self.config, self.store).process_inbox()
        return {"processed": count}

    def propose_update(
        self,
        relative_path: str,
        proposed_content: str,
        reason: str,
        evidence: list[str] | None = None,
        risk: str = "medium",
    ) -> dict[str, str]:
        raw = Path(relative_path)
        if raw.is_absolute() or ".." in raw.parts:
            raise ValueError("Proposed path must be relative to the vault without traversal")
        normalized = raw.as_posix().strip("/")
        if normalized in BLOCKED_FILES or any(
            normalized == prefix or normalized.startswith(f"{prefix}/") for prefix in BLOCKED_PREFIXES
        ):
            raise ValueError("This path is protected/blocked from generic MCP proposals")
        target = self.paths.vault / raw
        plan = build_plan(
            f"MCP proposed update to {normalized}",
            [
                PlannedWrite(
                    path=normalized,
                    content=proposed_content,
                    expected_hash=file_sha256(target) if target.exists() else None,
                )
            ],
            permission_level=2,
        )
        item = self.reviews.stage(
            plan,
            review_type="knowledge-update",
            risk=risk,
            proposal=f"Replace/update `{normalized}` with the staged content.",
            reason=reason,
            evidence=evidence or [],
            current_state=target.read_text(encoding="utf-8") if target.is_file() else "_File does not exist._",
            proposed_state=proposed_content,
            risks="Meaning-changing canonical update requested by an MCP client.",
            rollback="Transaction history preserves the previous file state.",
        )
        return {"review_id": item.review_id, "operation_id": item.operation_id, "status": item.status}

    def update_project_state(
        self,
        project_id: str,
        current_state: str,
        next_action: str = "",
        blockers: list[str] | None = None,
        open_questions: list[str] | None = None,
        evidence: list[str] | None = None,
        verified: bool = False,
    ) -> dict[str, str]:
        evidence_values = evidence or []
        state = ProjectStateInput(
            current_state=current_state,
            next_action=next_action,
            blockers=blockers or [],
            open_questions=open_questions or [],
            latest_verified_evidence=evidence_values,
            source_ids=[item for item in evidence_values if item.startswith("SRC-")],
        )
        # An MCP client cannot simply label an unsupported interpretation verified. Direct Level-1
        # state update requires explicit verified=True plus at least one stored evidence identifier.
        ambiguous = not (verified and bool(evidence_values))
        result = self.projects.update_state(project_id, state, ambiguous=ambiguous)
        return {
            "result_id": result,
            "mode": "applied" if not ambiguous else "staged_for_review",
        }

    def create_handoff(self, project_id: str) -> dict[str, str]:
        return {"operation_id": self.projects.create_handoff(project_id)}

    def review_list(self) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self.reviews.list(status="pending")]
