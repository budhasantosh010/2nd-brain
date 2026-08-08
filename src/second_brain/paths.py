"""Canonical repository and runtime vault paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BrainPaths:
    repo: Path
    vault: Path

    @classmethod
    def discover(cls, repo: Path | None = None, vault: Path | None = None) -> BrainPaths:
        root = (repo or Path(__file__).resolve().parents[2]).resolve()
        env_vault = os.getenv("SECOND_BRAIN_VAULT")
        runtime = (vault or (Path(env_vault) if env_vault else root / "vault")).resolve()
        return cls(root, runtime)

    @property
    def template(self) -> Path:
        return self.repo / "vault-template"

    @property
    def brain(self) -> Path:
        return self.vault / ".brain"

    @property
    def db(self) -> Path:
        return self.brain / "db" / "brain.sqlite"

    @property
    def indexes(self) -> Path:
        return self.brain / "indexes"

    @property
    def queue(self) -> Path:
        return self.brain / "queue"

    @property
    def logs(self) -> Path:
        return self.brain / "logs"

    @property
    def locks(self) -> Path:
        return self.brain / "locks"

    @property
    def manifests(self) -> Path:
        return self.brain / "manifests"

    @property
    def transactions(self) -> Path:
        return self.brain / "transactions"

    @property
    def history(self) -> Path:
        return self.brain / "history"

    @property
    def raw(self) -> Path:
        return self.vault / "02 Sources" / "Raw"

    @property
    def records(self) -> Path:
        return self.vault / "02 Sources" / "Records"

    @property
    def extracted(self) -> Path:
        return self.vault / "02 Sources" / "Extracted"

    @property
    def inbox(self) -> Path:
        return self.vault / "01 Inbox"

    @property
    def staging(self) -> Path:
        return self.vault / "12 Staging"

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.brain / "db",
            self.indexes,
            self.brain / "ledgers",
            self.manifests,
            self.queue,
            self.transactions,
            self.history,
            self.brain / "cache",
            self.logs,
            self.locks,
            self.brain / "runtime",
        ):
            path.mkdir(parents=True, exist_ok=True)
