"""Grounded answer pipeline: retrieve evidence, verify, expose conflicts, refuse unsupported claims."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from second_brain.models import (
    BrainAnswer,
    EvidenceItem,
    PlannedWrite,
    QueryType,
    SearchHit,
    VerificationState,
)
from second_brain.paths import BrainPaths
from second_brain.retrieval.service import RetrievalService
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan
from second_brain.verification.evidence import evidence_from_hit

REFUSAL = "I cannot verify this from the current brain."
EXACT_TOKEN_PATTERN = re.compile(
    r"\b(?:[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+|[a-fA-F0-9]{12,})\b"
)


class VerificationService:
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
        self.transactions = TransactionManager(self.paths, self.store)

    def ask(
        self,
        question: str,
        *,
        project_id: str | None = None,
        limit: int | None = None,
    ) -> BrainAnswer:
        query_type = self.retrieval.classify(question)
        hits = self.retrieval.search(question, project_id=project_id, limit=limit)
        return self.answer_from_hits(question, hits, query_type=query_type)

    def answer_from_hits(
        self,
        question: str,
        hits: list[SearchHit],
        *,
        query_type: QueryType,
    ) -> BrainAnswer:
        evidence: list[EvidenceItem] = []
        uncertainty: list[str] = []
        usable_hits: list[SearchHit] = []
        for hit in hits:
            item, warnings = evidence_from_hit(self.store, hit, query_type)
            uncertainty.extend(warnings)
            if item is None:
                continue
            if (
                item.verification_state in {VerificationState.STALE, VerificationState.CONTRADICTED}
                and query_type != QueryType.HISTORICAL
            ):
                # Historical questions may intentionally use stale/superseded evidence.
                continue
            evidence.append(item)
            usable_hits.append(hit)

        conflicts = self._conflicts_for([hit.object_id for hit in hits])
        required_exact = self._required_exact_tokens(question)
        evidence_text = "\n".join(
            f"{hit.object_id}\n{hit.source_id or ''}\n{hit.locator or ''}\n{hit.title}\n{hit.text}"
            for hit in usable_hits
        ).lower()
        missing_exact = [token for token in required_exact if token.lower() not in evidence_text]
        if not evidence or missing_exact:
            missing_message = (
                "Exact-looking query token(s) were not found in verified evidence: "
                + ", ".join(missing_exact)
                if missing_exact
                else "No retrievable source-backed evidence was sufficient to support an answer."
            )
            missing = [missing_message]
            searched = [hit.object_id for hit in hits]
            self.record_unanswered(
                question,
                searched=searched,
                found=[item.source_id for item in evidence],
                missing=missing_message,
            )
            return BrainAnswer(
                answer=REFUSAL,
                evidence=[],
                citations=[],
                conflicts=conflicts,
                uncertainty=sorted(set(uncertainty)),
                missing_information=missing,
                query_type=query_type,
            )

        # Deterministic extractive V1 answer. This prevents a generation model from adding facts that
        # are not in the verified evidence. Optional natural-language generation can be layered later
        # only if its output is checked against this evidence set.
        top = evidence[0]
        answer = top.excerpt
        if query_type == QueryType.CURRENT_STATE and conflicts:
            answer += "\n\nConflicting stored evidence exists; see conflicts below before treating this as final."
        citations = [self._citation(item) for item in evidence]
        return BrainAnswer(
            answer=answer,
            evidence=evidence,
            citations=citations,
            conflicts=conflicts,
            uncertainty=sorted(set(uncertainty)),
            missing_information=[],
            query_type=query_type,
        )

    def record_unanswered(
        self,
        question: str,
        *,
        searched: list[str],
        found: list[str],
        missing: str,
    ) -> str:
        question_id = f"QUE-{uuid4()}"
        now = datetime.now(UTC).isoformat()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO questions(
                    id, question, status, searched_json, found_json, missing_evidence,
                    created_at, metadata_json
                ) VALUES (?, ?, 'open', ?, ?, ?, ?, '{}')
                """,
                (
                    question_id,
                    question,
                    json.dumps(searched, sort_keys=True),
                    json.dumps(found, sort_keys=True),
                    missing,
                    now,
                ),
            )
        self.refresh_unanswered_dashboard()
        return question_id

    def refresh_unanswered_dashboard(self) -> None:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE status = 'open' ORDER BY created_at DESC"
            ).fetchall()
        lines = [
            "# Unanswered Questions",
            "",
            "> Generated from grounded refusals and explicit unresolved questions. Future ingestion may resolve these gaps.",
            "",
        ]
        if not rows:
            lines.append("_None recorded._")
        else:
            for row in rows:
                lines.extend(
                    [
                        f"## {row['id']}",
                        "",
                        str(row["question"]),
                        "",
                        f"Missing evidence: {row['missing_evidence'] or 'unspecified'}",
                        "",
                    ]
                )
        content = "\n".join(lines).rstrip() + "\n"
        target = self.paths.vault / "07 Operations" / "Unanswered Questions.md"
        expected = self._file_hash(target) if target.exists() else None
        plan = build_plan(
            "Refresh unanswered-questions dashboard",
            [
                PlannedWrite(
                    path="07 Operations/Unanswered Questions.md",
                    content=content,
                    expected_hash=expected,
                )
            ],
            permission_level=1,
        )
        self.transactions.apply(plan)

    def _conflicts_for(self, object_ids: list[str]) -> list[str]:
        if not object_ids:
            return []
        conflicts: set[str] = set()
        with self.store.connect() as conn:
            for object_id in object_ids:
                rows = conn.execute(
                    """
                    SELECT left_id, right_id, explanation FROM conflicts
                    WHERE status = 'open' AND (left_id = ? OR right_id = ?)
                    """,
                    (object_id, object_id),
                ).fetchall()
                for row in rows:
                    conflicts.add(
                        f"{row['left_id']} contradicts {row['right_id']}: {row['explanation']}"
                    )
                rels = conn.execute(
                    """
                    SELECT from_id, to_id FROM relationships
                    WHERE relation = 'contradicts' AND (from_id = ? OR to_id = ?)
                    """,
                    (object_id, object_id),
                ).fetchall()
                for row in rels:
                    conflicts.add(f"{row['from_id']} contradicts {row['to_id']}")
        return sorted(conflicts)

    @staticmethod
    def _required_exact_tokens(question: str) -> list[str]:
        return sorted(set(EXACT_TOKEN_PATTERN.findall(question)))

    @staticmethod
    def _citation(item: EvidenceItem) -> str:
        return f"{item.source_id} @ {item.locator}" if item.locator else item.source_id

    @staticmethod
    def _file_hash(path) -> str:  # type: ignore[no-untyped-def]
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
