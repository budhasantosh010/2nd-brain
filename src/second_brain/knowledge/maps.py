"""Generated Maps/MOCs derived from actual projects, concepts, decisions and gaps."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from second_brain.models import PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan

MAPS: dict[str, tuple[str, ...]] = {
    "AI Systems": ("ai", "llm", "agent", "model", "embedding", "retrieval", "mcp"),
    "Business": ("business", "customer", "revenue", "sales", "market", "pricing", "founder"),
    "Content": ("content", "youtube", "video", "script", "thumbnail", "post", "newsletter"),
    "Research": ("research", "source", "evidence", "study", "paper", "verify", "citation"),
    "Software": ("software", "code", "api", "database", "deployment", "git", "python", "system"),
}


@dataclass(frozen=True, slots=True)
class MapItem:
    object_id: str
    title: str
    note_path: str
    text: str
    updated_at: str


class MapGenerator:
    def __init__(self, paths: BrainPaths | None = None, store: SQLiteStore | None = None) -> None:
        self.paths = paths or BrainPaths.discover()
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        self.transactions = TransactionManager(self.paths, self.store)

    def generate(self) -> dict[str, int]:
        concepts = self._concepts()
        projects = self._projects()
        decisions = self._decisions()
        gaps = self._gaps()
        retrieval_counts = self._retrieval_counts()
        writes: list[PlannedWrite] = []
        mapped = 0
        for name, keywords in MAPS.items():
            related_concepts = self._rank(concepts, keywords, retrieval_counts)[:12]
            related_projects = self._rank(projects, keywords, retrieval_counts)[:8]
            related_decisions = self._rank(decisions, keywords, retrieval_counts)[:8]
            related_gaps = [gap for gap in gaps if self._score(gap.text, keywords) > 0][:8]
            if not related_concepts:
                related_concepts = sorted(
                    concepts,
                    key=lambda item: (-retrieval_counts.get(item.object_id, 0), item.title.lower()),
                )[:6]
            if not related_projects:
                related_projects = projects[:5]
            content = self._render(
                name,
                related_projects,
                related_concepts,
                related_decisions,
                related_gaps,
            )
            relative = f"03 Knowledge/Maps/{name}.md"
            path = self.paths.vault / relative
            expected = file_sha256(path) if path.exists() else None
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                writes.append(PlannedWrite(path=relative, content=content, expected_hash=expected))
            mapped += len(related_concepts) + len(related_projects) + len(related_decisions)
        if writes:
            self.transactions.apply(
                build_plan("Regenerate knowledge Maps/MOCs", writes, permission_level=1)
            )
        return {"maps_updated": len(writes), "objects_mapped": mapped}

    def _concepts(self) -> list[MapItem]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT id,title,summary,note_path,updated_at FROM concepts ORDER BY updated_at DESC"
            ).fetchall()
        return [
            MapItem(
                str(row["id"]),
                str(row["title"]),
                str(row["note_path"] or ""),
                f"{row['title']} {row['summary']}",
                str(row["updated_at"]),
            )
            for row in rows
            if row["note_path"]
        ]

    def _projects(self) -> list[MapItem]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT id,title,project_path,updated_at,metadata_json FROM projects "
                "WHERE status='active' ORDER BY updated_at DESC"
            ).fetchall()
        result: list[MapItem] = []
        for row in rows:
            metadata = self._json(row["metadata_json"])
            text = f"{row['title']} {metadata.get('goal', '')}"
            result.append(
                MapItem(
                    str(row["id"]),
                    str(row["title"]),
                    f"{row['project_path']}/PROJECT.md",
                    text,
                    str(row["updated_at"]),
                )
            )
        return result

    def _decisions(self) -> list[MapItem]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT id,decision,reasoning,decided_at FROM decisions "
                "WHERE status!='superseded' ORDER BY COALESCE(decided_at,'') DESC, id"
            ).fetchall()
        return [
            MapItem(
                str(row["id"]),
                str(row["decision"]),
                f"03 Knowledge/Decisions/{row['id']}.md",
                f"{row['decision']} {row['reasoning']}",
                str(row["decided_at"] or ""),
            )
            for row in rows
        ]

    def _gaps(self) -> list[MapItem]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT id,question,missing_evidence,created_at FROM questions "
                "WHERE status IN ('open','candidate_evidence') ORDER BY created_at DESC"
            ).fetchall()
        return [
            MapItem(
                str(row["id"]),
                str(row["question"]),
                "07 Operations/Knowledge Gaps.md",
                f"{row['question']} {row['missing_evidence']}",
                str(row["created_at"]),
            )
            for row in rows
        ]

    def _retrieval_counts(self) -> Counter[str]:
        counter: Counter[str] = Counter()
        with self.store.connect() as conn:
            rows = conn.execute("SELECT results_json FROM retrieval_events").fetchall()
        for row in rows:
            try:
                values = json.loads(str(row["results_json"] or "[]"))
            except json.JSONDecodeError:
                continue
            if not isinstance(values, list):
                continue
            for value in values[:5]:
                if isinstance(value, dict) and value.get("object_id"):
                    counter[str(value["object_id"])] += 1
        return counter

    def _rank(
        self,
        items: list[MapItem],
        keywords: tuple[str, ...],
        retrieval_counts: Counter[str],
    ) -> list[MapItem]:
        ranked = [
            (self._score(item.text, keywords) + min(retrieval_counts.get(item.object_id, 0), 5), item)
            for item in items
        ]
        return [
            item
            for score, item in sorted(
                (pair for pair in ranked if pair[0] > 0),
                key=lambda pair: (-pair[0], pair[1].title.lower()),
            )
        ]

    @staticmethod
    def _score(text: str, keywords: tuple[str, ...]) -> int:
        lowered = text.lower()
        return sum(1 for keyword in keywords if keyword in lowered)

    @staticmethod
    def _link(item: MapItem) -> str:
        target = item.note_path[:-3] if item.note_path.endswith(".md") else item.note_path
        return f"[[{target}|{item.title}]]"

    def _render(
        self,
        name: str,
        projects: list[MapItem],
        concepts: list[MapItem],
        decisions: list[MapItem],
        gaps: list[MapItem],
    ) -> str:
        lines = [
            f"# {name}",
            "",
            "> Generated/rebuildable navigation map from canonical knowledge, project state, retrieval use, and gaps.",
            "",
            "<!-- BEGIN GENERATED:MAP -->",
            "",
            "## Active Projects",
            "",
        ]
        lines.extend(f"- {self._link(item)}" for item in projects)
        if not projects:
            lines.append("_None mapped._")
        lines.extend(["", "## Important Concepts", ""])
        lines.extend(f"- {self._link(item)}" for item in concepts)
        if not concepts:
            lines.append("_None mapped._")
        lines.extend(["", "## Current Decisions", ""])
        lines.extend(f"- {self._link(item)}" for item in decisions)
        if not decisions:
            lines.append("_None mapped._")
        lines.extend(["", "## Knowledge Gaps", ""])
        lines.extend(f"- {self._link(item)}" for item in gaps)
        if not gaps:
            lines.append("_None mapped._")
        recent = sorted(projects + concepts + decisions, key=lambda item: item.updated_at, reverse=True)[:10]
        lines.extend(["", "## Recently Updated", ""])
        lines.extend(f"- {self._link(item)}" for item in recent)
        if not recent:
            lines.append("_None mapped._")
        lines.extend(["", "<!-- END GENERATED:MAP -->", ""])
        return "\n".join(lines)

    @staticmethod
    def _json(value: object) -> dict[str, object]:
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
