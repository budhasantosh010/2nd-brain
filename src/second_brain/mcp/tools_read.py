"""Read-only MCP tool implementations."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from second_brain.observability.status import brain_status
from second_brain.paths import BrainPaths
from second_brain.retrieval.service import RetrievalService
from second_brain.storage.sqlite import SQLiteStore


class BrainReadTools:
    def __init__(self, paths: BrainPaths, store: SQLiteStore) -> None:
        self.paths = paths
        self.store = store
        self.retrieval = RetrievalService(paths, store=store)

    def search(self, query: str, limit: int = 12, project_id: str | None = None) -> list[dict[str, Any]]:
        return [
            dict(hit.model_dump(mode="json"))
            for hit in self.retrieval.search(query, limit=limit, project_id=project_id)
        ]

    def get_source(self, source_id: str) -> dict[str, Any]:
        row = self.store.source_by_id(source_id)
        if row is None:
            raise KeyError(f"Source not found: {source_id}")
        with self.store.connect() as conn:
            segments = conn.execute(
                "SELECT segment_id, position, locator, text FROM source_segments WHERE source_id = ? ORDER BY position",
                (source_id,),
            ).fetchall()
        return {
            "source": dict(row),
            "segments": [dict(segment) for segment in segments],
        }

    def get_note(self, relative_path: str) -> dict[str, str]:
        raw = Path(relative_path)
        if raw.is_absolute() or ".." in raw.parts:
            raise ValueError("Note path must be a relative vault path without traversal")
        if raw.parts and raw.parts[0] == ".brain":
            raise ValueError("Machine-runtime paths are not exposed through brain_get_note")
        path = (self.paths.vault / raw).resolve()
        vault = self.paths.vault.resolve()
        if path != vault and vault not in path.parents:
            raise ValueError("Note path escapes the vault")
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        return {"path": raw.as_posix(), "content": path.read_text(encoding="utf-8")}

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        folder = self.paths.vault / str(row["project_path"])
        files: dict[str, str] = {}
        for name in ("PROJECT.md", "STATE.md", "DECISIONS.md", "OPEN LOOPS.md", "CONTEXT.md", "SOURCES.md", "HANDOFF.md"):
            path = folder / name
            if path.is_file():
                files[name] = path.read_text(encoding="utf-8")
        return {"project": dict(row), "files": files}

    def get_project_state(self, project_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            current = conn.execute(
                "SELECT * FROM project_states WHERE project_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            history = conn.execute(
                "SELECT * FROM project_states WHERE project_id = ? ORDER BY id DESC",
                (project_id,),
            ).fetchall()
        if current is None:
            raise KeyError(f"Project state not found: {project_id}")
        return {"current": dict(current), "history": [dict(row) for row in history]}

    def get_decisions(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM decisions WHERE project_id = ? ORDER BY decided_at DESC, rowid DESC",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM decisions ORDER BY decided_at DESC, rowid DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def get_conflicts(self) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM conflicts WHERE status = 'open' ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_current_context(self) -> str:
        path = self.paths.vault / "00 Home" / "Current Context.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def get_unanswered_questions(self) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE status = 'open' ORDER BY created_at DESC"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("searched_json", "found_json", "metadata_json"):
                if key in item:
                    with suppress(json.JSONDecodeError):
                        item[key.removesuffix("_json")] = json.loads(str(item.pop(key)))
            result.append(item)
        return result

    def status(self) -> dict[str, Any]:
        return brain_status(self.paths)
