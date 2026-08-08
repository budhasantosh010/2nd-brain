"""Actionable Phase 2.5 system doctor checks."""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from second_brain.backup import verify_backup
from second_brain.bootstrap import validate_vault_structure
from second_brain.config import load_config
from second_brain.embeddings.factory import create_embedding_provider
from second_brain.locks import lock_owner_is_live, read_lock
from second_brain.maintenance.health import verify_source_integrity
from second_brain.paths import BrainPaths
from second_brain.providers import create_provider
from second_brain.storage.durable import read_jsonl, read_resolution
from second_brain.storage.schema import SCHEMA_VERSION
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.consistency import ConsistencyVerifier


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    action: str = ""


def _check_ledger_jsonl(path: Path, *, required_keys: set[str]) -> tuple[bool, str]:
    try:
        events = read_jsonl(path)
    except ValueError as exc:
        return False, str(exc)
    bad = [
        index
        for index, event in enumerate(events, start=1)
        if not required_keys <= set(event)
    ]
    if bad:
        return False, f"{path.name}: malformed event line(s) {bad[:10]}"
    return True, f"{path.name}: {len(events)} durable event(s) valid."


def _transaction_integrity(paths: BrainPaths) -> tuple[bool, str]:
    bad: list[str] = []
    interrupted: list[str] = []
    count = 0
    for manifest in sorted(paths.transactions.glob("*/manifest.json")):
        count += 1
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bad.append(str(manifest.relative_to(paths.vault)))
            continue
        state = str(payload.get("state", ""))
        if state in {"planned", "applying"}:
            interrupted.append(str(payload.get("operation_id", manifest.parent.name)))
        elif state not in {"applied", "failed", "recovered_rollback"}:
            bad.append(f"{manifest.parent.name}:{state or 'missing-state'}")
    if bad:
        return False, f"Invalid transaction manifest(s): {bad[:10]}"
    if interrupted:
        return False, f"Interrupted transaction(s) require recovery: {interrupted[:10]}"
    return True, f"Transaction manifests checked={count}; no interrupted APPLYING state remains."


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
        write_detail = "Vault runtime write/read probe succeeded."
    except OSError as exc:
        writable = False
        write_detail = f"Vault runtime is not writable: {type(exc).__name__}: {exc}"
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

    config = load_config(paths)
    store = SQLiteStore(paths.db)
    try:
        store.initialize()
        db_health = store.health()
        current_schema = int(db_health["schema_version"])
        schema_ok = current_schema == SCHEMA_VERSION and not db_health["pending_migrations"]
        checks.append(
            DoctorCheck(
                "schema_version",
                schema_ok,
                f"database={current_schema}; code={SCHEMA_VERSION}; pending={db_health['pending_migrations']}",
                "Run the migration/initialization path or rebuild generated state after backup."
                if not schema_ok
                else "",
            )
        )
        checks.append(
            DoctorCheck(
                "database",
                bool(db_health["exists"]),
                json.dumps(db_health, sort_keys=True),
                "Run `second-brain rebuild` after securing a durable backup."
                if not db_health["exists"]
                else "",
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

        embedding = create_embedding_provider(config, paths)
        metadata = embedding.metadata
        with store.connect() as conn:
            profile = conn.execute(
                "SELECT * FROM embedding_profiles WHERE active=1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            vector_count = int(conn.execute("SELECT COUNT(*) FROM vector_items").fetchone()[0])
            segment_count = int(conn.execute("SELECT COUNT(*) FROM source_segments").fetchone()[0])
            queue_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM processing_jobs "
                    "WHERE state NOT IN ('COMPLETE','DUPLICATE','NEEDS_AI','NEEDS_ENRICHMENT','NEEDS_REVIEW')"
                ).fetchone()[0]
            )
            pending_reviews = int(
                conn.execute("SELECT COUNT(*) FROM review_items WHERE status='pending'").fetchone()[0]
            )
        profile_key = (
            (
                str(profile["provider"]),
                str(profile["model"]),
                str(profile["revision"]),
                int(profile["dimensions"]),
                str(profile["schema_version"]),
            )
            if profile is not None
            else None
        )
        profile_ok = profile_key is not None and profile_key == metadata.profile_key()
        checks.append(
            DoctorCheck(
                "embedding_provider",
                metadata.dimensions > 0,
                f"provider={metadata.provider}; model={metadata.model}; dimensions={metadata.dimensions}; learned={metadata.learned}",
            )
        )
        checks.append(
            DoctorCheck(
                "embedding_profile",
                profile_ok,
                f"configured={metadata.profile_key()}; active={profile_key}",
                "Run `second-brain rebuild` to regenerate vectors under the configured profile."
                if not profile_ok
                else "",
            )
        )
        vector_fresh = vector_count >= segment_count if segment_count else True
        checks.append(
            DoctorCheck(
                "vector_freshness",
                vector_fresh,
                f"vector_rows={vector_count}; source_segments={segment_count}",
                "Run `second-brain rebuild` if generated semantic rows are missing."
                if not vector_fresh
                else "",
            )
        )
        checks.append(DoctorCheck("queue", True, f"Outstanding active/error jobs={queue_count}."))
        checks.append(
            DoctorCheck(
                "pending_reviews",
                True,
                f"Pending human review items={pending_reviews}.",
            )
        )

        integrity = verify_source_integrity(store)
        corrupt = [item for item in integrity if not item.ok]
        checks.append(
            DoctorCheck(
                "raw_source_integrity",
                not corrupt,
                f"Checked {len(integrity)} source(s); corruption findings={len(corrupt)}.",
                "Inspect missing/corrupt raw evidence; never accept mutation silently." if corrupt else "",
            )
        )

        consistency = ConsistencyVerifier(paths, store).verify()
        checks.append(
            DoctorCheck(
                "canonical_consistency",
                consistency.ok,
                f"canonical_errors={len(consistency.canonical_errors)}; generated_warnings={len(consistency.generated_warnings)}",
                "Run `second-brain verify` and resolve meaning-bearing disagreement before rebuild."
                if not consistency.ok
                else (
                    "Generated index warnings can be repaired with `second-brain rebuild`."
                    if consistency.generated_warnings
                    else ""
                ),
            )
        )
    except Exception as exc:
        checks.append(
            DoctorCheck(
                "database",
                False,
                f"Database readiness failed: {type(exc).__name__}: {exc}",
                "Back up durable state, then run migration/rebuild diagnostics.",
            )
        )

    resolution_files = sorted((paths.brain / "ledgers" / "resolutions").glob("*.json"))
    invalid_resolutions = [path.name for path in resolution_files if read_resolution(path) is None]
    checks.append(
        DoctorCheck(
            "resolution_ledgers",
            not invalid_resolutions,
            f"resolution_ledgers={len(resolution_files)}; invalid={invalid_resolutions[:10]}",
            "Restore invalid canonical-resolution ledgers from backup/history before destructive rebuild."
            if invalid_resolutions
            else "",
        )
    )

    project_ledgers = sorted((paths.brain / "ledgers" / "projects").glob("*.jsonl"))
    project_ok = True
    project_details: list[str] = []
    for ledger in project_ledgers:
        ok, detail = _check_ledger_jsonl(ledger, required_keys={"event_id", "project_id", "current_state", "status"})
        project_ok &= ok
        if not ok:
            project_details.append(detail)
    checks.append(
        DoctorCheck(
            "project_history",
            project_ok,
            f"project_ledgers={len(project_ledgers)}" + (f"; errors={project_details[:5]}" if project_details else ""),
            "Restore malformed project history from a durable backup." if not project_ok else "",
        )
    )

    gap_path = paths.brain / "ledgers" / "knowledge-gaps.jsonl"
    gap_ok, gap_detail = _check_ledger_jsonl(
        gap_path,
        required_keys={"event_id", "question_id", "question", "event"},
    )
    checks.append(
        DoctorCheck(
            "knowledge_gap_history",
            gap_ok,
            gap_detail,
            "Restore/repair the append-only knowledge-gap ledger from backup." if not gap_ok else "",
        )
    )

    tx_ok, tx_detail = _transaction_integrity(paths)
    checks.append(
        DoctorCheck(
            "transaction_consistency",
            tx_ok,
            tx_detail,
            "Run `second-brain recover`; if recovery cannot prove consistency, restore from backup."
            if not tx_ok
            else "",
        )
    )

    for lock_type in ("writer", "daemon"):
        lock_path = paths.locks / f"{lock_type}.lock"
        lock_metadata = read_lock(lock_path)
        if not lock_path.exists():
            ok = True
            detail = "lock absent"
        elif lock_metadata is None:
            ok = False
            detail = "lock exists but metadata is invalid/stale"
        elif lock_owner_is_live(lock_metadata):
            ok = True
            detail = f"live owner pid={lock_metadata.pid}; started={lock_metadata.process_started_at}"
        else:
            ok = False
            detail = f"stale owner pid={lock_metadata.pid}; created_at={lock_metadata.created_at}"
        checks.append(
            DoctorCheck(
                f"{lock_type}_lock",
                ok,
                detail,
                "Use crash-safe recovery/startup to clear the stale lock." if not ok else "",
            )
        )

    heartbeat = paths.brain / "runtime" / "heartbeat.json"
    if heartbeat.exists():
        try:
            heartbeat_detail = heartbeat.read_text(encoding="utf-8").strip()
        except OSError:
            heartbeat_detail = "Heartbeat exists but could not be read."
    else:
        heartbeat_detail = "No daemon heartbeat; daemon may simply be stopped."
    checks.append(DoctorCheck("daemon_heartbeat", True, heartbeat_detail))

    provider = create_provider(config)
    if provider is None:
        checks.append(
            DoctorCheck(
                "ai_provider",
                True,
                "No AI provider configured. Deterministic ingestion/search works; AI compilation remains pending.",
            )
        )
    else:
        try:
            health = provider.health_check()
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    "ai_provider",
                    False,
                    f"provider health failed: {type(exc).__name__}",
                    "Check provider SDK/credential/network configuration without exposing credentials.",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    "ai_provider",
                    health.available,
                    f"{health.provider}/{health.model}: {health.detail}",
                    "Configure provider SDK/credential or switch provider." if not health.available else "",
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

    backups = sorted((paths.brain / "backups").glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not backups:
        checks.append(
            DoctorCheck(
                "backup_freshness",
                True,
                "No durable backup has been created yet.",
                "Run `second-brain backup` before risky maintenance or migration.",
            )
        )
    else:
        latest = backups[0]
        verification = verify_backup(latest)
        age_days = (datetime.now(UTC).timestamp() - latest.stat().st_mtime) / 86400.0
        checks.append(
            DoctorCheck(
                "backup_freshness",
                verification.ok,
                f"latest={latest.name}; age_days={age_days:.2f}; verified={verification.ok}",
                "Create a new verified backup." if not verification.ok or age_days > 30 else "",
            )
        )
    return checks


def doctor_dicts(paths: BrainPaths | None = None) -> list[dict[str, Any]]:
    return [asdict(item) for item in doctor(paths)]
