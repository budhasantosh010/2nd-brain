"""Materialize useful structured relationships into bounded Obsidian generated blocks."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from second_brain.models import PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan

BEGIN = "<!-- BEGIN GENERATED:RELATIONSHIPS -->"
END = "<!-- END GENERATED:RELATIONSHIPS -->"


@dataclass(frozen=True, slots=True)
class ObjectRef:
    object_id: str
    label: str
    note_path: str | None
    source_id: str | None = None
    locator: str | None = None


@dataclass(frozen=True, slots=True)
class Edge:
    left: str
    right: str
    relation: str


class MarkdownGraphMaterializer:
    def __init__(self, paths: BrainPaths | None = None, store: SQLiteStore | None = None) -> None:
        self.paths = paths or BrainPaths.discover()
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        self.transactions = TransactionManager(self.paths, self.store)

    def materialize(self) -> dict[str, int]:
        refs = self._refs()
        edges = self._edges(refs)
        adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for edge in edges:
            adjacency[edge.left].append((edge.relation, edge.right))
            inverse = self._inverse(edge.relation)
            adjacency[edge.right].append((inverse, edge.left))

        writes: list[PlannedWrite] = []
        broken_links = 0
        for object_id, relations in sorted(adjacency.items()):
            ref = refs.get(object_id)
            if ref is None or ref.note_path is None:
                continue
            path = self.paths.vault / ref.note_path
            if not path.is_file():
                continue
            lines: list[str] = []
            seen: set[tuple[str, str]] = set()
            for relation, target_id in sorted(relations, key=lambda item: (item[0], item[1])):
                key = (relation, target_id)
                if key in seen:
                    continue
                seen.add(key)
                target = refs.get(target_id)
                if target is None:
                    lines.append(f"- {relation} → `{target_id}`")
                    continue
                rendered, broken = self._render_target(target)
                broken_links += int(broken)
                lines.append(f"- {relation} → {rendered}")
            block = "\n".join(lines) if lines else "_No useful structured relationships._"
            original = path.read_text(encoding="utf-8")
            updated = replace_generated_block(original, block)
            if updated != original:
                writes.append(
                    PlannedWrite(
                        path=ref.note_path,
                        content=updated,
                        expected_hash=file_sha256(path),
                    )
                )

        if writes:
            self.transactions.apply(
                build_plan(
                    "Materialize structured relationships into Obsidian notes",
                    writes,
                    permission_level=1,
                )
            )
        return {"notes_updated": len(writes), "edges": len(edges), "broken_links": broken_links}

    def validate_wikilinks(self) -> list[str]:
        findings: list[str] = []
        link_re = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]")
        for path in self.paths.vault.rglob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for match in link_re.finditer(text):
                target = match.group(1).strip()
                if not target or target.startswith("http"):
                    continue
                markdown_target = target if target.endswith(".md") else f"{target}.md"
                bases = [path.parent] if target.startswith("../") or target.startswith("./") else [self.paths.vault, path.parent]
                exists = any(
                    (base / target).resolve().exists()
                    or (base / markdown_target).resolve().exists()
                    for base in bases
                )
                if not exists and "/" not in target and "\\" not in target:
                    exists = any(self.paths.vault.rglob(target)) or any(
                        self.paths.vault.rglob(markdown_target)
                    )
                if not exists:
                    findings.append(
                        f"{path.relative_to(self.paths.vault).as_posix()}: broken wikilink [[{target}]]"
                    )
        return sorted(set(findings))

    def _render_target(self, target: ObjectRef) -> tuple[str, bool]:
        if target.note_path:
            path = self.paths.vault / target.note_path
            if path.is_file():
                note = target.note_path[:-3] if target.note_path.endswith(".md") else target.note_path
                return f"[[{note}|{target.label}]]", False
            return f"`{target.object_id}` ({target.label}; missing note {target.note_path})", True
        suffix = ""
        if target.source_id:
            suffix = f" @ {target.source_id}"
            if target.locator:
                suffix += f" {target.locator}"
        return f"`{target.object_id}` {target.label}{suffix}".strip(), False

    def _refs(self) -> dict[str, ObjectRef]:
        refs: dict[str, ObjectRef] = {}
        with self.store.connect() as conn:
            for row in conn.execute("SELECT id,title FROM sources").fetchall():
                object_id = str(row["id"])
                refs[object_id] = ObjectRef(
                    object_id,
                    str(row["title"]),
                    f"02 Sources/Records/{object_id}.md",
                    source_id=object_id,
                )
            for row in conn.execute("SELECT id,title,note_path FROM concepts").fetchall():
                refs[str(row["id"])] = ObjectRef(
                    str(row["id"]), str(row["title"]), str(row["note_path"]) if row["note_path"] else None
                )
            for row in conn.execute("SELECT id,name,note_path FROM entities").fetchall():
                refs[str(row["id"])] = ObjectRef(
                    str(row["id"]), str(row["name"]), str(row["note_path"]) if row["note_path"] else None
                )
            for row in conn.execute(
                "SELECT id,statement,source_id,source_locator,materialized_path FROM claims"
            ).fetchall():
                statement = str(row["statement"])
                label = statement if len(statement) <= 80 else statement[:77] + "..."
                refs[str(row["id"])] = ObjectRef(
                    str(row["id"]),
                    label,
                    str(row["materialized_path"]) if row["materialized_path"] else None,
                    str(row["source_id"]),
                    str(row["source_locator"] or ""),
                )
            for row in conn.execute("SELECT id,decision FROM decisions").fetchall():
                object_id = str(row["id"])
                label = str(row["decision"])
                refs[object_id] = ObjectRef(
                    object_id,
                    label if len(label) <= 80 else label[:77] + "...",
                    f"03 Knowledge/Decisions/{object_id}.md",
                )
            for row in conn.execute("SELECT id,title,project_path FROM projects").fetchall():
                refs[str(row["id"])] = ObjectRef(
                    str(row["id"]),
                    str(row["title"]),
                    f"{row['project_path']}/PROJECT.md",
                )
        return refs

    def _edges(self, refs: dict[str, ObjectRef]) -> list[Edge]:
        edges: set[Edge] = set()
        with self.store.connect() as conn:
            for row in conn.execute("SELECT from_id,to_id,relation FROM relationships").fetchall():
                edges.add(Edge(str(row["from_id"]), str(row["to_id"]), str(row["relation"])))

            for row in conn.execute("SELECT id,source_id FROM claims").fetchall():
                edges.add(Edge(str(row["id"]), str(row["source_id"]), "derived-from"))
            for row in conn.execute("SELECT id,metadata_json FROM concepts").fetchall():
                metadata = self._json_dict(row["metadata_json"])
                for source_id in self._string_list(metadata.get("source_ids")):
                    edges.add(Edge(str(row["id"]), source_id, "derived-from"))
                for project_id in self._string_list(metadata.get("project_ids")):
                    edges.add(Edge(str(row["id"]), project_id, "applies-to"))
            for row in conn.execute("SELECT id,metadata_json FROM entities").fetchall():
                metadata = self._json_dict(row["metadata_json"])
                for source_id in self._string_list(metadata.get("source_ids")):
                    edges.add(Edge(str(row["id"]), source_id, "derived-from"))
                for project_id in self._string_list(metadata.get("project_ids")):
                    edges.add(Edge(str(row["id"]), project_id, "applies-to"))
            for row in conn.execute(
                "SELECT id,project_id,supersedes,metadata_json FROM decisions"
            ).fetchall():
                decision_id = str(row["id"])
                if row["project_id"]:
                    edges.add(Edge(decision_id, str(row["project_id"]), "applies-to"))
                if row["supersedes"]:
                    edges.add(Edge(decision_id, str(row["supersedes"]), "supersedes"))
                metadata = self._json_dict(row["metadata_json"])
                for source_id in self._string_list(metadata.get("source_ids")):
                    edges.add(Edge(decision_id, source_id, "derived-from"))
            for row in conn.execute("SELECT id,metadata_json FROM projects").fetchall():
                metadata = self._json_dict(row["metadata_json"])
                for source_id in self._string_list(metadata.get("source_ids")):
                    edges.add(Edge(str(row["id"]), source_id, "derived-from"))

        # Do not generate link noise to objects that no longer exist in canonical/generated state.
        return sorted(
            (edge for edge in edges if edge.left in refs and edge.right in refs),
            key=lambda edge: (edge.left, edge.relation, edge.right),
        )

    @staticmethod
    def _inverse(relation: str) -> str:
        return {
            "derived-from": "evidence-for",
            "supports": "supported-by",
            "contradicts": "contradicted-by",
            "supersedes": "superseded-by",
            "applies-to": "has",
            "part-of": "contains",
            "created-by": "created",
            "mentions": "mentioned-by",
            "depends-on": "dependency-of",
            "result-of": "produced",
        }.get(relation, "related-to" if relation == "related-to" else f"inverse-{relation}")

    @staticmethod
    def _json_dict(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _string_list(value: object) -> list[str]:
        return [str(item) for item in value] if isinstance(value, list) else []


def replace_generated_block(text: str, body: str) -> str:
    block = f"{BEGIN}\n{body.rstrip()}\n{END}"
    if BEGIN in text and END in text:
        before, remainder = text.split(BEGIN, 1)
        _old, after = remainder.split(END, 1)
        return before.rstrip() + "\n\n" + block + after
    base = text.rstrip()
    return f"{base}\n\n## Connections\n\n{block}\n"
