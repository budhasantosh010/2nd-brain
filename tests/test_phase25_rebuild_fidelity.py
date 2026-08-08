from __future__ import annotations

from pathlib import Path

from conftest import StaticProvider

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.compiler import KnowledgeCompiler
from second_brain.knowledge.projects import ProjectService, ProjectSpec, ProjectStateInput
from second_brain.paths import BrainPaths
from second_brain.rebuild import RebuildService
from second_brain.retrieval.service import RetrievalService
from second_brain.review.service import ReviewService
from second_brain.storage.durable import read_jsonl, read_resolution
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.service import VerificationService


def _ingest(paths: BrainPaths, store: SQLiteStore, path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    result = IngestionService(paths, load_config(paths), store).ingest_file(path)
    assert result.source_id is not None
    return result.source_id


def _payload(
    source_id: str,
    *,
    concept_summary: str | None = None,
    claim: str | None = None,
) -> dict[str, object]:
    concepts: list[dict[str, object]] = []
    if concept_summary is not None:
        concepts.append(
            {
                "title": "Canonical Rebuild",
                "summary": concept_summary,
                "status": "provisional",
                "verification_state": "provisional",
                "source_ids": [source_id],
            }
        )
    claims: list[dict[str, object]] = []
    if claim is not None:
        claims.append(
            {
                "statement": claim,
                "source_id": source_id,
                "source_locator": "lines 1-1",
                "confidence_state": "supported",
            }
        )
    return {
        "purpose": "phase 2.5 rebuild fixture",
        "entities": [],
        "project_candidates": [],
        "claims": claims,
        "decisions": [],
        "concepts": concepts,
        "open_loops": [],
        "questions": [],
    }


def _logical_snapshot(paths: BrainPaths, store: SQLiteStore, project_id: str) -> dict[str, object]:
    with store.connect() as conn:
        concepts = [
            tuple(row)
            for row in conn.execute(
                "SELECT id,title,summary,status,verification_state FROM concepts ORDER BY id"
            ).fetchall()
        ]
        relationships = [
            tuple(row)
            for row in conn.execute(
                "SELECT from_id,to_id,relation,source_id FROM relationships ORDER BY from_id,to_id,relation,source_id"
            ).fetchall()
        ]
        conflicts = [
            tuple(row)
            for row in conn.execute(
                "SELECT left_id,right_id,conflict_type,status,explanation FROM conflicts ORDER BY id"
            ).fetchall()
        ]
        states = [
            tuple(row)
            for row in conn.execute(
                "SELECT current_state,next_action,active FROM project_states WHERE project_id=? ORDER BY id",
                (project_id,),
            ).fetchall()
        ]
        gaps = [
            tuple(row)
            for row in conn.execute(
                "SELECT id,question,status,missing_evidence FROM questions ORDER BY id"
            ).fetchall()
        ]
        project_vectors = [
            tuple(row)
            for row in conn.execute(
                "SELECT object_id,object_type,title,text,source_id,metadata_json FROM vector_items "
                "WHERE object_id = ? OR object_id = ? ORDER BY object_id",
                (project_id, f"PST-{project_id[4:]}"),
            ).fetchall()
        ]
        project_fts = [
            tuple(row)
            for row in conn.execute(
                "SELECT object_id,object_type,title,text,source_id,locator FROM search_fts "
                "WHERE object_id = ? OR object_id = ? ORDER BY object_id",
                (project_id, f"PST-{project_id[4:]}"),
            ).fetchall()
        ]
        all_fts = [
            tuple(row)
            for row in conn.execute(
                "SELECT object_id,object_type,title,text,source_id,locator FROM search_fts ORDER BY object_id"
            ).fetchall()
        ]
        all_vectors = [
            tuple(row)
            for row in conn.execute(
                "SELECT object_id,object_type,title,text,source_id,metadata_json "
                "FROM vector_items ORDER BY object_id"
            ).fetchall()
        ]
    hits = RetrievalService(paths, store=store).search("approved canonical rebuild summary")
    return {
        "concepts": concepts,
        "relationships": relationships,
        "conflicts": conflicts,
        "states": states,
        "gaps": gaps,
        "project_vectors": project_vectors,
        "project_fts": project_fts,
        "all_fts": all_fts,
        "all_vectors": all_vectors,
        "retrieval_ids": [hit.object_id for hit in hits[:10]],
    }


def test_rebuild_reproduces_canonical_resolution_project_history_gaps_and_retrieval(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    # Match the real `second-brain init` lifecycle, which indexes tracked skills before use.
    RebuildService(isolated_brain).rebuild()
    store.initialize()
    source_a = _ingest(
        isolated_brain,
        store,
        input_dir / "source-a.txt",
        "Canonical rebuild originally means preserving accepted identity across regeneration.",
    )
    result_a = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(_payload(source_a, concept_summary="Original canonical rebuild summary.")),
    ).compile_source(source_a)
    canonical_id = result_a.created_concepts[0]

    source_b = _ingest(
        isolated_brain,
        store,
        input_dir / "source-b.txt",
        "A second source repeats the same canonical rebuild understanding.",
    )
    result_b = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(_payload(source_b, concept_summary="Original canonical rebuild summary.")),
    ).compile_source(source_b)
    assert result_b.duplicate_concepts == [canonical_id]

    source_c = _ingest(
        isolated_brain,
        store,
        input_dir / "source-c.txt",
        "The accepted meaning changes after review to include durable resolution ledgers.",
    )
    result_c = KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(
            _payload(
                source_c,
                concept_summary="Approved canonical rebuild summary uses durable resolution ledgers.",
            )
        ),
    ).compile_source(source_c)
    assert len(result_c.review_items) == 1
    ReviewService(isolated_brain, store).approve(result_c.review_items[0])

    source_d = _ingest(
        isolated_brain,
        store,
        input_dir / "source-d.txt",
        "Two evidence statements deliberately disagree for the contradiction fixture.",
    )
    KnowledgeCompiler(
        isolated_brain,
        load_config(isolated_brain),
        store,
        StaticProvider(
            {
                **_payload(source_d),
                "claims": [
                    {
                        "statement": "The launch plan uses cloud AI for approved sources.",
                        "source_id": source_d,
                        "source_locator": "lines 1-1",
                        "confidence_state": "supported",
                    },
                    {
                        "statement": "The launch plan does not use cloud AI for approved sources.",
                        "source_id": source_d,
                        "source_locator": "lines 1-1",
                        "confidence_state": "supported",
                    },
                ],
            }
        ),
    ).compile_source(source_d)

    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(ProjectSpec(title="Rebuild Fidelity", goal="Prove exact logical rebuild."))
    projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="State one is active.",
            last_completed="Initial state recorded.",
            next_action="Advance to state two.",
            source_ids=[source_a],
            latest_verified_evidence=[source_a],
        ),
    )
    projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="State two is current.",
            last_completed="State one completed.",
            next_action="Rebuild and compare.",
            source_ids=[source_c],
            latest_verified_evidence=[source_c],
        ),
    )

    gap_id = VerificationService(isolated_brain, store).record_unanswered(
        "What is the unrecorded Project Orion launch code?",
        searched=[canonical_id],
        found=[],
        missing="No source records the Project Orion launch code.",
    )

    resolution_a = read_resolution(
        isolated_brain.brain / "ledgers" / "resolutions" / f"{source_a}.json"
    )
    resolution_b = read_resolution(
        isolated_brain.brain / "ledgers" / "resolutions" / f"{source_b}.json"
    )
    resolution_c = read_resolution(
        isolated_brain.brain / "ledgers" / "resolutions" / f"{source_c}.json"
    )
    assert resolution_a is not None and resolution_a.concept_resolutions[0].canonical_id == canonical_id
    assert resolution_b is not None and resolution_b.concept_resolutions[0].action == "duplicate"
    assert resolution_b.concept_resolutions[0].canonical_id == canonical_id
    assert resolution_c is not None and resolution_c.concept_resolutions[0].action == "updated"
    assert resolution_c.concept_resolutions[0].canonical_id == canonical_id

    project_events_before = read_jsonl(
        isolated_brain.brain / "ledgers" / "projects" / f"{project_id}.jsonl"
    )
    gap_events_before = read_jsonl(isolated_brain.brain / "ledgers" / "knowledge-gaps.jsonl")
    assert len(project_events_before) == 3
    assert any(str(event.get("question_id")) == gap_id for event in gap_events_before)

    before = _logical_snapshot(isolated_brain, store, project_id)
    assert before["concepts"] == [
        (
            canonical_id,
            "Canonical Rebuild",
            "Approved canonical rebuild summary uses durable resolution ledgers.",
            "provisional",
            "provisional",
        )
    ]
    assert len(before["conflicts"]) >= 1
    assert len(before["states"]) == 3

    RebuildService(isolated_brain).rebuild()
    rebuilt = SQLiteStore(isolated_brain.db)
    rebuilt.initialize()
    after = _logical_snapshot(isolated_brain, rebuilt, project_id)

    assert after["project_vectors"] == before["project_vectors"], (
        f"before_vectors={before['project_vectors']} after_vectors={after['project_vectors']}"
    )
    assert after["project_fts"] == before["project_fts"], (
        f"before_fts={before['project_fts']} after_fts={after['project_fts']}"
    )
    assert after["all_fts"] == before["all_fts"]
    assert after["all_vectors"] == before["all_vectors"]
    assert after == before, f"before={before['retrieval_ids']} after={after['retrieval_ids']}"
    assert read_jsonl(
        isolated_brain.brain / "ledgers" / "projects" / f"{project_id}.jsonl"
    ) == project_events_before
    assert read_jsonl(isolated_brain.brain / "ledgers" / "knowledge-gaps.jsonl") == gap_events_before
