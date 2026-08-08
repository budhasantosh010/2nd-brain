"""Source → validated extraction → deterministic matching → canonical change plan."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import frontmatter
import yaml

from second_brain.config import BrainConfig, load_config
from second_brain.embeddings.local import LocalEmbeddingProvider
from second_brain.knowledge.contradiction import contradiction_candidate
from second_brain.knowledge.extractor import KnowledgeExtractor
from second_brain.knowledge.linker import derived_from, supports
from second_brain.knowledge.matcher import ConceptMatcher, MatchAction
from second_brain.models import (
    ClaimRecord,
    ConceptRecord,
    DecisionRecord,
    EntityRecord,
    KnowledgeExtraction,
    OperationPlan,
    ParsedDocument,
    PlannedWrite,
    ProcessingState,
    RelationshipRecord,
    RelationshipType,
)
from second_brain.paths import BrainPaths
from second_brain.providers import AIProvider, create_provider
from second_brain.review.service import ReviewService
from second_brain.storage.markdown import file_sha256
from second_brain.storage.repository import BrainRepository
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan

SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(slots=True)
class CompileResult:
    source_id: str
    state: ProcessingState
    cache_hit: bool = False
    created_concepts: list[str] = field(default_factory=list)
    duplicate_concepts: list[str] = field(default_factory=list)
    review_items: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    project_candidates: int = 0
    open_loops: int = 0
    questions: int = 0
    message: str = ""


class KnowledgeCompiler:
    def __init__(
        self,
        paths: BrainPaths | None = None,
        config: BrainConfig | None = None,
        store: SQLiteStore | None = None,
        provider: AIProvider | None = None,
    ) -> None:
        self.paths = paths or BrainPaths.discover()
        self.config = config or load_config(self.paths)
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        self.repository = BrainRepository(self.store)
        self.vectors = VectorStore(
            self.store,
            LocalEmbeddingProvider(self.config.embeddings.dimensions),
        )
        self.provider = provider if provider is not None else create_provider(self.config)
        self.transactions = TransactionManager(self.paths, self.store)
        self.reviews = ReviewService(self.paths, self.store, self.transactions)
        self.matcher = ConceptMatcher(self.repository)

    def compile_source(self, source_id: str) -> CompileResult:
        row = self.store.source_by_id(source_id)
        if row is None:
            raise KeyError(f"Source not found: {source_id}")
        if self.provider is None:
            self.store.update_source_status(source_id, ProcessingState.NEEDS_AI.value)
            return CompileResult(
                source_id,
                ProcessingState.NEEDS_AI,
                message="No AI provider configured; deterministic source data remains preserved/indexed.",
            )
        health = self.provider.health_check()
        if not health.available:
            self.store.update_source_status(source_id, ProcessingState.NEEDS_AI.value)
            return CompileResult(
                source_id,
                ProcessingState.NEEDS_AI,
                message=f"AI provider unavailable: {health.detail}",
            )
        if self.provider.is_cloud and not self._cloud_egress_allowed(row):
            self.store.update_source_status(source_id, ProcessingState.NEEDS_AI.value)
            return CompileResult(
                source_id,
                ProcessingState.NEEDS_AI,
                message="Cloud AI blocked by source sensitivity/egress policy; source remains local.",
            )

        document = self._load_document(row)
        extractor = KnowledgeExtractor(self.provider, self.repository)
        extraction, cache_hit = extractor.extract(document, source_hash=str(row["content_hash"]))
        return self._apply_extraction(row, document, extraction, cache_hit=cache_hit)

    def _apply_extraction(
        self,
        source_row: sqlite3.Row,
        document: ParsedDocument,
        extraction: KnowledgeExtraction,
        *,
        cache_hit: bool,
    ) -> CompileResult:
        source_id = str(source_row["id"])
        result = CompileResult(source_id, ProcessingState.COMPILED, cache_hit=cache_hit)
        writes: list[PlannedWrite] = []
        db_concepts: list[tuple[ConceptRecord, str]] = []
        db_claims: list[tuple[ClaimRecord, str | None]] = []
        db_entities: list[tuple[EntityRecord, str | None]] = []
        db_decisions: list[DecisionRecord] = []
        relationships: list[RelationshipRecord] = []
        conflicts_to_insert: list[tuple[str, str, str, str]] = []
        review_plans: list[tuple[OperationPlan, ConceptRecord, dict[str, object]]] = []

        for concept in extraction.concepts:
            if source_id not in concept.source_ids:
                concept.source_ids.append(source_id)
            match = self.matcher.match(concept)
            if match.action in {MatchAction.NEW, MatchAction.UNRELATED}:
                rel = self._concept_path(concept)
                writes.append(PlannedWrite(path=rel, content=self._render_concept(concept)))
                db_concepts.append((concept, rel))
                relationships.append(derived_from(concept.id, source_id))
                result.created_concepts.append(concept.id)
            elif match.action == MatchAction.DUPLICATE and match.existing_id:
                relationships.append(derived_from(match.existing_id, source_id))
                result.duplicate_concepts.append(match.existing_id)
            elif match.action == MatchAction.UPDATE and match.existing_id:
                existing = self.repository.concept_by_id(match.existing_id)
                if existing is None:
                    continue
                note_path = str(existing.get("note_path") or "")
                if not note_path:
                    continue
                incoming = concept.model_copy(deep=True)
                incoming.id = match.existing_id
                metadata = json.loads(str(existing.get("metadata_json") or "{}"))
                old_sources = [str(value) for value in metadata.get("source_ids", [])]
                incoming.source_ids = sorted(set(old_sources + incoming.source_ids + [source_id]))
                target = self.paths.vault / note_path
                expected = file_sha256(target) if target.exists() else None
                proposal = build_plan(
                    f"Meaning-changing concept update: {incoming.title}",
                    [
                        PlannedWrite(
                            path=note_path,
                            content=self._render_concept(incoming),
                            expected_hash=expected,
                        )
                    ],
                    permission_level=2,
                )
                proposal.metadata["concept_update"] = incoming.model_dump(mode="json")
                proposal.metadata["note_path"] = note_path
                review_plans.append((proposal, incoming, existing))

        with self.store.connect() as conn:
            existing_claim_rows = conn.execute("SELECT id, statement FROM claims").fetchall()
        incoming_claims_seen: list[ClaimRecord] = []
        for claim in extraction.claims:
            claim.source_id = source_id
            for existing_claim in existing_claim_rows:
                existing_id = str(existing_claim["id"])
                existing_statement = str(existing_claim["statement"])
                if contradiction_candidate(existing_statement, claim.statement):
                    conflict_id = f"CNF-{uuid4()}"
                    explanation = "Conservative contradiction candidate: high statement overlap with opposite negation; preserve both and require verification."
                    conflicts_to_insert.append((conflict_id, existing_id, claim.id, explanation))
                    relationships.append(
                        RelationshipRecord(
                            from_id=existing_id,
                            to_id=claim.id,
                            relation=RelationshipType.CONTRADICTS,
                            source_id=source_id,
                            provisional=True,
                        )
                    )
            for earlier_claim in incoming_claims_seen:
                if contradiction_candidate(earlier_claim.statement, claim.statement):
                    conflict_id = f"CNF-{uuid4()}"
                    explanation = "Conservative contradiction candidate within one extracted source; preserve both statements for verification."
                    conflicts_to_insert.append((conflict_id, earlier_claim.id, claim.id, explanation))
                    relationships.append(
                        RelationshipRecord(
                            from_id=earlier_claim.id,
                            to_id=claim.id,
                            relation=RelationshipType.CONTRADICTS,
                            source_id=source_id,
                            provisional=True,
                        )
                    )
            incoming_claims_seen.append(claim)
            materialized_path: str | None = None
            if claim.materialize:
                materialized_path = f"03 Knowledge/Claims/{claim.id}.md"
                writes.append(
                    PlannedWrite(path=materialized_path, content=self._render_claim(claim))
                )
            db_claims.append((claim, materialized_path))
            relationships.append(supports(claim.id, source_id))
            result.claims.append(claim.id)

        for entity in extraction.entities:
            if source_id not in entity.source_ids:
                entity.source_ids.append(source_id)
            rel = self._entity_path(entity.entity_type, entity.name, entity.id)
            writes.append(PlannedWrite(path=rel, content=self._render_entity(entity)))
            db_entities.append((entity, rel))
            relationships.append(derived_from(entity.id, source_id))
            result.entities.append(entity.id)

        for decision in extraction.decisions:
            if source_id not in decision.source_ids:
                decision.source_ids.append(source_id)
            rel = f"03 Knowledge/Decisions/{decision.id}.md"
            writes.append(PlannedWrite(path=rel, content=self._render_decision(decision)))
            db_decisions.append(decision)
            relationships.append(derived_from(decision.id, source_id))
            result.decisions.append(decision.id)

        ledger_rel = f".brain/ledgers/knowledge-{source_id}.json"
        writes.append(
            PlannedWrite(
                path=ledger_rel,
                content=json.dumps(
                    {
                        "source_id": source_id,
                        "source_hash": str(source_row["content_hash"]),
                        "schema": "knowledge-extraction-v1",
                        "provider": self.provider.name if self.provider is not None else "none",
                        "model": self.provider.model if self.provider is not None else "",
                        "compiled_at": datetime.now(UTC).isoformat(),
                        "extraction": extraction.model_dump(mode="json"),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
        )

        source_record_rel = f"02 Sources/Records/{source_id}.md"
        source_record_path = self.paths.vault / source_record_rel
        if source_record_path.exists():
            writes.append(
                PlannedWrite(
                    path=source_record_rel,
                    content=self._source_record_with_status(source_record_path, ProcessingState.COMPLETE),
                    expected_hash=file_sha256(source_record_path),
                )
            )

        main_plan = build_plan(
            f"Compile validated knowledge from {source_id}", writes, permission_level=1
        )

        def db_action(conn: sqlite3.Connection) -> None:
            for concept, note_path in db_concepts:
                BrainRepository.upsert_concept_db(conn, concept, note_path)
            for claim, claim_note_path in db_claims:
                BrainRepository.insert_claim_db(conn, claim, claim_note_path)
            for entity, entity_note_path in db_entities:
                BrainRepository.insert_entity_db(conn, entity, entity_note_path)
            for decision in db_decisions:
                BrainRepository.insert_decision_db(conn, decision)
            for relation in relationships:
                BrainRepository.insert_relationship_db(conn, relation)
            for conflict_id, left_id, right_id, explanation in conflicts_to_insert:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO conflicts(
                        id, left_id, right_id, conflict_type, status, explanation, created_at, metadata_json
                    ) VALUES (?, ?, ?, 'claim-contradiction', 'open', ?, ?, '{}')
                    """,
                    (
                        conflict_id,
                        left_id,
                        right_id,
                        explanation,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            for loop in extraction.open_loops:
                BrainRepository.insert_open_loop_db(
                    conn,
                    loop_id=f"LOP-{uuid4()}",
                    text=loop.text,
                    project_id=loop.project_id,
                    source_id=source_id,
                )
            for candidate in extraction.project_candidates:
                BrainRepository.insert_project_candidate_db(
                    conn,
                    candidate_id=f"PCD-{uuid4()}",
                    name=candidate.name,
                    rationale=candidate.rationale,
                    confidence_state=candidate.confidence_state.value,
                    source_id=source_id,
                )
            for question in extraction.questions:
                BrainRepository.insert_question_db(
                    conn,
                    question_id=f"QUE-{uuid4()}",
                    question=question,
                    source_id=source_id,
                )
            conn.execute("UPDATE sources SET status = ? WHERE id = ?", (ProcessingState.COMPLETE.value, source_id))

        if writes or db_concepts or db_claims or db_entities or db_decisions or relationships or extraction.open_loops or extraction.project_candidates or extraction.questions:
            self.transactions.apply(main_plan, db_action=db_action)
        else:
            with self.store.transaction() as conn:
                db_action(conn)

        for concept, note_path in db_concepts:
            concept_text = f"{concept.title}\n{concept.summary}"
            self.store.index_text(
                object_id=concept.id,
                object_type="concept",
                title=concept.title,
                text=concept_text,
                source_id=source_id,
                locator=note_path,
            )
            self.vectors.upsert(
                object_id=concept.id,
                object_type="concept",
                title=concept.title,
                text=concept_text,
                source_id=source_id,
                metadata={
                    "project_ids": concept.project_ids,
                    "status": concept.status,
                    "verification_state": concept.verification_state.value,
                    "locator": note_path,
                },
            )
        for claim, claim_note_path in db_claims:
            self.store.index_text(
                object_id=claim.id,
                object_type="claim",
                title="Claim",
                text=claim.statement,
                source_id=source_id,
                locator=claim_note_path,
            )
            self.vectors.upsert(
                object_id=claim.id,
                object_type="claim",
                title="Claim",
                text=claim.statement,
                source_id=source_id,
                metadata={
                    "project_ids": claim.project_ids,
                    "confidence_state": claim.confidence_state.value,
                    "locator": claim_note_path or claim.source_locator,
                },
            )
        for entity, entity_note_path in db_entities:
            self.store.index_text(
                object_id=entity.id,
                object_type="entity",
                title=entity.name,
                text=f"{entity.name}\n{entity.entity_type}",
                source_id=source_id,
                locator=entity_note_path,
            )
            self.vectors.upsert(
                object_id=entity.id,
                object_type="entity",
                title=entity.name,
                text=f"{entity.name}\n{entity.entity_type}",
                source_id=source_id,
                metadata={
                    "project_ids": entity.project_ids,
                    "entity_type": entity.entity_type,
                    "locator": entity_note_path,
                },
            )
        for decision in extraction.decisions:
            decision_text = f"{decision.decision}\n{decision.reasoning}"
            decision_path = f"03 Knowledge/Decisions/{decision.id}.md"
            self.store.index_text(
                object_id=decision.id,
                object_type="decision",
                title="Decision",
                text=decision_text,
                source_id=source_id,
                locator=decision_path,
            )
            self.vectors.upsert(
                object_id=decision.id,
                object_type="decision",
                title="Decision",
                text=decision_text,
                source_id=source_id,
                metadata={
                    "project_id": decision.project_id,
                    "status": decision.status,
                    "supersedes": decision.supersedes,
                    "superseded_by": decision.superseded_by,
                    "locator": decision_path,
                },
            )

        for proposal, incoming, existing in review_plans:
            item = self.reviews.stage(
                proposal,
                review_type="concept-update",
                risk="medium",
                proposal=f"Update existing concept '{incoming.title}' with materially different understanding.",
                reason="Exact concept title matched, but summary meaning changed enough to require review.",
                evidence=[source_id],
                current_state=str(existing.get("summary") or ""),
                proposed_state=incoming.summary,
                risks="A silent update could erase or alter the previous meaning.",
                rollback="Transaction history restores the previous concept note.",
            )
            result.review_items.append(item.review_id)

        result.project_candidates = len(extraction.project_candidates)
        result.open_loops = len(extraction.open_loops)
        result.questions = len(extraction.questions)
        result.state = ProcessingState.NEEDS_REVIEW if result.review_items else ProcessingState.COMPLETE
        result.message = "Validated knowledge compiled; risky meaning changes were staged." if result.review_items else "Validated knowledge compiled and indexed."
        return result

    def _cloud_egress_allowed(self, row: sqlite3.Row) -> bool:
        if not self.config.ai.allow_cloud_ai:
            return False
        return str(row["sensitivity"]) == "cloud_allowed"

    @staticmethod
    def _load_document(row: sqlite3.Row) -> ParsedDocument:
        extracted_path = row["extracted_path"]
        if not extracted_path:
            raise ValueError(f"Source {row['id']} has no deterministic extraction")
        path = Path(str(extracted_path))
        if not path.exists():
            raise FileNotFoundError(path)
        return ParsedDocument.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = SAFE_NAME.sub("-", value).strip(" .-")
        return cleaned[:80] or "untitled"

    def _concept_path(self, concept: ConceptRecord) -> str:
        return f"03 Knowledge/Concepts/{self._safe_name(concept.title)}--{concept.id}.md"

    def _entity_path(self, entity_type: str, name: str, entity_id: str) -> str:
        buckets = {
            "person": "People",
            "company": "Companies",
            "product": "Products",
            "tool": "Tools",
            "technology": "Technologies",
        }
        bucket = buckets.get(entity_type.strip().lower(), "Technologies")
        return f"03 Knowledge/Entities/{bucket}/{self._safe_name(name)}--{entity_id}.md"

    @staticmethod
    def _render_concept(concept: ConceptRecord) -> str:
        metadata = {
            "id": concept.id,
            "type": "concept",
            "title": concept.title,
            "status": concept.status,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "verification_state": concept.verification_state.value,
            "source_ids": concept.source_ids,
            "project_ids": concept.project_ids,
            "tags": concept.tags,
        }
        header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
        sources = "\n".join(f"- `{source}`" for source in concept.source_ids) or "_None._"
        return (
            f"---\n{header}\n---\n\n# {concept.title}\n\n"
            f"## Summary\n\n{concept.summary}\n\n"
            f"## Current Understanding\n\n{concept.summary}\n\n"
            f"## Evidence\n\n{sources}\n\n"
            "## Important Claims\n\n_See structured claims/retrieval._\n\n"
            "## Connections\n\n_Compiled through typed relationships._\n\n"
            "## Contradictions\n\n_None verified in this note yet._\n\n"
            "## Practical Implications\n\n_Provisional._\n\n"
            f"## Sources\n\n{sources}\n\n"
            f"## Change History\n\n- {datetime.now(UTC).date().isoformat()}: provisional concept compiled.\n"
        )

    @staticmethod
    def _render_claim(claim) -> str:  # type: ignore[no-untyped-def]
        metadata = {
            "id": claim.id,
            "type": "claim",
            "title": claim.statement[:80],
            "status": claim.status,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "source_ids": [claim.source_id],
            "project_ids": claim.project_ids,
            "tags": [],
            "verification_state": claim.confidence_state.value,
        }
        header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
        return (
            f"---\n{header}\n---\n\n# Claim\n\n## Statement\n\n{claim.statement}\n\n"
            f"## Evidence\n\n- `{claim.source_id}` — {claim.source_locator or 'source'}\n\n"
            "## Validity\n\n_See structured validity fields._\n\n"
            "## Contradictions\n\n_None verified yet._\n\n"
            "## Supersession\n\n_None._\n\n"
            f"## Sources\n\n- `{claim.source_id}`\n"
        )

    @staticmethod
    def _render_entity(entity) -> str:  # type: ignore[no-untyped-def]
        metadata = {
            "id": entity.id,
            "type": "entity",
            "title": entity.name,
            "status": "provisional",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "source_ids": entity.source_ids,
            "project_ids": entity.project_ids,
            "tags": [],
            "entity_type": entity.entity_type,
        }
        header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
        sources = "\n".join(f"- `{source}`" for source in entity.source_ids) or "_None._"
        return (
            f"---\n{header}\n---\n\n# {entity.name}\n\n"
            f"## Summary\n\nProvisional {entity.entity_type} entity.\n\n"
            "## Aliases\n\n_None compiled._\n\n"
            f"## Evidence\n\n{sources}\n\n"
            "## Projects\n\n_See project relationships._\n\n"
            "## Relationships\n\n_See structured relationships._\n\n"
            f"## Change History\n\n- {datetime.now(UTC).date().isoformat()}: entity compiled.\n"
        )

    @staticmethod
    def _render_decision(decision) -> str:  # type: ignore[no-untyped-def]
        metadata = {
            "id": decision.id,
            "type": "decision",
            "project_id": decision.project_id,
            "status": decision.status,
            "decided_at": decision.decided_at.isoformat() if decision.decided_at else None,
            "supersedes": decision.supersedes,
            "superseded_by": decision.superseded_by,
            "source_ids": decision.source_ids,
        }
        header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
        sources = "\n".join(f"- `{source}`" for source in decision.source_ids) or "_None._"
        return (
            f"---\n{header}\n---\n\n# Decision\n\n"
            f"## Decision\n\n{decision.decision}\n\n"
            f"## Context\n\n{decision.context or '_Not extracted._'}\n\n"
            "## Alternatives\n\n_Not extracted._\n\n"
            f"## Reasoning\n\n{decision.reasoning or '_Not extracted._'}\n\n"
            "## Assumptions\n\n_Not extracted._\n\n"
            f"## Evidence\n\n{sources}\n\n"
            "## Consequences\n\n_Not compiled._\n\n"
            "## Reversal Conditions\n\n_Not compiled._\n\n"
            "## History\n\nDecision retained; future changes use supersession rather than overwrite.\n"
        )

    @staticmethod
    def _source_record_with_status(path: Path, status: ProcessingState) -> str:
        post = frontmatter.load(path)
        post.metadata["status"] = status.value
        yaml_text = yaml.safe_dump(dict(post.metadata), sort_keys=False, allow_unicode=True).strip()
        return f"---\n{yaml_text}\n---\n\n{post.content.rstrip()}\n"
