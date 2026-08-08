from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from second_brain.bootstrap import initialize_vault
from second_brain.paths import BrainPaths
from second_brain.providers.base import AIProvider, ProviderHealth
from second_brain.storage.sqlite import SQLiteStore


class StaticProvider(AIProvider):
    name = "static-test"
    model = "static-v1"
    is_cloud = False

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def generate_structured(
        self,
        *,
        task: str,
        text: str,
        schema: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del task, text, schema, context
        return self.payload

    def generate_text(
        self,
        *,
        task: str,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        del task, context
        return text

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(True, self.name, self.model, "static deterministic test provider")


@pytest.fixture
def isolated_brain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BrainPaths:
    vault = tmp_path / "Brain Root With Spaces" / "vault"
    monkeypatch.setenv("SECOND_BRAIN_VAULT", str(vault))
    monkeypatch.setenv("SECOND_BRAIN_AI_PROVIDER", "none")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    paths = BrainPaths.discover()
    result = initialize_vault(paths)
    assert result.ready
    assert result.vault == vault
    return paths


@pytest.fixture
def store(isolated_brain: BrainPaths) -> SQLiteStore:
    value = SQLiteStore(isolated_brain.db)
    value.initialize()
    return value


@pytest.fixture
def input_dir(tmp_path: Path) -> Path:
    path = tmp_path / "Synthetic Inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path
