"""Idempotent Phase 1/2 runtime migration into Phase 2.5 durable ledgers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from second_brain.models import KnowledgeExtraction
from second_brain.paths import BrainPaths
from second_brain.storage.durable import (
    CanonicalResolutionLedger,
    ConceptResolution,
    KnowledgeGapEvent,
    ProjectStateEvent,
    append_jsonl_event,
    atomic_json,
    read_jsonl,
)
from second_brain.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class MigrationReport:
    schema_before: int
    schema_after: int
    resolution_ledgers_created: int
    project_events_created: int
    gap_events_created: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _json(value: object, fallback: object) -> object:
    try:
        return json.loads(str(value or ""))
    except json.JSONDecodeError:
        return fallback


def _metadata(row: Any) -> dict[str, Any]:
    value = _json(row["metadata_json"], {})
    return value if isinstance(value, dict) else {}


def _contains_source(row: Any, source_id: str) -> bool:
    metadata = _metadata(row)
    values = metadata.get("source_ids", [])
    return isinstance(values, list) and source_id in {str(value) for value in values}


def migrate_phase2_runtime(
    paths: BrainPaths | None = None,
    store: SQLiteStore | None = None,
) -> MigrationReport:
    """Upgrade generated schema and snapshot old canonical DB truth into durable Phase 2.5 ledgers.

    This is intentionally conservative: it never rewrites canonical Markdown or raw sources. Existing
    Phase 2.5 ledgers win, making the operation safe to run repeatedly.
    """

    paths = paths or BrainPaths.discover()
    store = store or SQLiteStore(paths.db)
    schema_before = store.schema_version()
    store.initialize()
    schema_after = store.schema_version()
    created_resolutions = 0
    created_project_events = 0
    created_gap_events = 0

    legacy_root = paths.brain / "ledgers"
    resolution_root = legacy_root / "resolutions"
    resolution_root.mkdir(parents=True, exist_ok=True)
    for legacy in sorted(legacy_root.glob("knowledge-SRC-*.json")):
        try:
            payload = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        source_id = str(payload.get("source_id", ""))
        if not source_id:
            continue
        target = resolution_root / f"{source_id}.json"
        if target.exists():
            continue
        extraction_raw = payload.get("extraction", {})
        try:
            extraction = KnowledgeExtraction.model_validate(extraction_raw)
        except ValueError:
            extraction = KnowledgeExtraction()
        with store.connect() as conn:
            source_row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
            concept_rows = conn.execute("SELECT * FROM concepts ORDER BY id").fetchall()
            claim_rows = conn.execute("SELECT * FROM claims WHERE source_id=? ORDER BY id", (source_id,)).fetchall()
            entity_rows = conn.execute("SELECT * FROM entities ORDER BY id").fetchall()
            decision_rows = conn.execute("SELECT * FROM decisions ORDER BY id").fetchall()
            relation_rows = conn.execute("SELECT * FROM relationships WHERE source_id=? ORDER BY id", (source_id,)).fetchall()
            loop_rows = conn.execute("SELECT * FROM open_loops WHERE source_id=? ORDER BY id", (source_id,)).fetchall()
            candidate_rows = conn.execute("SELECT * FROM project_candidates WHERE source_id=? ORDER BY id", (source_id,)).fetchall()
            question_rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
        canonical_for_source = [row for row in concept_rows if _contains_source(row, source_id)]
        by_id = {str(row["id"]): row for row in canonical_for_source}
        by_title = {str(row["title"]).strip().lower(): row for row in canonical_for_source}
        concept_resolutions: list[ConceptResolution] = []
        for incoming in extraction.concepts:
            row = by_id.get(incoming.id) or by_title.get(incoming.title.strip().lower())
            if row is None:
                concept_resolutions.append(
                    ConceptResolution(
                        incoming_id=incoming.id,
                        canonical_id=incoming.id,
                        action="review_pending",
                        evidence=[source_id],
                    )
                )
            else:
                canonical_id = str(row["id"])
                concept_resolutions.append(
                    ConceptResolution(
                        incoming_id=incoming.id,
                        canonical_id=canonical_id,
                        action="created" if canonical_id == incoming.id else "duplicate",
                        evidence=[source_id],
                    )
                )

        claims: list[dict[str, Any]] = []
        for row in claim_rows:
            item = _metadata(row)
            item["materialized_path"] = row["materialized_path"]
            claims.append(item)
        entities: list[dict[str, Any]] = []
        for row in entity_rows:
            if not _contains_source(row, source_id):
                continue
            item = _metadata(row)
            item["note_path"] = row["note_path"]
            entities.append(item)
        decisions = [_metadata(row) for row in decision_rows if _contains_source(row, source_id)]
        relationships = [_metadata(row) for row in relation_rows]
        claim_ids = {str(row["id"]) for row in claim_rows}
        with store.connect() as conn:
            conflict_rows = conn.execute("SELECT * FROM conflicts ORDER BY id").fetchall()
        conflicts = [dict(row) for row in conflict_rows if str(row["left_id"]) in claim_ids or str(row["right_id"]) in claim_ids]
        questions = [
            {
                "id": str(row["id"]),
                "question": str(row["question"]),
                "source_id": source_id,
                "missing_evidence": str(row["missing_evidence"] or ""),
            }
            for row in question_rows
            if str(_metadata(row).get("source_id") or "") == source_id
        ]
        open_loops = [
            {
                "id": str(row["id"]),
                "text": str(row["text"]),
                "project_id": str(row["project_id"]) if row["project_id"] else None,
                "source_id": source_id,
            }
            for row in loop_rows
        ]
        project_candidates = [
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "rationale": str(row["rationale"]),
                "confidence_state": str(row["confidence_state"]),
                "source_id": source_id,
            }
            for row in candidate_rows
        ]
        ledger = CanonicalResolutionLedger(
            source_id=source_id,
            source_hash=str(source_row["content_hash"]) if source_row is not None else str(payload.get("source_hash", "")),
            compiler_version="phase2.5-migration-from-phase2",
            concept_resolutions=concept_resolutions,
            claims=claims,
            entities=entities,
            decisions=decisions,
            relationships=relationships,
            conflicts=conflicts,
            questions=questions,
            open_loops=open_loops,
            project_candidates=project_candidates,
        )
        atomic_json(target, ledger.model_dump(mode="json"))
        created_resolutions += 1

    with store.connect() as conn:
        project_rows = conn.execute(
            """
            SELECT p.id AS project_id,ps.* FROM projects p
            JOIN project_states ps ON ps.project_id=p.id
            ORDER BY p.id,ps.id
            """
        ).fetchall()
    existing_project_history = {
        path.stem
        for path in (legacy_root / "projects").glob("PRJ-*.jsonl")
        if read_jsonl(path)
    }
    for row in project_rows:
        project_id = str(row["project_id"])
        if project_id in existing_project_history:
            continue
        ledger_path = legacy_root / "projects" / f"{project_id}.jsonl"
        event_id = f"PSE-MIG-{project_id}-{row['id']}"
        evidence = _json(row["evidence_json"], [])
        blockers = _json(row["blockers_json"], [])
        open_questions = _json(row["open_questions_json"], [])
        event = ProjectStateEvent(
            event_id=event_id,
            project_id=project_id,
            timestamp=str(row["created_at"]),
            current_state=str(row["current_state"]),
            next_action=str(row["next_action"] or ""),
            blockers=[str(value) for value in blockers] if isinstance(blockers, list) else [],
            open_questions=[str(value) for value in open_questions] if isinstance(open_questions, list) else [],
            evidence=[str(value) for value in evidence] if isinstance(evidence, list) else [],
            source_ids=[str(value) for value in evidence if str(value).startswith("SRC-")] if isinstance(evidence, list) else [],
            verified_at=str(row["verified_at"]) if row["verified_at"] else None,
            operation_id=f"OP-MIG-{project_id}-{row['id']}",
            status="migrated",
        )
        if append_jsonl_event(ledger_path, event.model_dump(mode="json"), event_id=event.event_id):
            created_project_events += 1

    gap_path = legacy_root / "knowledge-gaps.jsonl"
    existing_gap_events = read_jsonl(gap_path)
    existing_gap_ids = {str(item.get("event_id")) for item in existing_gap_events}
    existing_gap_questions = {str(item.get("question_id")) for item in existing_gap_events}
    with store.connect() as conn:
        gap_rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
    for row in gap_rows:
        question_id = str(row["id"])
        if question_id in existing_gap_questions:
            continue
        opened_id = f"KGE-MIG-OPEN-{question_id}"
        if opened_id not in existing_gap_ids:
            searched_raw = _json(row["searched_json"], [])
            found_raw = _json(row["found_json"], [])
            searched = [str(value) for value in searched_raw] if isinstance(searched_raw, list) else []
            found = [str(value) for value in found_raw] if isinstance(found_raw, list) else []
            opened = KnowledgeGapEvent(
                event_id=opened_id,
                question_id=question_id,
                question=str(row["question"]),
                event="opened",
                timestamp=str(row["created_at"]),
                missing_evidence=str(row["missing_evidence"] or ""),
                searched=searched,
                found=found,
            )
            if append_jsonl_event(gap_path, opened.model_dump(mode="json"), event_id=opened.event_id):
                created_gap_events += 1
                existing_gap_ids.add(opened_id)
        status = str(row["status"])
        mapped = {"resolved": "resolved", "dismissed": "dismissed", "reopened": "reopened", "candidate_evidence": "candidate_evidence_found"}.get(status)
        if mapped is None:
            continue
        final_id = f"KGE-MIG-{mapped.upper()}-{question_id}"
        if final_id in existing_gap_ids:
            continue
        final = KnowledgeGapEvent(
            event_id=final_id,
            question_id=question_id,
            question=str(row["question"]),
            event=mapped,  # type: ignore[arg-type]
            timestamp=str(row["resolved_at"] or row["created_at"]),
            missing_evidence=str(row["missing_evidence"] or ""),
            resolution_id=str(row["resolution_id"]) if row["resolution_id"] else None,
        )
        if append_jsonl_event(gap_path, final.model_dump(mode="json"), event_id=final.event_id):
            created_gap_events += 1
            existing_gap_ids.add(final_id)

    return MigrationReport(
        schema_before=schema_before,
        schema_after=schema_after,
        resolution_ledgers_created=created_resolutions,
        project_events_created=created_project_events,
        gap_events_created=created_gap_events,
    )
