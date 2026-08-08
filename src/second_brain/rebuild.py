"""Rebuild disposable SQLite/FTS/vector state from durable canonical brain data."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter

from second_brain.config import load_config
from second_brain.embeddings.factory import create_embedding_provider
from second_brain.migration import migrate_phase2_runtime
from second_brain.models import (
    ClaimRecord,
    ConceptRecord,
    DecisionRecord,
    EntityRecord,
    ParsedDocument,
    RelationshipRecord,
    SourceRecord,
    VerificationState,
)
from second_brain.paths import BrainPaths
from second_brain.storage.durable import (
    CanonicalResolutionLedger,
    KnowledgeGapEvent,
    ProjectStateEvent,
    read_jsonl,
)
from second_brain.storage.repository import BrainRepository
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore


class RebuildService:
    """Reconstruct generated state without replaying unresolved/raw AI identities."""

    def __init__(self, paths: BrainPaths | None = None) -> None:
        self.paths = paths or BrainPaths.discover()
        self.config = load_config(self.paths)

    def rebuild(self) -> dict[str, int]:
        # Capture legacy Phase 1/2 generated DB resolution truth into durable Phase 2.5 ledgers
        # before deleting/rebuilding disposable SQLite state.
        if self.paths.db.exists():
            migrate_phase2_runtime(self.paths, SQLiteStore(self.paths.db))
        self._archive_generated_db()
        store = SQLiteStore(self.paths.db)
        store.initialize()
        vectors = VectorStore(store, create_embedding_provider(self.config, self.paths))
        counts = {
            "sources": 0,
            "segments": 0,
            "concepts": 0,
            "claims": 0,
            "entities": 0,
            "decisions": 0,
            "relationships": 0,
            "conflicts": 0,
            "projects": 0,
            "project_states": 0,
            "knowledge_gaps": 0,
            "skills": 0,
        }

        counts["sources"], counts["segments"] = self._rebuild_sources(store, vectors)
        resolutions = self._resolution_ledgers()
        counts["concepts"] = self._rebuild_canonical_concepts(store, vectors)
        self._rebuild_resolution_payloads(store, vectors, resolutions, counts)
        counts["projects"], counts["project_states"] = self._rebuild_projects(store, vectors)
        counts["knowledge_gaps"] = self._rebuild_knowledge_gaps(store)
        counts["skills"] = self._rebuild_skills(store, vectors)
        return counts

    def _rebuild_sources(self, store: SQLiteStore, vectors: VectorStore) -> tuple[int, int]:
        source_count = 0
        segment_count = 0
        for manifest_path in sorted(self.paths.manifests.glob("SRC-*.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                source = SourceRecord.model_validate(payload.get("source", {}))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            store.upsert_source(source, mime_type=payload.get("parser"))
            source_count += 1
            extracted = source.extracted_path
            if extracted and Path(extracted).exists():
                try:
                    document = ParsedDocument.model_validate_json(
                        Path(extracted).read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    document = None
                if document is not None:
                    store.replace_segments(document)
                    segment_count += len(document.segments)
                    for segment in document.segments:
                        vectors.upsert(
                            object_id=segment.segment_id,
                            object_type="source-segment",
                            title=document.title,
                            text=segment.text,
                            source_id=source.id,
                            metadata={"locator": segment.locator, "position": segment.position},
                        )
            record_path = self.paths.records / f"{source.id}.md"
            if record_path.exists():
                store.index_text(
                    object_id=source.id,
                    object_type="source-record",
                    title=source.title,
                    text=record_path.read_text(encoding="utf-8"),
                    source_id=source.id,
                    locator="source record",
                )
        return source_count, segment_count

    def _resolution_ledgers(self) -> list[CanonicalResolutionLedger]:
        root = self.paths.brain / "ledgers" / "resolutions"
        result: list[CanonicalResolutionLedger] = []
        for path in sorted(root.glob("SRC-*.json")) if root.exists() else []:
            try:
                result.append(
                    CanonicalResolutionLedger.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        return result

    def _rebuild_canonical_concepts(self, store: SQLiteStore, vectors: VectorStore) -> int:
        root = self.paths.vault / "03 Knowledge" / "Concepts"
        count = 0
        for path in sorted(root.rglob("*.md")) if root.exists() else []:
            try:
                post = frontmatter.load(path)
                if str(post.metadata.get("type")) != "concept":
                    continue
                sections = self._sections(post.content)
                source_values = post.metadata.get("source_ids", [])
                project_values = post.metadata.get("project_ids", [])
                tag_values = post.metadata.get("tags", [])
                concept = ConceptRecord(
                    id=str(post.metadata["id"]),
                    title=str(post.metadata["title"]),
                    summary=sections.get("Summary", sections.get("Current Understanding", "")),
                    status=str(post.metadata.get("status", "provisional")),
                    verification_state=VerificationState(
                        str(post.metadata.get("verification_state", "provisional"))
                    ),
                    source_ids=[str(v) for v in source_values] if isinstance(source_values, list) else [],
                    project_ids=[str(v) for v in project_values] if isinstance(project_values, list) else [],
                    tags=[str(v) for v in tag_values] if isinstance(tag_values, list) else [],
                )
            except (OSError, KeyError, ValueError):
                continue
            rel = path.relative_to(self.paths.vault).as_posix()
            with store.transaction() as conn:
                BrainRepository.upsert_concept_db(conn, concept, rel)
            text = f"{concept.title}\n{concept.summary}"
            source_id = concept.source_ids[0] if concept.source_ids else None
            store.index_text(
                object_id=concept.id,
                object_type="concept",
                title=concept.title,
                text=text,
                source_id=source_id,
                locator=rel,
            )
            vectors.upsert(
                object_id=concept.id,
                object_type="concept",
                title=concept.title,
                text=text,
                source_id=source_id,
                metadata={
                    "source_ids": concept.source_ids,
                    "project_ids": concept.project_ids,
                    "status": concept.status,
                    "verification_state": concept.verification_state.value,
                    "locator": rel,
                },
            )
            count += 1
        return count

    def _rebuild_resolution_payloads(
        self,
        store: SQLiteStore,
        vectors: VectorStore,
        resolutions: list[CanonicalResolutionLedger],
        counts: dict[str, int],
    ) -> None:
        decisions: dict[str, DecisionRecord] = {}
        decision_sources: dict[str, str] = {}
        relationships: dict[str, RelationshipRecord] = {}
        conflicts: dict[str, dict[str, Any]] = {}

        with store.transaction() as conn:
            for ledger in resolutions:
                source_id = ledger.source_id
                for raw in ledger.claims:
                    payload = dict(raw)
                    materialized_path = payload.pop("materialized_path", None)
                    claim = ClaimRecord.model_validate(payload)
                    BrainRepository.insert_claim_db(
                        conn,
                        claim,
                        str(materialized_path) if materialized_path else None,
                    )
                    counts["claims"] += 1
                for raw in ledger.entities:
                    payload = dict(raw)
                    note_path = payload.pop("note_path", None)
                    entity = EntityRecord.model_validate(payload)
                    BrainRepository.insert_entity_db(
                        conn,
                        entity,
                        str(note_path) if note_path else None,
                    )
                    counts["entities"] += 1
                for raw in ledger.decisions:
                    decision = DecisionRecord.model_validate(raw)
                    decisions[decision.id] = decision
                    decision_sources[decision.id] = source_id
                for raw in ledger.relationships:
                    relation = RelationshipRecord.model_validate(raw)
                    relationships[relation.id] = relation
                for raw in ledger.conflicts:
                    conflict_id = str(raw.get("id", ""))
                    if conflict_id:
                        conflicts[conflict_id] = dict(raw)
                for raw in ledger.open_loops:
                    BrainRepository.insert_open_loop_db(
                        conn,
                        loop_id=str(raw["id"]),
                        text=str(raw.get("text", "")),
                        project_id=str(raw["project_id"]) if raw.get("project_id") else None,
                        source_id=str(raw.get("source_id") or source_id),
                    )
                for raw in ledger.project_candidates:
                    BrainRepository.insert_project_candidate_db(
                        conn,
                        candidate_id=str(raw["id"]),
                        name=str(raw.get("name", "")),
                        rationale=str(raw.get("rationale", "")),
                        confidence_state=str(raw.get("confidence_state", "provisional")),
                        source_id=str(raw.get("source_id") or source_id),
                    )
                for raw in ledger.questions:
                    BrainRepository.insert_question_db(
                        conn,
                        question_id=str(raw["id"]),
                        question=str(raw.get("question", "")),
                        source_id=str(raw.get("source_id") or source_id),
                    )

        inserted: set[str] = set()
        pending = dict(decisions)
        while pending:
            progress = False
            for decision_id, decision in list(pending.items()):
                if decision.supersedes and decision.supersedes not in inserted:
                    continue
                with store.transaction() as conn:
                    BrainRepository.insert_decision_db(conn, decision)
                inserted.add(decision_id)
                del pending[decision_id]
                counts["decisions"] += 1
                progress = True
            if not progress:
                missing = {
                    key: value.supersedes
                    for key, value in pending.items()
                    if value.supersedes and value.supersedes not in decisions
                }
                raise ValueError(f"Cannot rebuild decision supersession graph; missing predecessors: {missing}")

        for decision_id, decision in decisions.items():
            decision_source_id = decision_sources.get(decision_id)
            text, locator = self._canonical_decision_text(decision)
            store.index_text(
                object_id=decision.id,
                object_type="decision",
                title="Decision",
                text=text,
                source_id=source_id,
                locator=locator,
            )
            vectors.upsert(
                object_id=decision.id,
                object_type="decision",
                title="Decision",
                text=text,
                source_id=decision_source_id,
                metadata={
                    "project_id": decision.project_id,
                    "status": decision.status,
                    "supersedes": decision.supersedes,
                    "superseded_by": decision.superseded_by,
                    "locator": locator,
                },
            )

        with store.transaction() as conn:
            for relation in relationships.values():
                BrainRepository.insert_relationship_db(conn, relation)
                counts["relationships"] += 1
            for raw in conflicts.values():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO conflicts(
                        id,left_id,right_id,conflict_type,status,explanation,created_at,resolved_at,metadata_json
                    ) VALUES (?,?,?,?,?,?,?,NULL,?)
                    """,
                    (
                        str(raw["id"]),
                        str(raw.get("left_id", "")),
                        str(raw.get("right_id", "")),
                        str(raw.get("conflict_type", "unknown")),
                        str(raw.get("status", "open")),
                        str(raw.get("explanation", "")),
                        str(raw.get("created_at", datetime.now(UTC).isoformat())),
                        json.dumps({"source_id": raw.get("source_id")}, sort_keys=True),
                    ),
                )
                counts["conflicts"] += 1

        # Claims/entities are non-canonical when no note exists, so resolution ledgers own them.
        with store.connect() as conn:
            claim_rows = conn.execute("SELECT * FROM claims").fetchall()
            entity_rows = conn.execute("SELECT * FROM entities").fetchall()
        for row in claim_rows:
            text = str(row["statement"])
            object_id = str(row["id"])
            source_id = str(row["source_id"])
            materialized_locator = str(row["materialized_path"] or "")
            vector_locator = materialized_locator or str(row["source_locator"] or "")
            store.index_text(
                object_id=object_id,
                object_type="claim",
                title="Claim",
                text=text,
                source_id=source_id,
                locator=materialized_locator or None,
            )
            claim_metadata = json.loads(str(row["metadata_json"] or "{}"))
            project_values = (
                claim_metadata.get("project_ids", []) if isinstance(claim_metadata, dict) else []
            )
            project_ids = [str(value) for value in project_values] if isinstance(project_values, list) else []
            vectors.upsert(
                object_id=object_id,
                object_type="claim",
                title="Claim",
                text=text,
                source_id=source_id,
                metadata={
                    "project_ids": project_ids,
                    "confidence_state": str(row["confidence_state"]),
                    "locator": vector_locator or None,
                },
            )
        for row in entity_rows:
            object_id = str(row["id"])
            title = str(row["name"])
            text = f"{title}\n{row['entity_type']}"
            locator = str(row["note_path"] or "")
            entity_metadata = json.loads(str(row["metadata_json"] or "{}"))
            source_values = (
                entity_metadata.get("source_ids", []) if isinstance(entity_metadata, dict) else []
            )
            project_values = (
                entity_metadata.get("project_ids", []) if isinstance(entity_metadata, dict) else []
            )
            source_ids = [str(value) for value in source_values] if isinstance(source_values, list) else []
            project_ids = [str(value) for value in project_values] if isinstance(project_values, list) else []
            entity_source_id = source_ids[0] if source_ids else None
            store.index_text(
                object_id=object_id,
                object_type="entity",
                title=title,
                text=text,
                source_id=entity_source_id,
                locator=locator or None,
            )
            vectors.upsert(
                object_id=object_id,
                object_type="entity",
                title=title,
                text=text,
                source_id=entity_source_id,
                metadata={
                    "project_ids": project_ids,
                    "entity_type": str(row["entity_type"]),
                    "locator": locator or None,
                },
            )

    def _canonical_decision_text(self, decision: DecisionRecord) -> tuple[str, str]:
        path = self.paths.vault / "03 Knowledge" / "Decisions" / f"{decision.id}.md"
        if not path.exists():
            return f"{decision.decision}\n{decision.reasoning}", path.relative_to(self.paths.vault).as_posix()
        try:
            post = frontmatter.load(path)
            sections = self._sections(post.content)
            text = f"{sections.get('Decision', decision.decision)}\n{sections.get('Reasoning', decision.reasoning)}"
        except OSError:
            text = f"{decision.decision}\n{decision.reasoning}"
        return text, path.relative_to(self.paths.vault).as_posix()

    def _rebuild_projects(self, store: SQLiteStore, vectors: VectorStore) -> tuple[int, int]:
        root = self.paths.vault / "04 Projects" / "Active Projects"
        project_count = 0
        state_count = 0
        if not root.exists():
            return 0, 0
        for project_file in sorted(root.glob("*/PROJECT.md")):
            try:
                post = frontmatter.load(project_file)
                project_id = str(post.metadata["id"])
                title = str(post.metadata["title"])
                created_at = str(post.metadata.get("created_at", datetime.now(UTC).isoformat()))
                updated_at = str(post.metadata.get("updated_at", created_at))
                rel_dir = project_file.parent.relative_to(self.paths.vault).as_posix()
            except (OSError, KeyError):
                continue
            with store.transaction() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO projects(
                        id,title,status,project_path,created_at,updated_at,metadata_json
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        project_id,
                        title,
                        str(post.metadata.get("status", "active")),
                        rel_dir,
                        created_at,
                        updated_at,
                        json.dumps(dict(post.metadata), default=str, sort_keys=True),
                    ),
                )

            history_path = self.paths.brain / "ledgers" / "projects" / f"{project_id}.jsonl"
            events: list[ProjectStateEvent] = []
            try:
                events = [ProjectStateEvent.model_validate(item) for item in read_jsonl(history_path)]
            except ValueError:
                events = []
            if not events:
                fallback = self._project_state_from_markdown(project_file.parent / "STATE.md", project_id)
                if fallback is not None:
                    events = [fallback]

            with store.transaction() as conn:
                for index, event in enumerate(events):
                    conn.execute(
                        """
                        INSERT INTO project_states(
                            project_id,current_state,next_action,blockers_json,open_questions_json,
                            evidence_json,verified_at,created_at,active
                        ) VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            project_id,
                            event.current_state,
                            event.next_action,
                            json.dumps(event.blockers),
                            json.dumps(event.open_questions),
                            json.dumps(event.evidence),
                            event.verified_at,
                            event.timestamp,
                            1 if index == len(events) - 1 else 0,
                        ),
                    )
                    state_count += 1

            project_sections = self._sections(post.content)
            project_text = f"{title}\nGoal: {project_sections.get('Goal', '')}"
            store.index_text(
                object_id=project_id,
                object_type="project",
                title=title,
                text=project_text,
                locator=f"{rel_dir}/PROJECT.md",
            )
            vectors.upsert(
                object_id=project_id,
                object_type="project",
                title=title,
                text=project_text,
                metadata={"project_id": project_id, "locator": f"{rel_dir}/PROJECT.md"},
            )
            if events:
                current = events[-1]
                state_id = f"PST-{project_id[4:]}"
                state_text = self._project_event_text(title, current)
                source_id = next((v for v in current.evidence if v.startswith("SRC-")), None)
                store.index_text(
                    object_id=state_id,
                    object_type="project-state",
                    title=f"{title} — Current State",
                    text=state_text,
                    source_id=source_id,
                    locator=f"{rel_dir}/STATE.md",
                )
                vectors.upsert(
                    object_id=state_id,
                    object_type="project-state",
                    title=f"{title} — Current State",
                    text=state_text,
                    source_id=source_id,
                    metadata={
                        "project_id": project_id,
                        "evidence": current.evidence,
                        "locator": f"{rel_dir}/STATE.md",
                    },
                )
            project_count += 1
        return project_count, state_count

    def _project_state_from_markdown(
        self,
        path: Path,
        project_id: str,
    ) -> ProjectStateEvent | None:
        if not path.exists():
            return None
        try:
            post = frontmatter.load(path)
            sections = self._sections(post.content)
            timestamp = str(
                sections.get("Last Verified Timestamp")
                or post.metadata.get("updated_at")
                or datetime.now(UTC).isoformat()
            )
            source_values = post.metadata.get("source_ids", [])
            source_ids = [str(value) for value in source_values] if isinstance(source_values, list) else []
            return ProjectStateEvent(
                project_id=project_id,
                timestamp=timestamp,
                current_state=sections.get("Current State", ""),
                last_completed=sections.get("Last Completed", "").replace("_None recorded._", ""),
                currently_working_on=sections.get("Currently Working On", "").replace(
                    "_None recorded._", ""
                ),
                next_action=sections.get("Next Action", "").replace("_Not defined._", ""),
                blockers=self._bullets(sections.get("Blockers", "")),
                open_questions=self._bullets(sections.get("Open Questions", "")),
                evidence=self._bullets(sections.get("Latest Verified Evidence", "")),
                source_ids=source_ids,
                verified_at=timestamp,
                operation_id="OP-migrated-project-state",
                status="migrated",
            )
        except (OSError, ValueError):
            return None

    @staticmethod
    def _project_event_text(title: str, event: ProjectStateEvent) -> str:
        return (
            f"{title}\nCurrent state: {event.current_state}\n"
            f"Last completed: {event.last_completed}\n"
            f"Currently working on: {event.currently_working_on}\n"
            f"Next action: {event.next_action}\n"
            f"Blockers: {'; '.join(event.blockers)}\n"
            f"Open questions: {'; '.join(event.open_questions)}"
        )

    def _rebuild_knowledge_gaps(self, store: SQLiteStore) -> int:
        path = self.paths.brain / "ledgers" / "knowledge-gaps.jsonl"
        try:
            raw_events = read_jsonl(path)
        except ValueError:
            return 0
        by_question: dict[str, list[KnowledgeGapEvent]] = {}
        for raw in raw_events:
            try:
                event = KnowledgeGapEvent.model_validate(raw)
            except ValueError:
                continue
            by_question.setdefault(event.question_id, []).append(event)
        with store.transaction() as conn:
            for question_id, events in by_question.items():
                first = events[0]
                last = events[-1]
                status_map = {
                    "opened": "open",
                    "candidate_evidence_found": "candidate_evidence",
                    "resolved": "resolved",
                    "reopened": "open",
                    "dismissed": "dismissed",
                }
                conn.execute(
                    """
                    INSERT OR REPLACE INTO questions(
                        id,question,status,searched_json,found_json,missing_evidence,
                        created_at,resolved_at,resolution_id,metadata_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        question_id,
                        first.question,
                        status_map[last.event],
                        json.dumps(first.searched),
                        json.dumps(last.found),
                        first.missing_evidence,
                        first.timestamp,
                        last.timestamp if last.event == "resolved" else None,
                        last.resolution_id,
                        json.dumps({"last_gap_event_id": last.event_id}, sort_keys=True),
                    ),
                )
        return len(by_question)

    def _rebuild_skills(self, store: SQLiteStore, vectors: VectorStore) -> int:
        root = self.paths.vault / "06 Skills"
        count = 0
        for path in root.rglob("*.md") if root.exists() else []:
            if path.name == "SKILLS INDEX.md":
                continue
            try:
                post = frontmatter.load(path)
                if post.metadata.get("type") != "skill":
                    continue
                skill_id = str(post.metadata["id"])
                title = str(post.metadata["title"])
                level_value = post.metadata.get("permission_level", 0)
                level = int(level_value) if isinstance(level_value, (int, str)) else 0
                rel = path.relative_to(self.paths.vault).as_posix()
                content = path.read_text(encoding="utf-8")
            except (OSError, KeyError, ValueError):
                continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            with store.transaction() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO skills(
                        id,title,path,permission_level,content_hash,metadata_json
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (
                        skill_id,
                        title,
                        rel,
                        level,
                        digest,
                        json.dumps(dict(post.metadata), default=str, sort_keys=True),
                    ),
                )
            store.index_text(
                object_id=skill_id,
                object_type="skill",
                title=title,
                text=content,
                locator=rel,
            )
            vectors.upsert(
                object_id=skill_id,
                object_type="skill",
                title=title,
                text=content,
                metadata={"permission_level": level, "locator": rel},
            )
            count += 1
        return count

    def _archive_generated_db(self) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_dir = self.paths.history / f"rebuild-{timestamp}"
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.paths.db) + suffix)
            if path.exists():
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(backup_dir / path.name))
        if self.paths.indexes.exists():
            for child in self.paths.indexes.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)

    @staticmethod
    def _sections(body: str) -> dict[str, str]:
        result: dict[str, str] = {}
        current: str | None = None
        lines: list[str] = []
        for line in body.splitlines():
            if line.startswith("## "):
                if current is not None:
                    result[current] = "\n".join(lines).strip()
                current = line[3:].strip()
                lines = []
            elif current is not None:
                lines.append(line)
        if current is not None:
            result[current] = "\n".join(lines).strip()
        return result

    @staticmethod
    def _bullets(body: str) -> list[str]:
        return [line[2:].strip().strip("`") for line in body.splitlines() if line.startswith("- ")]
