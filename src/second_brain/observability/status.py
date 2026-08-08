"""Compact status snapshot consumed by CLI, MCP and generated pages."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from second_brain.config import load_config
from second_brain.observability.metrics import collect_metrics
from second_brain.paths import BrainPaths
from second_brain.providers import create_provider
from second_brain.storage.sqlite import SQLiteStore


def brain_status(paths: BrainPaths | None = None) -> dict[str, Any]:
    paths = paths or BrainPaths.discover()
    config = load_config(paths)
    store = SQLiteStore(paths.db)
    if paths.db.exists():
        store.initialize()
    provider = create_provider(config)
    heartbeat = paths.brain / "runtime" / "heartbeat.json"
    heartbeat_data: dict[str, Any] | None = None
    if heartbeat.exists():
        try:
            value = json.loads(heartbeat.read_text(encoding="utf-8"))
            heartbeat_data = value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            heartbeat_data = None
    return {
        "vault": str(paths.vault),
        "vault_exists": paths.vault.exists(),
        "database": store.health() if paths.db.exists() else {"exists": False},
        "metrics": collect_metrics(store) if paths.db.exists() else {},
        "ai_provider": (
            asdict(provider.health_check()) if provider is not None else {
                "available": False,
                "provider": "none",
                "model": "",
                "detail": "No AI provider configured; deterministic brain remains operational.",
            }
        ),
        "embedding_provider": config.embeddings.provider,
        "heartbeat": heartbeat_data,
        "writer_lock": str(paths.locks / "writer.lock") if (paths.locks / "writer.lock").exists() else None,
    }
