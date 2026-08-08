"""Validated domain models shared across ingestion, knowledge, retrieval and review."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ProcessingState(StrEnum):
    DETECTED = "DETECTED"
    HASHED = "HASHED"
    PRESERVED = "PRESERVED"
    EXTRACTED = "EXTRACTED"
    CLASSIFIED = "CLASSIFIED"
    COMPILED = "COMPILED"
    INDEXED = "INDEXED"
    VERIFIED = "VERIFIED"
    COMPLETE = "COMPLETE"
    DUPLICATE = "DUPLICATE"
    NEEDS_AI = "NEEDS_AI"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class VerificationState(StrEnum):
    VERIFIED = "verified"
    SUPPORTED = "supported"
    PROVISIONAL = "provisional"
    UNCERTAIN = "uncertain"
    CONTRADICTED = "contradicted"
    STALE = "stale"


class Sensitivity(StrEnum):
    LOCAL_ONLY = "local_only"
    CLOUD_ALLOWED = "cloud_allowed"
    SENSITIVE = "sensitive"
    BLOCKED = "blocked"


class RelationshipType(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived-from"
    RELATED_TO = "related-to"
    PART_OF = "part-of"
    APPLIES_TO = "applies-to"
    CREATED_BY = "created-by"
    MENTIONS = "mentions"
    DEPENDS_ON = "depends-on"
    RESULT_OF = "result-of"


class QueryType(StrEnum):
    EXACT = "EXACT"
    CURRENT_STATE = "CURRENT_STATE"
    HISTORICAL = "HISTORICAL"
    CONCEPTUAL = "CONCEPTUAL"
    CROSS_PROJECT = "CROSS_PROJECT"
    DECISION = "DECISION"
    SOURCE_LOOKUP = "SOURCE_LOOKUP"


class CanonicalFrontmatter(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    title: str
    status: str = "provisional"
    created_at: datetime
    updated_at: datetime
    source_ids: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class SourceRecord(BaseModel):
    id: str
    type: Literal["source"] = "source"
    source_type: str
    title: str
    original_filename: str
    original_path: str
    content_hash: str
    size_bytes: int
    created_at: datetime | None = None
    ingested_at: datetime
    status: ProcessingState
    authority: str = "unknown"
    sensitivity: Sensitivity = Sensitivity.LOCAL_ONLY
    project_ids: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    raw_path: str | None = None
    extracted_path: str | None = None


class ParsedSegment(BaseModel):
    segment_id: str
    text: str
    locator: str
    position: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    source_id: str
    title: str
    mime_type: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    segments: list[ParsedSegment] = Field(default_factory=list)


class EntityRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"ENT-{uuid4()}")
    name: str
    entity_type: str
    source_ids: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)


class ClaimRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"CLM-{uuid4()}")
    statement: str
    status: str = "active"
    confidence_state: VerificationState = VerificationState.PROVISIONAL
    source_id: str
    source_locator: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    project_ids: list[str] = Field(default_factory=list)
    materialize: bool = False


class DecisionRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"DEC-{uuid4()}")
    project_id: str | None = None
    decision: str
    context: str = ""
    reasoning: str = ""
    status: str = "active"
    decided_at: datetime | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class ConceptRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"KNO-{uuid4()}")
    title: str
    summary: str
    status: str = "provisional"
    verification_state: VerificationState = VerificationState.PROVISIONAL
    source_ids: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ProjectCandidate(BaseModel):
    name: str
    rationale: str
    confidence_state: VerificationState = VerificationState.PROVISIONAL


class OpenLoopRecord(BaseModel):
    text: str
    project_id: str | None = None
    source_id: str | None = None
    status: str = "open"


class KnowledgeExtraction(BaseModel):
    purpose: str = ""
    entities: list[EntityRecord] = Field(default_factory=list)
    project_candidates: list[ProjectCandidate] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    concepts: list[ConceptRecord] = Field(default_factory=list)
    open_loops: list[OpenLoopRecord] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class RelationshipRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"REL-{uuid4()}")
    from_id: str
    to_id: str
    relation: RelationshipType
    source_id: str | None = None
    provisional: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    source_id: str
    locator: str | None = None
    title: str
    excerpt: str
    authority: str = "unknown"
    verification_state: VerificationState = VerificationState.SUPPORTED


class BrainAnswer(BaseModel):
    answer: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    query_type: QueryType = QueryType.CONCEPTUAL


class ReviewItemModel(BaseModel):
    review_id: str = Field(default_factory=lambda: f"RVW-{uuid4()}")
    type: str
    risk: str
    status: Literal[
        "pending", "approved", "rejected", "applied", "expired", "rolled_back"
    ] = "pending"
    created_at: datetime
    operation_id: str
    affected_paths: list[str] = Field(default_factory=list)
    decision: str = ""
    proposal: str = ""
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    current_state: str = ""
    proposed_state: str = ""
    risks: str = ""
    rollback: str = ""
    recommendation: str = ""


class PlannedWrite(BaseModel):
    path: str
    content: str
    expected_hash: str | None = None


class OperationPlan(BaseModel):
    operation_id: str = Field(default_factory=lambda: f"OP-{uuid4()}")
    created_at: datetime
    permission_level: int = Field(ge=0, le=3)
    description: str
    writes: list[PlannedWrite] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchHit(BaseModel):
    object_id: str
    object_type: str
    title: str
    text: str
    score: float
    source_id: str | None = None
    locator: str | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
