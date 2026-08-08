"""Durable brain backup creation and cryptographic verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore

MANIFEST_NAME = "BACKUP_MANIFEST.json"
GENERATED_PREFIXES = (
    ".brain/db/",
    ".brain/indexes/",
    ".brain/cache/",
    ".brain/logs/",
    ".brain/runtime/",
    ".brain/locks/",
    ".brain/queue/",
    ".brain/backups/",
    "02 Sources/Extracted/",
    "03 Knowledge/Maps/",
    "08 Briefs/Daily/",
    "08 Briefs/Weekly/",
    "08 Briefs/Monthly/",
)
DURABLE_BRAIN_PREFIXES = (
    ".brain/manifests/",
    ".brain/ledgers/",
    ".brain/transactions/",
    ".brain/history/",
)
DURABLE_BRAIN_FILES = {".brain/config.yaml", ".brain/trust-rules.json"}


@dataclass(frozen=True, slots=True)
class BackupManifest:
    format_version: str
    created_at: str
    schema_version: int
    vault_name: str
    files: dict[str, str]
    excluded_generated_prefixes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackupVerification:
    ok: bool
    checked: int
    errors: tuple[str, ...]
    manifest: BackupManifest | None = None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_generated(relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in GENERATED_PREFIXES)


def _include(relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    if _is_generated(normalized):
        return False
    if normalized.startswith(".brain/"):
        return normalized in DURABLE_BRAIN_FILES or any(
            normalized.startswith(prefix) for prefix in DURABLE_BRAIN_PREFIXES
        )
    return True


def create_backup(
    paths: BrainPaths | None = None,
    destination: Path | None = None,
) -> Path:
    paths = paths or BrainPaths.discover()
    store = SQLiteStore(paths.db)
    store.initialize()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = destination or (paths.brain / "backups" / f"second-brain-{stamp}.zip")
    target = target.expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target == paths.vault or paths.vault in target.parents and target.suffix.lower() != ".zip":
        raise ValueError("Backup destination must be a .zip file, not a vault directory.")

    members: dict[str, bytes] = {}
    for file_path in sorted(path for path in paths.vault.rglob("*") if path.is_file()):
        if file_path == target:
            continue
        relative = file_path.relative_to(paths.vault).as_posix()
        if not _include(relative):
            continue
        members[relative] = file_path.read_bytes()

    manifest = BackupManifest(
        format_version="second-brain-backup-v1",
        created_at=datetime.now(UTC).isoformat(),
        schema_version=store.schema_version(),
        vault_name=paths.vault.name,
        files={name: _sha256_bytes(data) for name, data in sorted(members.items())},
        excluded_generated_prefixes=GENERATED_PREFIXES,
    )
    manifest_bytes = (json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n").encode("utf-8")
    temp = target.with_name(f".{target.name}.tmp")
    with ZipFile(temp, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        archive.writestr(MANIFEST_NAME, manifest_bytes)
    temp.replace(target)
    verification = verify_backup(target)
    if not verification.ok:
        target.unlink(missing_ok=True)
        raise RuntimeError("Created backup failed self-verification: " + "; ".join(verification.errors))
    return target


def verify_backup(path: Path | str) -> BackupVerification:
    backup = Path(path).expanduser().absolute()
    errors: list[str] = []
    checked = 0
    manifest: BackupManifest | None = None
    try:
        with ZipFile(backup, "r") as archive:
            names = set(archive.namelist())
            if MANIFEST_NAME not in names:
                return BackupVerification(False, 0, ("missing backup manifest",), None)
            try:
                raw = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
                manifest = BackupManifest(
                    format_version=str(raw["format_version"]),
                    created_at=str(raw["created_at"]),
                    schema_version=int(raw["schema_version"]),
                    vault_name=str(raw["vault_name"]),
                    files={str(k): str(v) for k, v in dict(raw["files"]).items()},
                    excluded_generated_prefixes=tuple(str(v) for v in raw["excluded_generated_prefixes"]),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                return BackupVerification(False, 0, (f"invalid backup manifest: {type(exc).__name__}",), None)
            if manifest.format_version != "second-brain-backup-v1":
                errors.append(f"unsupported backup format: {manifest.format_version}")
            for name, expected in manifest.files.items():
                posix = PurePosixPath(name)
                if posix.is_absolute() or ".." in posix.parts:
                    errors.append(f"unsafe member path: {name}")
                    continue
                if name not in names:
                    errors.append(f"missing member: {name}")
                    continue
                try:
                    data = archive.read(name)
                except (BadZipFile, RuntimeError) as exc:
                    errors.append(f"unreadable member {name}: {type(exc).__name__}")
                    continue
                checked += 1
                actual = _sha256_bytes(data)
                if actual != expected:
                    errors.append(f"hash mismatch: {name}")
            unexpected = sorted(
                name for name in names if name != MANIFEST_NAME and name not in manifest.files
            )
            if unexpected:
                errors.append("unexpected unmanifested member(s): " + ", ".join(unexpected[:10]))
    except (OSError, BadZipFile) as exc:
        return BackupVerification(False, 0, (f"invalid backup archive: {type(exc).__name__}",), None)
    return BackupVerification(not errors, checked, tuple(errors), manifest)
