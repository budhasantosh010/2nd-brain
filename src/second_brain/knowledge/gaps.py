"""Durable knowledge-gap lifecycle and evidence-driven re-evaluation."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from second_brain.models import PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.retrieval.service import RetrievalService
from second_brain.storage.durable import KnowledgeGapEvent, append_jsonl_event, read_jsonl
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan
from second_brain.verification.service import REFUSAL, VerificationService

WORD = re.compile(r"[a-z0-9]+")
STOP = {
    "what",
    "when",
    "where",
    "why",
    "how",
    "which",
    "who",
    "is",
    "are",
    "was",
    "were",
    "the",
    "a",
    "an",
    "to",
    "of",
    "for",
    "in",
    "on",
    "and",
    "or",
    "did",
    "does",
    "do",
}


class GapResolver:
    VALID_STATES = {"open", "candidate_evidence", "resolved", "reopened", "dismissed"}

    def __init__(
        self,
        paths: BrainPaths | None = None,
        store: SQLiteStore | None = None,
        retrieval: RetrievalService | None = None,
    ) -> None:
        self.paths = paths or BrainPaths.discover()
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        self.retrieval = retrieval or RetrievalService(self.paths, store=self.store)
        self.verification = VerificationService(self.paths, self.store, self.retrieval)
        self.transactions = TransactionManager(self.paths, self.store)

    def recheck(self, *, source_ids: list[str] | None = None, limit: int = 50) -> dict[str, int]:
        """Re-evaluate open/candidate gaps against current indexes.

        If ``source_ids`` is supplied, only evidence introduced by those sources may advance a
        gap. This keeps compilation-triggered rechecks attributable to the newly arrived evidence.
        """

        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE status IN ('open','candidate_evidence') "
                "ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
        counts = {"checked": 0, "candidate_evidence": 0, "resolved": 0}
        allowed_sources = set(source_ids or [])
        for row in rows:
            counts["checked"] += 1
            question = str(row["question"])
            hits = self.retrieval.search(question, limit=8)
            if allowed_sources:
                hits = [
                    hit
                    for hit in hits
                    if hit.source_id in allowed_sources or hit.object_id in allowed_sources
                ]
            if not hits:
                continue
            top = hits[0]
            found = sorted(
                {
                    value
                    for hit in hits[:5]
                    for value in (hit.source_id, hit.object_id)
                    if value and (not allowed_sources or value in allowed_sources or hit.source_id in allowed_sources)
                }
            )
            current_status = str(row["status"])
            if current_status == "open":
                self._transition(
                    row,
                    status="candidate_evidence",
                    event="candidate_evidence_found",
                    found=found,
                    source_ids=sorted(allowed_sources or {hit.source_id for hit in hits if hit.source_id}),
                    resolution_id=top.object_id,
                )
                counts["candidate_evidence"] += 1

            # Auto-resolution requires both verified extractive support and meaningful lexical
            # alignment. Semantic similarity alone can advance to candidate_evidence but cannot
            # silently close a gap.
            query_type = self.retrieval.classify(question)
            answer = self.verification.answer_from_hits(question, hits, query_type=query_type)
            if answer.answer != REFUSAL and self._support_overlap(question, top.text) >= 0.45:
                self._transition(
                    row,
                    status="resolved",
                    event="resolved",
                    found=found,
                    source_ids=sorted(allowed_sources or {hit.source_id for hit in hits if hit.source_id}),
                    resolution_id=top.object_id,
                    answer=answer.answer,
                    evidence=[item.model_dump(mode="json") for item in answer.evidence],
                )
                counts["resolved"] += 1
        self.refresh_dashboards()
        return counts

    def reopen(self, question_id: str, *, reason: str = "Evidence became insufficient or stale.") -> None:
        row = self._question(question_id)
        self._transition(row, status="open", event="reopened", missing_evidence=reason)
        self.refresh_dashboards()

    def dismiss(self, question_id: str, *, reason: str = "Gap dismissed by review.") -> None:
        row = self._question(question_id)
        self._transition(row, status="dismissed", event="dismissed", missing_evidence=reason)
        self.refresh_dashboards()

    def history(self, question_id: str) -> list[dict[str, Any]]:
        return [
            event
            for event in read_jsonl(self.paths.brain / "ledgers" / "knowledge-gaps.jsonl")
            if str(event.get("question_id")) == question_id
        ]

    def refresh_dashboards(self) -> None:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE status IN ('open','candidate_evidence') "
                "ORDER BY created_at DESC"
            ).fetchall()
        unanswered = [
            "# Unanswered Questions",
            "",
            "> Generated from grounded refusals. Candidate evidence is shown but is not silently treated as truth.",
            "",
        ]
        gaps = [
            "# Knowledge Gaps",
            "",
            "> Durable lifecycle: open → candidate_evidence → resolved/reopened/dismissed.",
            "",
        ]
        if not rows:
            unanswered.append("_None recorded._")
            gaps.append("_No active knowledge gaps._")
        for row in rows:
            status = str(row["status"])
            block = [
                f"## {row['id']} — {status}",
                "",
                str(row["question"]),
                "",
                f"Missing evidence: {row['missing_evidence'] or 'unspecified'}",
                "",
            ]
            unanswered.extend(block)
            gaps.extend(block)
        writes: list[PlannedWrite] = []
        for relative, lines in (
            ("07 Operations/Unanswered Questions.md", unanswered),
            ("07 Operations/Knowledge Gaps.md", gaps),
        ):
            path = self.paths.vault / relative
            writes.append(
                PlannedWrite(
                    path=relative,
                    content="\n".join(lines).rstrip() + "\n",
                    expected_hash=file_sha256(path) if path.exists() else None,
                )
            )
        self.transactions.apply(
            build_plan("Refresh knowledge-gap dashboards", writes, permission_level=1)
        )

    def _question(self, question_id: str):  # type: ignore[no-untyped-def]
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        if row is None:
            raise KeyError(f"Knowledge gap not found: {question_id}")
        return row

    def _transition(
        self,
        row: sqlite3.Row,
        *,
        status: str,
        event: str,
        found: list[str] | None = None,
        source_ids: list[str] | None = None,
        resolution_id: str | None = None,
        answer: str = "",
        evidence: list[dict[str, Any]] | None = None,
        missing_evidence: str | None = None,
    ) -> None:
        if status not in self.VALID_STATES:
            raise ValueError(f"Invalid gap state: {status}")
        question_id = str(row["id"])
        if str(row["status"]) == status and event != "resolved":
            return
        now = datetime.now(UTC).isoformat()
        found_values = found if found is not None else self._json_list(row["found_json"])
        missing = missing_evidence if missing_evidence is not None else str(row["missing_evidence"] or "")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE questions SET status=?,found_json=?,missing_evidence=?,resolved_at=?,resolution_id=? WHERE id=?",
                (
                    status,
                    json.dumps(found_values, sort_keys=True),
                    missing,
                    now if status == "resolved" else None,
                    resolution_id,
                    question_id,
                ),
            )
        gap_event = KnowledgeGapEvent(
            question_id=question_id,
            question=str(row["question"]),
            event=event,  # type: ignore[arg-type]
            timestamp=now,
            missing_evidence=missing,
            searched=self._json_list(row["searched_json"]),
            found=found_values,
            source_ids=source_ids or [],
            resolution_id=resolution_id,
            answer=answer,
            evidence=evidence or [],
            operation_id=f"OP-gap-{uuid4()}",
        )
        append_jsonl_event(
            self.paths.brain / "ledgers" / "knowledge-gaps.jsonl",
            gap_event.model_dump(mode="json"),
            event_id=gap_event.event_id,
        )

    @staticmethod
    def _json_list(value: object) -> list[str]:
        try:
            parsed = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @staticmethod
    def _support_overlap(question: str, evidence: str) -> float:
        left = {word for word in WORD.findall(question.lower()) if word not in STOP and len(word) > 2}
        right = set(WORD.findall(evidence.lower()))
        if not left:
            return 0.0
        return len(left & right) / len(left)
