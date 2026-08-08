from __future__ import annotations

from pathlib import Path
from typing import Any

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.paths import BrainPaths
from second_brain.providers.base import AIProvider, ProviderHealth
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.service import VerificationService


class ValidSynthesisProvider(AIProvider):
    name = "valid-synthesis"
    model = "test-v1"
    is_cloud = False

    def generate_structured(
        self,
        *,
        task: str,
        text: str,
        schema: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del text, schema
        assert task == "grounded_multi_source_synthesis_v1"
        assert context is not None
        evidence = context["evidence"]
        assert isinstance(evidence, list) and evidence
        ids = [
            str(item.get("source_id") or item.get("object_id"))
            for item in evidence[:2]
            if isinstance(item, dict)
        ]
        return {
            "answer": "Customer acquisition costs are rising while retention remains stable.",
            "claims": [
                {
                    "text": "Customer acquisition costs are rising.",
                    "evidence_ids": [ids[0]],
                },
                {
                    "text": "Retention remains stable.",
                    "evidence_ids": [ids[-1]],
                },
            ],
            "uncertainty": [],
            "conflicts": list(context.get("known_conflicts", [])),
        }

    def generate_text(self, *, task: str, text: str, context: dict[str, Any] | None = None) -> str:
        del task, context
        return text

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(True, self.name, self.model, "available")


class InvalidSynthesisProvider(ValidSynthesisProvider):
    name = "invalid-synthesis"

    def generate_structured(
        self,
        *,
        task: str,
        text: str,
        schema: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del task, text, schema, context
        return {
            "answer": "The secret launch code is INVENTED-9999.",
            "claims": [
                {
                    "text": "The secret launch code is INVENTED-9999.",
                    "evidence_ids": ["SRC-does-not-exist"],
                }
            ],
            "uncertainty": [],
            "conflicts": [],
        }


class CloudCounterProvider(ValidSynthesisProvider):
    name = "cloud-counter"
    is_cloud = True

    def __init__(self) -> None:
        self.calls = 0

    def generate_structured(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return super().generate_structured(**kwargs)


def _ingest(paths: BrainPaths, store: SQLiteStore, input_dir: Path, name: str, text: str) -> str:
    path = input_dir / name
    path.write_text(text, encoding="utf-8")
    result = IngestionService(paths, load_config(paths), store).ingest_file(path)
    assert result.source_id is not None
    return result.source_id


def test_valid_grounded_synthesis_uses_bounded_existing_evidence(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    _ingest(
        isolated_brain,
        store,
        input_dir,
        "acquisition.txt",
        "Customer acquisition cost is rising because paid advertising is more expensive.",
    )
    _ingest(
        isolated_brain,
        store,
        input_dir,
        "retention.txt",
        "Customer retention remains stable at the current level.",
    )
    service = VerificationService(
        isolated_brain,
        store,
        config=load_config(isolated_brain),
        provider=ValidSynthesisProvider(),
    )
    answer = service.ask("What is happening to customer acquisition cost and retention?")
    assert "acquisition costs are rising" in answer.answer.lower()
    assert "retention remains stable" in answer.answer.lower()
    assert answer.evidence


def test_invalid_synthesis_is_rejected_and_extractive_answer_survives(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    _ingest(
        isolated_brain,
        store,
        input_dir,
        "evidence.txt",
        "Customer acquisition cost is rising because paid advertising is more expensive.",
    )
    baseline = VerificationService(isolated_brain, store, provider=None).ask(
        "What is happening to customer acquisition cost?"
    )
    answer = VerificationService(
        isolated_brain,
        store,
        config=load_config(isolated_brain),
        provider=InvalidSynthesisProvider(),
    ).ask("What is happening to customer acquisition cost?")
    assert answer.answer == baseline.answer
    assert "INVENTED-9999" not in answer.answer


def test_cloud_synthesis_is_not_invoked_for_local_only_evidence(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    _ingest(
        isolated_brain,
        store,
        input_dir,
        "private-evidence.txt",
        "Customer acquisition cost is rising.",
    )
    config = load_config(isolated_brain)
    config.ai.allow_cloud_ai = True
    provider = CloudCounterProvider()
    answer = VerificationService(
        isolated_brain,
        store,
        config=config,
        provider=provider,
    ).ask("What is happening to customer acquisition cost?")
    assert answer.evidence
    assert provider.calls == 0
