"""Rebuild disposable SQLite/FTS/vector state from canonical source records and local ledgers."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import frontmatter

from second_brain.config import load_config
from second_brain.embeddings.local import LocalEmbeddingProvider
from second_brain.knowledge.linker import derived_from, supports
from second_brain.models import KnowledgeExtraction, ParsedDocument, SourceRecord
from second_brain.paths import BrainPaths
from second_brain.storage.repository import BrainRepository
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore


class RebuildService:
    def __init__(self, paths: BrainPaths | None = None) -> None:
        self.paths = paths or BrainPaths.discover()
        self.config = load_config(self.paths)

    def rebuild(self) -> dict[str, int]:
        self._archive_generated_db()
        store = SQLiteStore(self.paths.db)
        store.initialize()
        vectors = VectorStore(store, LocalEmbeddingProvider(self.config.embeddings.dimensions))
        counts = {
            "sources": 0,
            "segments": 0,
            "concepts": 0,
            "claims": 0,
            "entities": 0,
            "decisions": 0,
            "projects": 0,
            "skills": 0,
        }

        for manifest_path in sorted(self.paths.manifests.glob("SRC-*.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                source_payload = payload.get("source", {})
                source = SourceRecord.model_validate(source_payload)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            store.upsert_source(source, mime_type=payload.get("parser"))
            counts["sources"] += 1
            extracted = source.extracted_path
            if extracted and Path(extracted).exists():
                try:
                    document = ParsedDocument.model_validate_json(Path(extracted).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                store.replace_segments(document)
                counts["segments"] += len(document.segments)
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

        for ledger_path in sorted((self.paths.brain / "ledgers").glob("knowledge-SRC-*.json")):
            try:
                payload = json.loads(ledger_path.read_text(encoding="utf-8"))
                source_id = str(payload["source_id"])
                extraction = KnowledgeExtraction.model_validate(payload["extraction"])
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
            with store.transaction() as conn:
                for concept in extraction.concepts:
                    note_path = self._find_note("03 Knowledge/Concepts", concept.id)
                    BrainRepository.upsert_concept_db(conn, concept, note_path or "")
                    BrainRepository.insert_relationship_db(conn, derived_from(concept.id, source_id))
                    counts["concepts"] += 1
                for claim in extraction.claims:
                    claim.source_id = source_id
                    note_path = self._find_note("03 Knowledge/Claims", claim.id)
                    BrainRepository.insert_claim_db(conn, claim, note_path)
                    BrainRepository.insert_relationship_db(conn, supports(claim.id, source_id))
                    counts["claims"] += 1
                for entity in extraction.entities:
                    note_path = self._find_note("03 Knowledge/Entities", entity.id)
                    BrainRepository.insert_entity_db(conn, entity, note_path)
                    BrainRepository.insert_relationship_db(conn, derived_from(entity.id, source_id))
                    counts["entities"] += 1
                for decision in extraction.decisions:
                    BrainRepository.insert_decision_db(conn, decision)
                    BrainRepository.insert_relationship_db(conn, derived_from(decision.id, source_id))
                    counts["decisions"] += 1
                for loop in extraction.open_loops:
                    BrainRepository.insert_open_loop_db(
                        conn,
                        loop_id=f"LOP-rebuild-{source_id}-{counts['claims']}-{len(loop.text)}",
                        text=loop.text,
                        project_id=loop.project_id,
                        source_id=source_id,
                    )
                for candidate in extraction.project_candidates:
                    BrainRepository.insert_project_candidate_db(
                        conn,
                        candidate_id=(
                            f"PCD-rebuild-{source_id}-"
                            f"{hashlib.sha256(candidate.name.encode('utf-8')).hexdigest()[:16]}"
                        ),
                        name=candidate.name,
                        rationale=candidate.rationale,
                        confidence_state=candidate.confidence_state.value,
                        source_id=source_id,
                    )
            self._index_extraction(store, vectors, extraction, source_id)

        counts["projects"] = self._rebuild_projects(store, vectors)
        counts["skills"] = self._rebuild_skills(store, vectors)
        return counts

    def _archive_generated_db(self) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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

    def _find_note(self, root_rel: str, object_id: str) -> str | None:
        root = self.paths.vault / root_rel
        for path in root.rglob("*.md") if root.exists() else []:
            if object_id in path.name:
                return path.relative_to(self.paths.vault).as_posix()
        return None

    def _index_extraction(
        self,
        store: SQLiteStore,
        vectors: VectorStore,
        extraction: KnowledgeExtraction,
        source_id: str,
    ) -> None:
        for concept in extraction.concepts:
            text = f"{concept.title}\n{concept.summary}"
            path = self._find_note("03 Knowledge/Concepts", concept.id)
            store.index_text(object_id=concept.id, object_type="concept", title=concept.title, text=text, source_id=source_id, locator=path)
            vectors.upsert(object_id=concept.id, object_type="concept", title=concept.title, text=text, source_id=source_id, metadata={"project_ids": concept.project_ids, "locator": path})
        for claim in extraction.claims:
            store.index_text(object_id=claim.id, object_type="claim", title="Claim", text=claim.statement, source_id=source_id, locator=self._find_note("03 Knowledge/Claims", claim.id))
            vectors.upsert(object_id=claim.id, object_type="claim", title="Claim", text=claim.statement, source_id=source_id, metadata={"project_ids": claim.project_ids})
        for decision in extraction.decisions:
            text = f"{decision.decision}\n{decision.reasoning}"
            path = f"03 Knowledge/Decisions/{decision.id}.md"
            store.index_text(object_id=decision.id, object_type="decision", title="Decision", text=text, source_id=source_id, locator=path)
            vectors.upsert(object_id=decision.id, object_type="decision", title="Decision", text=text, source_id=source_id, metadata={"project_id": decision.project_id, "status": decision.status, "locator": path})

    def _rebuild_projects(self, store: SQLiteStore, vectors: VectorStore) -> int:
        root = self.paths.vault / "04 Projects" / "Active Projects"
        count = 0
        if not root.exists():
            return 0
        for project_file in root.glob("*/PROJECT.md"):
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
                    "INSERT OR REPLACE INTO projects(id,title,status,project_path,created_at,updated_at,metadata_json) VALUES (?,?,?,?,?,?,?)",
                    (project_id, title, str(post.metadata.get("status", "active")), rel_dir, created_at, updated_at, json.dumps(dict(post.metadata), default=str, sort_keys=True)),
                )
                state_path = project_file.parent / "STATE.md"
                if state_path.exists():
                    state_post = frontmatter.load(state_path)
                    sections = self._sections(state_post.content)
                    conn.execute(
                        """
                        INSERT INTO project_states(project_id,current_state,next_action,blockers_json,open_questions_json,evidence_json,verified_at,created_at,active)
                        VALUES (?,?,?,?,?,?,?,?,1)
                        """,
                        (
                            project_id,
                            sections.get("Current State", ""),
                            sections.get("Next Action", ""),
                            json.dumps(self._bullets(sections.get("Blockers", ""))),
                            json.dumps(self._bullets(sections.get("Open Questions", ""))),
                            json.dumps(self._bullets(sections.get("Latest Verified Evidence", ""))),
                            sections.get("Last Verified Timestamp", updated_at),
                            updated_at,
                        ),
                    )
            project_text = project_file.read_text(encoding="utf-8")
            store.index_text(object_id=project_id, object_type="project", title=title, text=project_text, locator=f"{rel_dir}/PROJECT.md")
            vectors.upsert(object_id=project_id, object_type="project", title=title, text=project_text, metadata={"project_id": project_id, "locator": f"{rel_dir}/PROJECT.md"})
            state_path = project_file.parent / "STATE.md"
            if state_path.exists():
                state_id = f"PST-{project_id[4:]}"
                state_text = state_path.read_text(encoding="utf-8")
                store.index_text(object_id=state_id, object_type="project-state", title=f"{title} — Current State", text=state_text, locator=f"{rel_dir}/STATE.md")
                vectors.upsert(object_id=state_id, object_type="project-state", title=f"{title} — Current State", text=state_text, metadata={"project_id": project_id, "locator": f"{rel_dir}/STATE.md"})
            count += 1
        return count

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
            import hashlib

            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            with store.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO skills(id,title,path,permission_level,content_hash,metadata_json) VALUES (?,?,?,?,?,?)",
                    (skill_id, title, rel, level, digest, json.dumps(dict(post.metadata), default=str, sort_keys=True)),
                )
            store.index_text(object_id=skill_id, object_type="skill", title=title, text=content, locator=rel)
            vectors.upsert(object_id=skill_id, object_type="skill", title=title, text=content, metadata={"permission_level": level, "locator": rel})
            count += 1
        return count

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
