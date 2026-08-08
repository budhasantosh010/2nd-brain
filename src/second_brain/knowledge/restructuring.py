"""Structural-friction analysis and review-gated restructuring proposals."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from second_brain.config import BrainConfig, load_config
from second_brain.embeddings.factory import create_embedding_provider
from second_brain.models import OperationPlan, PlannedWrite
from second_brain.observability.metrics import collect_metrics
from second_brain.paths import BrainPaths
from second_brain.review.service import ReviewService
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan

WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class StructuralFinding:
    finding_type: str
    severity: str
    summary: str
    object_ids: tuple[str, ...] = ()
    affected_files: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    expected_retrieval_benefit: str = "Improve retrieval precision/continuity."
    recommendation: str = "Review structural change."
    risks: str = "Meaning-bearing structure may change if applied incorrectly."

    @property
    def signature(self) -> str:
        payload = "|".join(
            [self.finding_type, *sorted(self.object_ids), self.summary]
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class RestructuringReport:
    metrics: dict[str, Any]
    findings: tuple[StructuralFinding, ...]
    duplicate_titles: list[tuple[str, int]]
    broken_relationships: list[str]
    stale_projects: list[str]


class RestructuringProposalModel(BaseModel):
    schema_version: str = "restructuring-proposal-v1"
    proposal_id: str
    finding_type: str
    reason: str
    evidence: list[str] = Field(default_factory=list)
    affected_objects: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    expected_retrieval_benefit: str
    risks: str
    rollback_procedure: str
    recommended_action: str
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def _json_dict(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_query(value: str) -> str:
    words = [word for word in WORD.findall(value.lower()) if len(word) > 2]
    return " ".join(words[:8])


class StructuralAnalyzer:
    def __init__(
        self,
        paths: BrainPaths,
        config: BrainConfig,
        store: SQLiteStore,
    ) -> None:
        self.paths = paths
        self.config = config
        self.store = store
        self.vectors = VectorStore(store, create_embedding_provider(config, paths))

    def analyze(self) -> RestructuringReport:
        findings: list[StructuralFinding] = []
        with self.store.connect() as conn:
            duplicate_rows = conn.execute(
                """
                SELECT lower(title) AS normalized, COUNT(*) AS count,
                       group_concat(id) AS ids
                FROM concepts GROUP BY lower(title) HAVING COUNT(*) > 1
                ORDER BY count DESC
                """
            ).fetchall()
            all_ids: set[str] = set()
            for table in (
                "sources",
                "concepts",
                "claims",
                "entities",
                "projects",
                "decisions",
                "skills",
            ):
                rows = conn.execute(f"SELECT id FROM {table}").fetchall()
                all_ids.update(str(row["id"]) for row in rows)
            relationship_rows = conn.execute(
                "SELECT id,from_id,to_id,relation FROM relationships"
            ).fetchall()
            stale_rows = conn.execute(
                """
                SELECT id,title,project_path,updated_at FROM projects
                WHERE status='active' AND julianday('now') - julianday(updated_at) > 30
                ORDER BY updated_at
                """
            ).fetchall()
            project_no_next = conn.execute(
                """
                SELECT p.id,p.title,p.project_path FROM projects p
                LEFT JOIN project_states ps ON ps.project_id=p.id AND ps.active=1
                WHERE p.status='active' AND (ps.next_action IS NULL OR trim(ps.next_action)='')
                """
            ).fetchall()
            concept_rows = conn.execute(
                "SELECT id,title,note_path,metadata_json FROM concepts"
            ).fetchall()
            retrieval_rows = conn.execute(
                "SELECT query,results_json,answered FROM retrieval_events"
            ).fetchall()
            question_rows = conn.execute(
                "SELECT id,question,status FROM questions WHERE status IN ('open','candidate_evidence')"
            ).fetchall()
            state_rows = conn.execute(
                """
                SELECT p.id,p.title,ps.verified_at,ps.evidence_json
                FROM projects p JOIN project_states ps ON ps.project_id=p.id AND ps.active=1
                WHERE p.status='active'
                """
            ).fetchall()
            candidate_rows = conn.execute(
                "SELECT confidence_state,COUNT(*) AS count FROM project_candidates GROUP BY confidence_state"
            ).fetchall()

        duplicate_titles = [
            (str(row["normalized"]), int(row["count"])) for row in duplicate_rows
        ]
        for row in duplicate_rows:
            ids = tuple(sorted(str(row["ids"] or "").split(",")))
            findings.append(
                StructuralFinding(
                    "duplicate-title",
                    "high",
                    f"Multiple concepts share normalized title '{row['normalized']}'.",
                    ids,
                    evidence=(f"count={row['count']}",),
                    recommendation="Merge Concept A + Concept B only after evidence review.",
                )
            )

        broken = [
            str(row["id"])
            for row in relationship_rows
            if str(row["from_id"]) not in all_ids or str(row["to_id"]) not in all_ids
        ]
        for relation_id in broken:
            findings.append(
                StructuralFinding(
                    "broken-relationship",
                    "high",
                    f"Relationship {relation_id} references a missing endpoint.",
                    (relation_id,),
                    recommendation="Repair or remove the broken generated relationship after review.",
                )
            )

        stale_projects = [str(row["id"]) for row in stale_rows]
        for row in stale_rows:
            findings.append(
                StructuralFinding(
                    "stale-active-project",
                    "medium",
                    f"Active project '{row['title']}' has not changed for more than 30 days.",
                    (str(row["id"]),),
                    (f"{row['project_path']}/PROJECT.md",),
                    (f"updated_at={row['updated_at']}",),
                    recommendation="Review whether to refresh or archive this project.",
                )
            )
        for row in project_no_next:
            findings.append(
                StructuralFinding(
                    "project-without-next-action",
                    "high",
                    f"Active project '{row['title']}' has no next action.",
                    (str(row["id"]),),
                    (f"{row['project_path']}/STATE.md",),
                    recommendation="Add a verified next action or stage an archive decision.",
                )
            )

        degree: Counter[str] = Counter()
        adjacency: dict[str, set[str]] = {}
        concept_ids = {str(row["id"]) for row in concept_rows}
        for row in relationship_rows:
            left = str(row["from_id"])
            right = str(row["to_id"])
            degree[left] += 1
            degree[right] += 1
            if left in concept_ids and right in concept_ids:
                adjacency.setdefault(left, set()).add(right)
                adjacency.setdefault(right, set()).add(left)

        visited: set[str] = set()
        for concept_id in sorted(concept_ids):
            if concept_id in visited:
                continue
            component: list[str] = []
            frontier = [concept_id]
            while frontier:
                current = frontier.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.append(current)
                frontier.extend(sorted(adjacency.get(current, set()) - visited))
            if len(component) >= 25:
                findings.append(
                    StructuralFinding(
                        "oversized-concept-cluster",
                        "medium",
                        f"Concept cluster contains {len(component)} connected concepts and may be too broad.",
                        tuple(sorted(component)[:50]),
                        evidence=(f"cluster_size={len(component)}",),
                        recommendation="Create a review proposal to split the cluster into narrower maps/concepts without deleting canonical notes.",
                    )
                )

        retrieval_counts: Counter[str] = Counter()
        failed_queries: Counter[str] = Counter()
        for row in retrieval_rows:
            try:
                values = json.loads(str(row["results_json"] or "[]"))
            except json.JSONDecodeError:
                values = []
            if isinstance(values, list):
                for value in values[:5]:
                    if isinstance(value, dict) and value.get("object_id"):
                        retrieval_counts[str(value["object_id"])] += 1
            if not bool(row["answered"]):
                failed_queries[_normalize_query(str(row["query"]))] += 1

        for row in concept_rows:
            concept_id = str(row["id"])
            metadata = _json_dict(row["metadata_json"])
            source_ids = metadata.get("source_ids", [])
            sources = source_ids if isinstance(source_ids, list) else []
            note_path = str(row["note_path"] or "")
            if degree[concept_id] == 0:
                findings.append(
                    StructuralFinding(
                        "orphan-concept",
                        "medium",
                        f"Concept '{row['title']}' has no structured relationships.",
                        (concept_id,),
                        (note_path,) if note_path else (),
                        recommendation="Link the concept to verified sources/projects or review whether it belongs.",
                    )
                )
            if retrieval_counts[concept_id] >= 3 and degree[concept_id] <= 1:
                findings.append(
                    StructuralFinding(
                        "weakly-connected-frequent-concept",
                        "medium",
                        f"Frequently retrieved concept '{row['title']}' is weakly connected.",
                        (concept_id,),
                        evidence=(f"retrieval_count={retrieval_counts[concept_id]}", f"degree={degree[concept_id]}"),
                        recommendation="Link this concept to the project/source context users repeatedly need.",
                    )
                )
            if degree[concept_id] >= 15:
                findings.append(
                    StructuralFinding(
                        "high-fanout-concept",
                        "medium",
                        f"Concept '{row['title']}' has unusually high fan-out ({degree[concept_id]}).",
                        (concept_id,),
                        recommendation="Review whether the concept should be split into narrower concepts.",
                    )
                )
            if not sources:
                findings.append(
                    StructuralFinding(
                        "concept-without-provenance",
                        "high",
                        f"Concept '{row['title']}' has almost no provenance.",
                        (concept_id,),
                        recommendation="Attach source evidence before treating this concept as trustworthy.",
                    )
                )
            if note_path and len(Path(note_path).parts) > 7:
                findings.append(
                    StructuralFinding(
                        "deep-folder-structure",
                        "low",
                        f"Concept '{row['title']}' is nested unusually deeply.",
                        (concept_id,),
                        (note_path,),
                        recommendation="Review a shallower canonical location; do not auto-move it.",
                    )
                )

        # Bounded semantic duplicate candidate generation: top retrieved/recent concepts only,
        # never an unbounded all-pairs comparison and never an automatic merge.
        if self.vectors.profile.learned:
            candidate_concepts = sorted(
                concept_rows,
                key=lambda row: (-retrieval_counts[str(row["id"])], str(row["id"])),
            )[:100]
            semantic_pairs: set[tuple[str, str]] = set()
            for row in candidate_concepts:
                concept_id = str(row["id"])
                hits = self.vectors.search(str(row["title"]), limit=5, object_types={"concept"})
                for hit in hits:
                    if hit.object_id == concept_id or hit.score < 0.82:
                        continue
                    pair = tuple(sorted((concept_id, hit.object_id)))
                    if len(pair) != 2:
                        continue
                    semantic_pair: tuple[str, str] = (pair[0], pair[1])
                    if semantic_pair in semantic_pairs:
                        continue
                    semantic_pairs.add(semantic_pair)
                    findings.append(
                        StructuralFinding(
                            "semantic-duplicate-candidate",
                            "medium",
                            f"Concepts {semantic_pair[0]} and {semantic_pair[1]} are semantically close; similarity is only a review candidate.",
                            semantic_pair,
                            evidence=(f"semantic_score={hit.score:.4f}",),
                            recommendation="Compare evidence and meaning before any merge.",
                        )
                    )

        for query, count in failed_queries.items():
            if query and count >= 2:
                findings.append(
                    StructuralFinding(
                        "repeated-retrieval-failure",
                        "medium",
                        f"Query pattern repeatedly returned no useful answer: '{query}'.",
                        evidence=(f"failures={count}",),
                        expected_retrieval_benefit="A map/link/gap repair should reduce repeated grounded refusals.",
                        recommendation="Create or improve a map/link only if evidence supports the missing topic.",
                    )
                )

        gap_topics: Counter[str] = Counter(
            _normalize_query(str(row["question"])) for row in question_rows
        )
        for topic, count in gap_topics.items():
            if topic and count >= 2:
                findings.append(
                    StructuralFinding(
                        "frequent-unanswered-topic",
                        "medium",
                        f"Unanswered topic recurs {count} times: '{topic}'.",
                        evidence=(f"open_gap_count={count}",),
                        recommendation="Create a focused research/map proposal; do not invent the missing answer.",
                    )
                )

        ambiguous_count = sum(
            int(row["count"])
            for row in candidate_rows
            if str(row["confidence_state"]).lower() in {"provisional", "uncertain", "low"}
        )
        if ambiguous_count >= 3:
            findings.append(
                StructuralFinding(
                    "repeated-ambiguous-classification",
                    "low",
                    f"{ambiguous_count} project candidates remain provisional/ambiguous.",
                    evidence=(f"ambiguous_candidates={ambiguous_count}",),
                    recommendation="Improve classification evidence or create a review rule for this recurring ambiguity.",
                )
            )

        for row in state_rows:
            evidence = json.loads(str(row["evidence_json"] or "[]"))
            stale = False
            if row["verified_at"]:
                try:
                    verified = datetime.fromisoformat(str(row["verified_at"]))
                    if verified.tzinfo is None:
                        verified = verified.replace(tzinfo=UTC)
                    stale = (datetime.now(UTC) - verified.astimezone(UTC)).days > 30
                except ValueError:
                    stale = True
            if stale or not isinstance(evidence, list) or not evidence:
                findings.append(
                    StructuralFinding(
                        "stale-current-state-evidence",
                        "high",
                        f"Current state for project '{row['title']}' lacks fresh verified evidence.",
                        (str(row["id"]),),
                        evidence=(f"verified_at={row['verified_at']}",),
                        recommendation="Refresh project state from verified evidence before continuing work.",
                    )
                )

        map_root = self.paths.vault / "03 Knowledge" / "Maps"
        for path in sorted(map_root.glob("*.md")) if map_root.exists() else []:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if "[[" not in text:
                findings.append(
                    StructuralFinding(
                        "unused-empty-map",
                        "low",
                        f"Map '{path.stem}' contains no navigable knowledge links.",
                        affected_files=(path.relative_to(self.paths.vault).as_posix(),),
                        recommendation="Regenerate this map from actual knowledge; generated map refresh is safe.",
                        risks="Generated-only map content is rebuildable.",
                    )
                )

        return RestructuringReport(
            metrics=collect_metrics(self.store),
            findings=tuple(sorted(findings, key=lambda finding: (finding.finding_type, finding.signature))),
            duplicate_titles=duplicate_titles,
            broken_relationships=broken,
            stale_projects=stale_projects,
        )


class RestructuringService:
    def __init__(
        self,
        paths: BrainPaths | None = None,
        config: BrainConfig | None = None,
        store: SQLiteStore | None = None,
    ) -> None:
        self.paths = paths or BrainPaths.discover()
        self.config = config or load_config(self.paths)
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        self.analyzer = StructuralAnalyzer(self.paths, self.config, self.store)
        self.reviews = ReviewService(self.paths, self.store)
        self.transactions = TransactionManager(self.paths, self.store)

    def analyze(self) -> RestructuringReport:
        return self.analyzer.analyze()

    def generate_proposals(self, *, limit: int = 8) -> list[str]:
        report = self.analyze()
        staged: list[str] = []
        for finding in report.findings:
            if finding.severity not in {"high", "medium"}:
                continue
            marker = f"[structural:{finding.signature}]"
            if self._already_pending(marker):
                continue
            proposal = self._proposal(finding)
            plan = OperationPlan(
                created_at=datetime.now(UTC),
                permission_level=2,
                description=proposal.recommended_action,
                writes=[],
                metadata={
                    "advisory_only": True,
                    "structural_signature": finding.signature,
                    "restructuring_proposal": proposal.model_dump(mode="json"),
                },
            )
            item = self.reviews.stage(
                plan,
                review_type="restructuring-candidate",
                risk=finding.severity,
                proposal=proposal.recommended_action,
                reason=f"{marker} {proposal.reason}",
                evidence=proposal.evidence,
                current_state=finding.summary,
                proposed_state=proposal.recommended_action,
                risks=proposal.risks,
                rollback=proposal.rollback_procedure,
                recommendation="Review and create a concrete reversible operation if approved; advisory proposals cannot auto-apply.",
            )
            staged.append(item.review_id)
            if len(staged) >= limit:
                break
        self.write_audit(report)
        return staged

    def write_audit(self, report: RestructuringReport | None = None) -> str:
        report = report or self.analyze()
        relative = "07 Operations/Structural Audit.md"
        path = self.paths.vault / relative
        lines = [
            "# Structural Audit",
            "",
            "> Generated analysis only. Meaning-changing restructuring requires a review proposal and a separate reversible operation.",
            "",
            f"Generated: {datetime.now(UTC).isoformat()}",
            "",
        ]
        if not report.findings:
            lines.append("_No structural friction detected._")
        for finding in report.findings:
            lines.extend(
                [
                    f"## {finding.finding_type} — {finding.severity}",
                    "",
                    finding.summary,
                    "",
                    f"- Objects: {', '.join(finding.object_ids) or 'none'}",
                    f"- Evidence: {'; '.join(finding.evidence) or 'structural query'}",
                    f"- Expected retrieval benefit: {finding.expected_retrieval_benefit}",
                    f"- Recommendation: {finding.recommendation}",
                    f"- Risks: {finding.risks}",
                    "",
                ]
            )
        content = "\n".join(lines).rstrip() + "\n"
        self.transactions.apply(
            build_plan(
                "Refresh structural audit",
                [
                    PlannedWrite(
                        path=relative,
                        content=content,
                        expected_hash=file_sha256(path) if path.exists() else None,
                    )
                ],
                permission_level=1,
            )
        )
        return relative

    def _already_pending(self, marker: str) -> bool:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM review_items WHERE status='pending' AND payload_json LIKE ? LIMIT 1",
                (f"%{marker}%",),
            ).fetchone()
        return row is not None

    @staticmethod
    def _proposal(finding: StructuralFinding) -> RestructuringProposalModel:
        action = finding.recommendation
        return RestructuringProposalModel(
            proposal_id=f"RSP-{finding.signature}",
            finding_type=finding.finding_type,
            reason=finding.summary,
            evidence=list(finding.evidence),
            affected_objects=list(finding.object_ids),
            affected_files=list(finding.affected_files),
            expected_retrieval_benefit=finding.expected_retrieval_benefit,
            risks=finding.risks,
            rollback_procedure=(
                "No canonical mutation is performed by this advisory proposal. "
                "Any later concrete operation must carry transaction backups and row snapshots."
            ),
            recommended_action=action,
        )


def analyze_structure(store: SQLiteStore) -> RestructuringReport:
    """Phase 1/2 compatibility wrapper using the store's runtime path."""
    db = store.path.resolve()
    vault = db.parent.parent.parent
    paths = BrainPaths(repo=Path.cwd(), vault=vault)
    return StructuralAnalyzer(paths, load_config(paths), store).analyze()
