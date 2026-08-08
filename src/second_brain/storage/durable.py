"""Durable Phase 2.5 ledgers that survive deletion of generated SQLite/index state."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ConceptResolution(BaseModel):
    incoming_id: str
    canonical_id: str
    action: Literal[
        "created",
        "duplicate",
        "updated",
        "review_pending",
        "rejected",
        "rolled_back",
        "related",
        "conflict",
    ]
    evidence: list[str] = Field(default_factory=list)
    review_operation_id: str | None = None
    decision_operation_id: str | None = None


class CanonicalResolutionLedger(BaseModel):
    schema_version: str = "canonical-resolution-v1"
    source_id: str
    source_hash: str
    compiler_version: str = "phase2.5-v1"
    resolved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    concept_resolutions: list[ConceptResolution] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    open_loops: list[dict[str, Any]] = Field(default_factory=list)
    project_candidates: list[dict[str, Any]] = Field(default_factory=list)


class ProjectStateEvent(BaseModel):
    schema_version: str = "project-state-event-v1"
    event_id: str = Field(default_factory=lambda: f"PSE-{uuid4()}")
    project_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    current_state: str
    last_completed: str = ""
    currently_working_on: str = ""
    next_action: str = ""
    blockers: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    verified_at: str | None = None
    operation_id: str
    status: Literal["created", "applied", "rollback", "recovered", "migrated"] = "applied"
    compensates_event_id: str | None = None


class KnowledgeGapEvent(BaseModel):
    schema_version: str = "knowledge-gap-event-v1"
    event_id: str = Field(default_factory=lambda: f"KGE-{uuid4()}")
    question_id: str
    question: str
    event: Literal["opened", "candidate_evidence_found", "resolved", "reopened", "dismissed"]
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    missing_evidence: str = ""
    searched: list[str] = Field(default_factory=list)
    found: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    resolution_id: str | None = None
    answer: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    operation_id: str | None = None


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def read_resolution(path: Path) -> CanonicalResolutionLedger | None:
    if not path.exists():
        return None
    try:
        return CanonicalResolutionLedger.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render_resolution(ledger: CanonicalResolutionLedger) -> str:
    return json.dumps(ledger.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def update_concept_resolution(
    ledger: CanonicalResolutionLedger,
    *,
    incoming_id: str,
    canonical_id: str,
    action: str,
    decision_operation_id: str | None = None,
) -> CanonicalResolutionLedger:
    updated = ledger.model_copy(deep=True)
    for item in updated.concept_resolutions:
        if item.incoming_id == incoming_id and item.canonical_id == canonical_id:
            item.action = action  # type: ignore[assignment]
            item.decision_operation_id = decision_operation_id
            updated.resolved_at = datetime.now(UTC).isoformat()
            return updated
    raise KeyError(
        f"Concept resolution not found: incoming={incoming_id} canonical={canonical_id}"
    )


def append_jsonl_event(path: Path, payload: dict[str, Any], *, event_id: str) -> bool:
    """Append an immutable event idempotently using atomic replacement.

    Existing lines are copied byte-for-byte into the replacement; no prior event is edited.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    for line in existing.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and str(value.get("event_id")) == event_id:
            return False
    suffix = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(existing + suffix, encoding="utf-8")
    os.replace(temp, path)
    return True


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Expected JSON object at {path}:{line_number}")
        result.append(value)
    return result
