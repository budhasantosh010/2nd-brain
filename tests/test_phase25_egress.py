from __future__ import annotations

from pathlib import Path

import pytest

from second_brain.config import load_config
from second_brain.exceptions import SecurityViolation
from second_brain.ingest.egress import SourceEgressService
from second_brain.ingest.security import TrustStore
from second_brain.ingest.service import IngestionService
from second_brain.models import Sensitivity
from second_brain.paths import BrainPaths
from second_brain.storage.durable import read_jsonl
from second_brain.storage.sqlite import SQLiteStore


def _ingest(paths: BrainPaths, store: SQLiteStore, path: Path) -> str:
    result = IngestionService(paths, load_config(paths), store).ingest_file(path)
    assert result.source_id is not None
    return result.source_id


def test_inbox_permission_lanes_and_secret_precedence(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    ai_lane = isolated_brain.inbox / "AI Allowed"
    local_lane = isolated_brain.inbox / "Local Only"
    ai_lane.mkdir(parents=True, exist_ok=True)
    local_lane.mkdir(parents=True, exist_ok=True)

    safe = ai_lane / "safe-note.txt"
    safe.write_text("Approved market research with no credentials.", encoding="utf-8")
    safe_id = _ingest(isolated_brain, store, safe)
    with store.connect() as conn:
        safe_row = conn.execute("SELECT sensitivity FROM sources WHERE id=?", (safe_id,)).fetchone()
    assert safe_row is not None
    assert safe_row["sensitivity"] == Sensitivity.CLOUD_ALLOWED.value

    local = local_lane / "private-note.txt"
    local.write_text("This stays on-device.", encoding="utf-8")
    local_id = _ingest(isolated_brain, store, local)
    with store.connect() as conn:
        local_row = conn.execute("SELECT sensitivity FROM sources WHERE id=?", (local_id,)).fetchone()
    assert local_row is not None
    assert local_row["sensitivity"] == Sensitivity.LOCAL_ONLY.value

    secret = ai_lane / "credential-note.txt"
    secret.write_text("password=super-secret-credential-value", encoding="utf-8")
    secret_id = _ingest(isolated_brain, store, secret)
    with store.connect() as conn:
        secret_row = conn.execute("SELECT sensitivity FROM sources WHERE id=?", (secret_id,)).fetchone()
    assert secret_row is not None
    assert secret_row["sensitivity"] == Sensitivity.BLOCKED.value


def test_trusted_path_and_source_overrides_are_audited_but_cannot_override_secrets(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    trust = TrustStore(isolated_brain)
    trusted = input_dir / "trusted folder"
    trusted.mkdir(parents=True)
    trust.add(trusted)

    safe = trusted / "safe.txt"
    safe.write_text("Safe approved research.", encoding="utf-8")
    safe_id = _ingest(isolated_brain, store, safe)
    assert SourceEgressService(isolated_brain, store).show(safe_id)["sensitivity"] == "cloud_allowed"

    service = SourceEgressService(isolated_brain, store)
    service.local_only(safe_id)
    assert service.show(safe_id)["sensitivity"] == "local_only"
    service.allow_cloud(safe_id)
    assert service.show(safe_id)["sensitivity"] == "cloud_allowed"

    secret = trusted / "secrets.txt"
    secret.write_text("token=this-is-a-long-secret-token-value", encoding="utf-8")
    secret_id = _ingest(isolated_brain, store, secret)
    assert service.show(secret_id)["sensitivity"] == "blocked"
    with pytest.raises(SecurityViolation, match="higher-priority security classification"):
        service.allow_cloud(secret_id)

    events = read_jsonl(isolated_brain.brain / "ledgers" / "egress-audit.jsonl")
    actions = [str(event.get("action")) for event in events]
    assert "trust_add" in actions
    assert actions.count("source_permission_change") >= 2
