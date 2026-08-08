from __future__ import annotations

from pathlib import Path

from second_brain.config import load_config
from second_brain.ingest.fingerprint import sha256_file
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.projects import ProjectService, ProjectSpec, ProjectStateInput
from second_brain.paths import BrainPaths
from second_brain.retrieval.service import RetrievalService
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.service import REFUSAL, VerificationService


def test_phase25_exact_current_and_unsupported_acceptance_metrics(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    config = load_config(isolated_brain)
    ingest = IngestionService(isolated_brain, config, store)
    source_path = input_dir / "exact benchmark source.txt"
    source_path.write_text(
        "Exact benchmark evidence says the release validation marker is EXACT-METRIC-7719.",
        encoding="utf-8",
    )
    result = ingest.ingest_file(source_path)
    assert result.source_id is not None
    source_id = result.source_id
    digest = sha256_file(source_path)

    retrieval = RetrievalService(isolated_brain, config, store)
    exact_queries = [source_id, digest[:16], source_path.name]
    exact_hits = 0
    for query in exact_queries:
        hits = retrieval.search(query, limit=5)
        if hits and (hits[0].object_id == source_id or hits[0].source_id == source_id):
            exact_hits += 1
    exact_id_recall = exact_hits / len(exact_queries)

    projects = ProjectService(isolated_brain, store)
    project_id = projects.create(
        ProjectSpec(title="Current State Metric Project", goal="Measure current-state ranking.")
    )
    projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="Old state that must not be current.",
            next_action="Move forward.",
            latest_verified_evidence=[source_id],
            source_ids=[source_id],
        ),
    )
    projects.update_state(
        project_id,
        ProjectStateInput(
            current_state="Release validation is the current state.",
            next_action="Push the verified branch.",
            latest_verified_evidence=[source_id],
            source_ids=[source_id],
        ),
    )
    current_hits = retrieval.search("What is the current status of Current State Metric Project?", limit=5)
    current_correct = any(
        hit.object_type == "project-state"
        and hit.metadata.get("project_id") == project_id
        and "Release validation is the current state" in hit.text
        for hit in current_hits[:3]
    )
    current_state_accuracy = 1.0 if current_correct else 0.0

    verifier = VerificationService(isolated_brain, store, retrieval, config=config)
    unsupported_questions = [
        "What is the favorite dessert of PERSON-NOT-IN-BRAIN-12345?",
        "What is the exact SECRET-PLAN-NOT-PRESENT-88221?",
        "What password belongs to ACCOUNT-NOT-IN-BRAIN-77221?",
    ]
    unsupported_answers = sum(
        1 for question in unsupported_questions if verifier.ask(question).answer != REFUSAL
    )
    unsupported_answer_rate = unsupported_answers / len(unsupported_questions)

    assert exact_id_recall == 1.0
    assert current_state_accuracy == 1.0
    assert unsupported_answer_rate == 0.0
