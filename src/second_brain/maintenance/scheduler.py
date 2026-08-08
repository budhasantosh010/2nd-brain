"""Configurable Asia/Dubai maintenance schedule with missed-run recovery."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from second_brain.config import BrainConfig
from second_brain.paths import BrainPaths


@dataclass(frozen=True, slots=True)
class DueRoutine:
    name: str
    missed: bool


class MaintenanceScheduler:
    def __init__(self, paths: BrainPaths, config: BrainConfig) -> None:
        self.paths = paths
        self.config = config
        self.state_path = paths.brain / "runtime" / "maintenance_state.json"
        self.timezone = ZoneInfo(config.vault.timezone)

    def now(self) -> datetime:
        return datetime.now(self.timezone)

    def state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def due(self, now: datetime | None = None) -> list[DueRoutine]:
        current = (now or self.now()).astimezone(self.timezone)
        state = self.state()
        due: list[DueRoutine] = []
        if self.config.maintenance.nightly_enabled and self._nightly_due(state, current):
            due.append(DueRoutine("nightly", bool(state.get("nightly"))))
        if self.config.maintenance.weekly_enabled and self._weekly_due(state, current):
            due.append(DueRoutine("weekly", bool(state.get("weekly"))))
        if self.config.maintenance.monthly_enabled and self._monthly_due(state, current):
            due.append(DueRoutine("monthly", bool(state.get("monthly"))))
        return due

    def mark_success(self, name: str, when: datetime | None = None) -> None:
        current = (when or self.now()).astimezone(self.timezone)
        state = self.state()
        state[name] = current.isoformat()
        self._atomic_json(self.state_path, state)

    def last_run(self, name: str) -> datetime | None:
        value = self.state().get(name)
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value).astimezone(self.timezone)
        except ValueError:
            return None

    def _nightly_due(self, state: dict[str, Any], current: datetime) -> bool:
        last = self._parse(state.get("nightly"))
        return last is None or last.date() < current.date()

    def _weekly_due(self, state: dict[str, Any], current: datetime) -> bool:
        last = self._parse(state.get("weekly"))
        return last is None or last.isocalendar()[:2] != current.isocalendar()[:2]

    def _monthly_due(self, state: dict[str, Any], current: datetime) -> bool:
        last = self._parse(state.get("monthly"))
        return last is None or (last.year, last.month) != (current.year, current.month)

    def _parse(self, value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value).astimezone(self.timezone)
        except ValueError:
            return None

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)
