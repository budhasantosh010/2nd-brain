from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from conftest import StaticProvider

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.ingest.watcher import InboxWatcher
from second_brain.knowledge.compiler import KnowledgeCompiler
from second_brain.maintenance.monthly import MonthlyMaintenance
from second_brain.maintenance.nightly import NightlyMaintenance
from second_brain.maintenance.scheduler import MaintenanceScheduler
from second_brain.maintenance.weekly import WeeklyMaintenance
from second_brain.models import ProcessingState
from second_brain.paths import BrainPaths
from second_brain.rebuild import RebuildService
from second_brain.storage.sqlite import SQLiteStore


def test_nightly_weekly_monthly_are_idempotent_generated_views(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    config = load_config(isolated_brain)
    nightly = NightlyMaintenance(isolated_brain, config, store)
    first = nightly.run()
    second = nightly.run()
    assert isinstance(first, dict) and isinstance(second, dict)
    today = datetime.now(ZoneInfo(config.vault.timezone)).date().isoformat()
    assert (isolated_brain.vault / "08 Briefs" / "Daily" / f"{today}.md").is_file()
    assert len(list((isolated_brain.vault / "08 Briefs" / "Daily").glob(f"{today}*.md"))) == 1

    weekly = WeeklyMaintenance(isolated_brain, config, store)
    weekly.run()
    weekly.run()
    year, week, _ = datetime.now(ZoneInfo(config.vault.timezone)).isocalendar()
    assert (isolated_brain.vault / "08 Briefs" / "Weekly" / f"{year}-W{week:02d}.md").is_file()

    monthly = MonthlyMaintenance(isolated_brain, config, store)
    monthly.run()
    monthly.run()
    now = datetime.now(ZoneInfo(config.vault.timezone))
    assert (isolated_brain.vault / "08 Briefs" / "Monthly" / f"{now.year}-{now.month:02d}.md").is_file()


def test_scheduler_detects_missed_routines_after_offline_period(isolated_brain: BrainPaths) -> None:
    config = load_config(isolated_brain)
    scheduler = MaintenanceScheduler(isolated_brain, config)
    timezone = ZoneInfo(config.vault.timezone)
    now = datetime.now(timezone)
    old = now - timedelta(days=40)
    scheduler.state_path.write_text(
        json.dumps(
            {
                "nightly": old.isoformat(),
                "weekly": old.isoformat(),
                "monthly": old.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    due = scheduler.due(now)
    assert {item.name for item in due} == {"nightly", "weekly", "monthly"}
    assert all(item.missed for item in due)


def test_watcher_ingests_new_inbox_file_automatically(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    config = load_config(isolated_brain)
    config.ingestion.settle_seconds = 0.1
    service = IngestionService(isolated_brain, config, store)
    watcher = InboxWatcher(service)
    watcher.start()
    try:
        target = isolated_brain.inbox / "Text Captures" / "watcher-event.txt"
        target.write_text("watcher automatic ingestion marker", encoding="utf-8")
        deadline = time.monotonic() + 8
        count = 0
        while time.monotonic() < deadline:
            with store.connect() as conn:
                count = int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
            if count:
                break
            time.sleep(0.1)
        assert count == 1
        assert not target.exists()
    finally:
        watcher.stop()


def test_rebuild_restores_nonmaterialized_claims_sources_vectors_and_skills(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    source = input_dir / "rebuild-source.txt"
    source.write_text("Rebuild evidence for a nonmaterialized claim and concept.", encoding="utf-8")
    ingest = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(source)
    assert ingest.source_id is not None and ingest.state == ProcessingState.NEEDS_AI
    payload = {
        "purpose": "rebuild fixture",
        "entities": [],
        "project_candidates": [],
        "claims": [
            {
                "statement": "Nonmaterialized claims survive generated database rebuilds.",
                "source_id": ingest.source_id,
                "source_locator": "lines 1-1",
                "confidence_state": "supported",
                "materialize": False,
            }
        ],
        "decisions": [],
        "concepts": [
            {
                "title": "Rebuildability",
                "summary": "Generated indexes can be recreated from canonical evidence and ledgers.",
                "status": "provisional",
                "verification_state": "provisional",
                "source_ids": [ingest.source_id],
            }
        ],
        "open_loops": [],
        "questions": [],
    }
    compiled = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(payload),
    ).compile_source(ingest.source_id)
    claim_id = compiled.claims[0]
    concept_id = compiled.created_concepts[0]
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM claims WHERE id = ?", (claim_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM vector_items").fetchone()[0] > 0

    counts = RebuildService(isolated_brain).rebuild()
    rebuilt = SQLiteStore(isolated_brain.db)
    with rebuilt.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sources WHERE id = ?", (ingest.source_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM claims WHERE id = ?", (claim_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM concepts WHERE id = ?", (concept_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM vector_items").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0] >= 14
    assert counts["claims"] >= 1
    assert counts["skills"] >= 14
