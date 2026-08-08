"""Actionable system doctor checks."""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from typing import Any

from second_brain.bootstrap import validate_vault_structure
from second_brain.config import load_config
from second_brain.embeddings.local import LocalEmbeddingProvider
from second_brain.maintenance.health import verify_source_integrity
from second_brain.paths import BrainPaths
from second_brain.providers import create_provider
from second_brain.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    action: str = ""


def doctor(paths: BrainPaths | None = None) -> list[DoctorCheck]:
    paths = paths or BrainPaths.discover()
    checks: list[DoctorCheck] = []
    vault_exists = paths.vault.is_dir()
    checks.append(
        DoctorCheck(
            "vault",
            vault_exists,
            str(paths.vault) if vault_exists else "Runtime vault is missing.",
            "Run `second-brain init`." if not vault_exists else "",
        )
    )
    if not vault_exists:
        return checks

    missing_files, missing_dirs = validate_vault_structure(paths.vault)
    structural_ok = not missing_files and not missing_dirs
    checks.append(
        DoctorCheck(
            "template_structure",
            structural_ok,
            "Required vault structure is present."
            if structural_ok
            else f"Missing files={missing_files}; dirs={missing_dirs}",
            "Restore missing public template files without overwriting personal content."
            if not structural_ok
            else "",
        )
    )

    probe = paths.brain / "runtime" / f"doctor-write-{os.getpid()}.tmp"
    try:
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        writable = probe.read_text(encoding="utf-8") == "ok"
    except OSError as exc:
        writable = False
        write_detail = f"Vault runtime is not writable: {type(exc).__name__}: {exc}"
    else:
        write_detail = "Vault runtime write/read probe succeeded."
    finally:
        probe.unlink(missing_ok=True)
    checks.append(
        DoctorCheck(
            "write_permissions",
            writable,
            write_detail,
            "Fix filesystem permissions for the runtime vault." if not writable else "",
        )
    )

    store = SQLiteStore(paths.db)
    try:
        store.initialize()
        db_health = store.health()
        db_ok = bool(db_health["exists"]) and not db_health["pending_migrations"]
        checks.append(
            DoctorCheck(
                "database",
                db_ok,
                json.dumps(db_health, sort_keys=True),
                "Run `second-brain rebuild` or repair pending migrations." if not db_ok else "",
            )
        )
        checks.append(
            DoctorCheck(
                "fts5",
                bool(db_health["fts5"]),
                "SQLite FTS5 is available." if db_health["fts5"] else "SQLite lacks FTS5 support.",
                "Use a Python/SQLite build with FTS5 enabled." if not db_health["fts5"] else "",
            )
        )
        with store.connect() as conn:
            vector_count = int(conn.execute("SELECT COUNT(*) FROM vector_items").fetchone()[0])
            queue_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM processing_jobs WHERE state NOT IN ('COMPLETE','DUPLICATE')"
                ).fetchone()[0]
            )
        embedding = LocalEmbeddingProvider(load_config(paths).embeddings.dimensions)
        probe_vector = embedding.embed("doctor semantic probe")
        semantic_ok = len(probe_vector) == embedding.dimensions
        checks.append(
            DoctorCheck(
                "semantic_index",
                semantic_ok,
                f"Local embedding provider ready; indexed vector rows={vector_count}.",
                "Run `second-brain rebuild` if semantic rows are unexpectedly missing."
                if not semantic_ok
                else "",
            )
        )
        checks.append(DoctorCheck("queue", True, f"Outstanding durable jobs={queue_count}."))

        integrity = verify_source_integrity(store, limit=25)
        corrupt = [item for item in integrity if not item.ok]
        checks.append(
            DoctorCheck(
                "raw_source_integrity",
                not corrupt,
                f"Checked {len(integrity)} source(s); corruption findings={len(corrupt)}.",
                "Inspect corrupted/missing raw source immediately; do not accept mutation silently."
                if corrupt
                else "",
            )
        )
    except Exception as exc:
        checks.append(
            DoctorCheck(
                "database",
                False,
                f"Database readiness failed: {type(exc).__name__}: {exc}",
                "Run `second-brain rebuild` after confirming the vault is backed up.",
            )
        )

    config = load_config(paths)
    provider = create_provider(config)
    if provider is None:
        checks.append(
            DoctorCheck(
                "ai_provider",
                True,
                "No AI provider configured. Deterministic ingestion/search still works; AI compilation waits as NEEDS_AI.",
            )
        )
    else:
        health = provider.health_check()
        checks.append(
            DoctorCheck(
                "ai_provider",
                health.available,
                f"{health.provider}/{health.model}: {health.detail}",
                "Configure provider SDK/credential or switch provider." if not health.available else "",
            )
        )

    heartbeat = paths.brain / "runtime" / "heartbeat.json"
    daemon_lock = paths.locks / "daemon.lock"
    if heartbeat.exists():
        try:
            heartbeat_detail = heartbeat.read_text(encoding="utf-8").strip()
        except OSError:
            heartbeat_detail = "Heartbeat exists but could not be read."
    else:
        heartbeat_detail = "No daemon heartbeat yet."
    checks.append(
        DoctorCheck(
            "daemon",
            True,
            f"lock={'present' if daemon_lock.exists() else 'absent'}; heartbeat={heartbeat_detail}",
        )
    )
    writer_lock = paths.locks / "writer.lock"
    checks.append(
        DoctorCheck(
            "writer_lock",
            not writer_lock.exists(),
            "No canonical writer lock is currently held."
            if not writer_lock.exists()
            else f"Writer lock exists: {writer_lock}",
            "Confirm no active write, then use recovery if the lock is stale." if writer_lock.exists() else "",
        )
    )
    obsidian = paths.vault / ".obsidian" / "app.json"
    checks.append(
        DoctorCheck(
            "obsidian",
            obsidian.is_file(),
            f"Obsidian configuration: {obsidian}",
            "Restore `.obsidian/app.json` from the public template." if not obsidian.is_file() else "",
        )
    )
    mcp_available = importlib.util.find_spec("mcp") is not None
    checks.append(
        DoctorCheck(
            "mcp",
            mcp_available,
            "Python MCP SDK is installed." if mcp_available else "Python MCP SDK is not installed.",
            "Install the project's MCP dependency with `uv sync`." if not mcp_available else "",
        )
    )
    return checks


def doctor_dicts(paths: BrainPaths | None = None) -> list[dict[str, Any]]:
    return [asdict(item) for item in doctor(paths)]
