"""Meaning-bearing consistency checks across canonical Markdown, SQLite and generated indexes."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import frontmatter

from second_brain.ingest.security import classify_source
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class ConsistencyFinding:
    check: str
    ok: bool
    object_id: str
    detail: str
    severity: str = "error"

    @property
    def code(self) -> str:
        if self.check == "concept_markdown" and "summary_match=False" in self.detail:
            return "concept-summary-disagreement"
        if self.check == "concept_markdown":
            return "concept-markdown-disagreement"
        if self.check == "relationship_endpoint":
            return "relationship-missing-endpoint"
        if self.check == "project_state_markdown":
            return "project-state-disagreement"
        if self.check == "decision_markdown":
            return "decision-status-disagreement"
        if self.check == "egress_secret_precedence":
            return "secret-egress-policy-violation"
        return self.check.replace("_", "-")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code"] = self.code
        return payload


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    ok: bool
    findings: tuple[ConsistencyFinding, ...]

    @property
    def canonical_errors(self) -> tuple[ConsistencyFinding, ...]:
        return tuple(item for item in self.findings if not item.ok and item.severity == "error")

    @property
    def generated_warnings(self) -> tuple[ConsistencyFinding, ...]:
        return tuple(item for item in self.findings if not item.ok and item.severity != "error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "canonical_errors": [item.to_dict() for item in self.canonical_errors],
            "generated_warnings": [item.to_dict() for item in self.generated_warnings],
            "findings": [item.to_dict() for item in self.findings],
        }


_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _sections(content: str) -> dict[str, str]:
    matches = list(_HEADING.finditer(content))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        result[match.group(1).strip()] = content[start:end].strip()
    return result


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


class ConsistencyVerifier:
    def __init__(self, paths: BrainPaths | None = None, store: SQLiteStore | None = None) -> None:
        self.paths = paths or BrainPaths.discover()
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()

    def verify(self) -> ConsistencyReport:
        findings: list[ConsistencyFinding] = []
        findings.extend(self._concepts())
        findings.extend(self._projects())
        findings.extend(self._decisions())
        findings.extend(self._relationships())
        findings.extend(self._indexes())
        findings.extend(self._egress())
        errors = [item for item in findings if not item.ok and item.severity == "error"]
        return ConsistencyReport(not errors, tuple(findings))

    def _concepts(self) -> list[ConsistencyFinding]:
        findings: list[ConsistencyFinding] = []
        with self.store.connect() as conn:
            rows = conn.execute("SELECT id,title,summary,note_path FROM concepts ORDER BY id").fetchall()
        for row in rows:
            concept_id = str(row["id"])
            note_path = str(row["note_path"] or "")
            if not note_path:
                findings.append(ConsistencyFinding("concept_markdown", False, concept_id, "DB concept has no canonical note_path"))
                continue
            path = self.paths.vault / note_path
            if not path.is_file():
                findings.append(ConsistencyFinding("concept_markdown", False, concept_id, f"Canonical concept note is missing: {note_path}"))
                continue
            try:
                post = frontmatter.load(path)
            except Exception as exc:
                findings.append(ConsistencyFinding("concept_markdown", False, concept_id, f"Cannot parse concept note: {type(exc).__name__}"))
                continue
            sections = _sections(post.content)
            note_id = str(post.metadata.get("id", ""))
            note_title = str(post.metadata.get("title", ""))
            note_summary = sections.get("Summary", sections.get("Current Understanding", ""))
            if note_id != concept_id or note_title != str(row["title"]) or note_summary != str(row["summary"]):
                findings.append(
                    ConsistencyFinding(
                        "concept_markdown",
                        False,
                        concept_id,
                        f"Markdown/SQLite disagreement: id={note_id!r}, title={note_title!r}, summary_match={note_summary == str(row['summary'])}",
                    )
                )
            else:
                findings.append(ConsistencyFinding("concept_markdown", True, concept_id, "Canonical concept Markdown matches SQLite."))
        return findings

    def _projects(self) -> list[ConsistencyFinding]:
        findings: list[ConsistencyFinding] = []
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.id,p.project_path,ps.current_state,ps.next_action,ps.blockers_json,
                       ps.open_questions_json,ps.evidence_json
                FROM projects p JOIN project_states ps ON ps.project_id=p.id AND ps.active=1
                ORDER BY p.id
                """
            ).fetchall()
        for row in rows:
            project_id = str(row["id"])
            path = self.paths.vault / str(row["project_path"]) / "STATE.md"
            if not path.is_file():
                findings.append(ConsistencyFinding("project_state_markdown", False, project_id, f"STATE.md missing: {path.relative_to(self.paths.vault).as_posix()}"))
                continue
            try:
                post = frontmatter.load(path)
            except Exception as exc:
                findings.append(ConsistencyFinding("project_state_markdown", False, project_id, f"Cannot parse STATE.md: {type(exc).__name__}"))
                continue
            sections = _sections(post.content)
            checks = {
                "Current State": str(row["current_state"]),
                "Next Action": str(row["next_action"] or "") or "_Not defined._",
            }
            mismatch = [name for name, expected in checks.items() if sections.get(name, "") != expected]
            if mismatch:
                findings.append(ConsistencyFinding("project_state_markdown", False, project_id, "STATE.md/SQLite mismatch in: " + ", ".join(mismatch)))
            else:
                findings.append(ConsistencyFinding("project_state_markdown", True, project_id, "Current STATE.md matches SQLite current state."))
        return findings

    def _decisions(self) -> list[ConsistencyFinding]:
        findings: list[ConsistencyFinding] = []
        with self.store.connect() as conn:
            rows = conn.execute("SELECT id,status,superseded_by FROM decisions ORDER BY id").fetchall()
        for row in rows:
            decision_id = str(row["id"])
            path = self.paths.vault / "03 Knowledge" / "Decisions" / f"{decision_id}.md"
            if not path.is_file():
                findings.append(ConsistencyFinding("decision_markdown", False, decision_id, "Canonical decision note is missing."))
                continue
            try:
                post = frontmatter.load(path)
            except Exception as exc:
                findings.append(ConsistencyFinding("decision_markdown", False, decision_id, f"Cannot parse decision note: {type(exc).__name__}"))
                continue
            note_status = str(post.metadata.get("status", ""))
            db_status = str(row["status"])
            note_superseded_by = str(post.metadata.get("superseded_by") or "")
            db_superseded_by = str(row["superseded_by"] or "")
            if note_status != db_status or note_superseded_by != db_superseded_by:
                findings.append(
                    ConsistencyFinding(
                        "decision_markdown",
                        False,
                        decision_id,
                        f"Decision Markdown/SQLite mismatch: status {note_status!r}!={db_status!r} or superseded_by {note_superseded_by!r}!={db_superseded_by!r}",
                    )
                )
            else:
                findings.append(ConsistencyFinding("decision_markdown", True, decision_id, "Decision note status matches SQLite."))
        return findings

    def _known_ids(self) -> set[str]:
        ids: set[str] = set()
        with self.store.connect() as conn:
            for table in ("sources", "source_segments", "concepts", "claims", "entities", "projects", "decisions", "skills"):
                column = "segment_id" if table == "source_segments" else "id"
                ids.update(str(row[0]) for row in conn.execute(f"SELECT {column} FROM {table}").fetchall())
            project_ids = [str(row[0]) for row in conn.execute("SELECT id FROM projects").fetchall()]
        ids.update(f"PST-{value[4:]}" for value in project_ids if value.startswith("PRJ-"))
        return ids

    def _relationships(self) -> list[ConsistencyFinding]:
        findings: list[ConsistencyFinding] = []
        known = self._known_ids()
        with self.store.connect() as conn:
            rows = conn.execute("SELECT id,from_id,to_id FROM relationships ORDER BY id").fetchall()
        for row in rows:
            missing = [str(value) for value in (row["from_id"], row["to_id"]) if str(value) not in known]
            if missing:
                findings.append(ConsistencyFinding("relationship_endpoint", False, str(row["id"]), "Missing relationship endpoint(s): " + ", ".join(missing)))
        if not findings:
            findings.append(ConsistencyFinding("relationship_endpoint", True, "relationships", "All relationship endpoints exist."))
        return findings

    def _indexes(self) -> list[ConsistencyFinding]:
        findings: list[ConsistencyFinding] = []
        known = self._known_ids()
        with self.store.connect() as conn:
            fts = conn.execute("SELECT DISTINCT object_id FROM search_fts").fetchall()
            vectors = conn.execute("SELECT object_id FROM vector_items").fetchall()
        missing_fts = sorted(str(row[0]) for row in fts if str(row[0]) not in known)
        missing_vectors = sorted(str(row[0]) for row in vectors if str(row[0]) not in known)
        findings.append(
            ConsistencyFinding(
                "fts_orphans",
                not missing_fts,
                "search_fts",
                "No missing FTS objects." if not missing_fts else "FTS references missing object(s): " + ", ".join(missing_fts[:20]),
                severity="warning" if missing_fts else "error",
            )
        )
        findings.append(
            ConsistencyFinding(
                "vector_orphans",
                not missing_vectors,
                "vector_items",
                "No missing vector objects." if not missing_vectors else "Vector index references missing object(s): " + ", ".join(missing_vectors[:20]),
                severity="warning" if missing_vectors else "error",
            )
        )
        return findings

    def _egress(self) -> list[ConsistencyFinding]:
        findings: list[ConsistencyFinding] = []
        with self.store.connect() as conn:
            rows = conn.execute("SELECT id,raw_path,sensitivity FROM sources WHERE sensitivity='cloud_allowed'").fetchall()
        for row in rows:
            raw_path = Path(str(row["raw_path"] or ""))
            if not raw_path.is_file():
                continue
            classification = classify_source(raw_path, scan_secrets=True)
            if classification.sensitivity.value in {"blocked", "sensitive"}:
                findings.append(
                    ConsistencyFinding(
                        "egress_secret_precedence",
                        False,
                        str(row["id"]),
                        "Source is cloud_allowed but a fresh scan classifies it blocked/sensitive.",
                    )
                )
        if not findings:
            findings.append(ConsistencyFinding("egress_secret_precedence", True, "sources", "No cloud-allowed source violates secret/sensitive precedence."))
        return findings
