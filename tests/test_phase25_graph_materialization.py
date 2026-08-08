from __future__ import annotations

from pathlib import Path

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.graph_materializer import (
    BEGIN,
    END,
    MarkdownGraphMaterializer,
)
from second_brain.knowledge.maps import MapGenerator
from second_brain.knowledge.projects import ProjectService, ProjectSpec
from second_brain.models import ConceptRecord, VerificationState
from second_brain.paths import BrainPaths
from second_brain.storage.repository import BrainRepository
from second_brain.storage.sqlite import SQLiteStore


def test_generated_relationship_block_preserves_human_text_and_valid_wikilinks(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    source = input_dir / "graph-source.txt"
    source.write_text("Transactional writes keep the software brain consistent.", encoding="utf-8")
    ingested = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(source)
    assert ingested.source_id is not None

    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(
        ProjectSpec(title="Graph Project", goal="Build software relationship materialization.")
    )
    concept_id = "KNO-phase25-graph-concept"
    note_rel = "03 Knowledge/Concepts/transactional-writes--KNO-phase25-graph-concept.md"
    note = isolated_brain.vault / note_rel
    human = (
        "# Transactional Writes\n\n"
        "## Human Notes\n\n"
        "This sentence belongs to a human and must never be regenerated.\n\n"
        "## Connections\n\n"
        f"{BEGIN}\n- old generated noise\n{END}\n\n"
        "## Human Tail\n\nKeep this too.\n"
    )
    note.write_text(human, encoding="utf-8")
    concept = ConceptRecord(
        id=concept_id,
        title="Transactional Writes",
        summary="Software writes are applied atomically with rollback support.",
        status="verified",
        verification_state=VerificationState.VERIFIED,
        source_ids=[ingested.source_id],
        project_ids=[project_id],
        tags=["software"],
    )
    with store.transaction() as conn:
        BrainRepository.upsert_concept_db(conn, concept, note_rel)

    materializer = MarkdownGraphMaterializer(isolated_brain, store)
    first = materializer.materialize()
    rendered = note.read_text(encoding="utf-8")
    assert first["notes_updated"] >= 1
    assert "This sentence belongs to a human and must never be regenerated." in rendered
    assert "Keep this too." in rendered
    assert "old generated noise" not in rendered
    assert f"[[02 Sources/Records/{ingested.source_id}|" in rendered
    assert "[[04 Projects/Active Projects/" in rendered
    assert rendered.count(BEGIN) == 1 and rendered.count(END) == 1
    assert materializer.validate_wikilinks() == []

    second = materializer.materialize()
    assert second["notes_updated"] == 0
    assert note.read_text(encoding="utf-8") == rendered


def test_software_map_is_generated_from_real_project_and_concept(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(
        ProjectSpec(title="Second Brain Software", goal="Implement a local software database and API.")
    )
    concept_id = "KNO-phase25-software-map"
    note_rel = "03 Knowledge/Concepts/hybrid-retrieval--KNO-phase25-software-map.md"
    (isolated_brain.vault / note_rel).write_text(
        "# Hybrid Retrieval\n\nSoftware search combines a database, embeddings, and exact IDs.\n",
        encoding="utf-8",
    )
    concept = ConceptRecord(
        id=concept_id,
        title="Hybrid Retrieval",
        summary="Software search combines a database, embeddings, and exact IDs.",
        status="verified",
        verification_state=VerificationState.VERIFIED,
        project_ids=[project_id],
        tags=["software"],
    )
    with store.transaction() as conn:
        BrainRepository.upsert_concept_db(conn, concept, note_rel)

    result = MapGenerator(isolated_brain, store).generate()
    software = (isolated_brain.vault / "03 Knowledge" / "Maps" / "Software.md").read_text(
        encoding="utf-8"
    )
    assert result["maps_updated"] >= 1
    assert "<!-- BEGIN GENERATED:MAP -->" in software
    assert "[[04 Projects/Active Projects/" in software
    assert "Second Brain Software" in software
    assert "[[03 Knowledge/Concepts/hybrid-retrieval--KNO-phase25-software-map|Hybrid Retrieval]]" in software
    assert "_No mapped Software knowledge yet._" not in software
