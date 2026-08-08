from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from second_brain.backup import MANIFEST_NAME, create_backup, verify_backup
from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore


def test_backup_contains_durable_private_state_and_excludes_generated_state(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    secret = input_dir / "private-notes.txt"
    secret.write_text("Internal local-only planning notes.", encoding="utf-8")
    ingested = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(secret)
    assert ingested.source_id is not None
    (isolated_brain.indexes / "generated.bin").write_bytes(b"generated")
    (isolated_brain.brain / "cache").mkdir(parents=True, exist_ok=True)
    (isolated_brain.brain / "cache" / "cache.bin").write_bytes(b"generated")

    backup = create_backup(isolated_brain, isolated_brain.brain / "backups" / "acceptance.zip")
    verified = verify_backup(backup)
    assert verified.ok
    with ZipFile(backup, "r") as archive:
        names = set(archive.namelist())
        assert MANIFEST_NAME in names
        assert any(name.startswith("02 Sources/Raw/") and name.endswith("private-notes.txt") for name in names)
        assert any(name.startswith(".brain/manifests/") for name in names)
        assert not any(name.startswith(".brain/db/") for name in names)
        assert not any(name.startswith(".brain/indexes/") for name in names)
        assert not any(name.startswith(".brain/cache/") for name in names)


def test_backup_verifier_rejects_missing_manifested_member(
    isolated_brain: BrainPaths,
) -> None:
    durable = isolated_brain.vault / "03 Knowledge" / "Concepts" / "durable.md"
    durable.parent.mkdir(parents=True, exist_ok=True)
    durable.write_text("# Durable\n", encoding="utf-8")
    good = create_backup(isolated_brain, isolated_brain.brain / "backups" / "good.zip")
    corrupt = isolated_brain.brain / "backups" / "corrupt.zip"
    with ZipFile(good, "r") as source:
        manifest = json.loads(source.read(MANIFEST_NAME).decode("utf-8"))
        omitted = next(iter(manifest["files"]))
        with ZipFile(corrupt, "w", compression=ZIP_DEFLATED) as target:
            for name in source.namelist():
                if name == omitted:
                    continue
                target.writestr(name, source.read(name))
    result = verify_backup(corrupt)
    assert not result.ok
    assert any("missing member" in error for error in result.errors)
