from __future__ import annotations

import json
from pathlib import Path

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.paths import BrainPaths
from second_brain.retrieval.service import RetrievalService
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.service import REFUSAL, VerificationService


def test_fixed_retrieval_benchmark_tracks_quality_metrics(
    isolated_brain: BrainPaths, store: SQLiteStore, tmp_path: Path
) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "retrieval_benchmark.json").read_text(encoding="utf-8")
    )
    source_ids: dict[str, str] = {}
    source_dir = tmp_path / "benchmark sources"
    source_dir.mkdir()
    ingestion = IngestionService(isolated_brain, load_config(isolated_brain), store)
    for spec in fixture["sources"]:
        path = source_dir / spec["filename"]
        path.write_text(spec["content"], encoding="utf-8")
        result = ingestion.ingest_file(path)
        assert result.source_id is not None
        source_ids[spec["filename"]] = result.source_id

    retrieval = RetrievalService(isolated_brain, store=store)
    verification = VerificationService(isolated_brain, store, retrieval)
    relevant_cases = 0
    recalled = 0
    reciprocal_ranks: list[float] = []
    cited = 0
    unsupported_cases = 0
    unsupported_correct = 0
    forbidden_violations = 0

    for case in fixture["cases"]:
        hits = retrieval.search(case["question"], limit=10)
        expected_filename = case["expected_filename"]
        answer = verification.ask(case["question"])
        if expected_filename is None:
            unsupported_cases += 1
            if answer.answer == REFUSAL:
                unsupported_correct += 1
        else:
            relevant_cases += 1
            expected_id = source_ids[expected_filename]
            rank = next(
                (
                    index
                    for index, hit in enumerate(hits, start=1)
                    if hit.source_id == expected_id or hit.object_id == expected_id
                ),
                None,
            )
            if rank is not None:
                recalled += 1
                reciprocal_ranks.append(1.0 / rank)
            else:
                reciprocal_ranks.append(0.0)
            if any(expected_id in citation for citation in answer.citations):
                cited += 1
            expected_fact = case["expected_fact"]
            if expected_fact:
                evidence_text = " ".join(item.excerpt for item in answer.evidence)
                assert expected_fact.lower() in evidence_text.lower()

        combined = answer.answer.lower()
        forbidden_violations += sum(
            1 for forbidden in case["forbidden_facts"] if forbidden.lower() in combined
        )

    recall_at_10 = recalled / relevant_cases
    mrr = sum(reciprocal_ranks) / relevant_cases
    citation_accuracy = cited / relevant_cases
    unsupported_answer_rate = 1.0 - (unsupported_correct / unsupported_cases)

    assert recall_at_10 >= 1.0
    assert mrr >= 0.75
    assert citation_accuracy >= 1.0
    assert unsupported_answer_rate == 0.0
    assert forbidden_violations == 0
