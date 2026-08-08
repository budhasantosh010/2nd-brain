from __future__ import annotations

from pathlib import Path

from second_brain.embeddings.base import EmbeddingMetadata, EmbeddingProvider
from second_brain.embeddings.learned import LearnedLocalEmbeddingProvider
from second_brain.embeddings.local import HashingEmbeddingProvider, LocalEmbeddingProvider
from second_brain.paths import BrainPaths
from second_brain.retrieval.benchmark import semantic_paraphrase_benchmark
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore


class TinyProvider(EmbeddingProvider):
    def __init__(self, *, model: str, dimensions: int) -> None:
        self.name = "tiny-test-provider"
        self.model = model
        self.dimensions = dimensions

    @property
    def metadata(self) -> EmbeddingMetadata:
        return EmbeddingMetadata(
            provider=self.name,
            model=self.model,
            revision="fixture-1",
            dimensions=self.dimensions,
            learned=True,
        )

    def embed(self, text: str) -> list[float]:
        seed = float((sum(ord(char) for char in text) % 7) + 1)
        raw = [seed + float(index) for index in range(self.dimensions)]
        magnitude = sum(value * value for value in raw) ** 0.5
        return [value / magnitude for value in raw]


def test_hashing_provider_is_named_as_fuzzy_fallback() -> None:
    provider = HashingEmbeddingProvider(384)
    assert provider.name == "local-fuzzy-hashing-v1"
    assert provider.metadata.learned is False
    assert LocalEmbeddingProvider is HashingEmbeddingProvider


def test_learned_provider_is_lazy_until_prepare_or_embed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    provider = LearnedLocalEmbeddingProvider(cache_dir=str(tmp_path / "models"))
    assert provider._engine is None
    assert provider.metadata.learned is True
    assert provider.metadata.model == "BAAI/bge-small-en-v1.5"


def test_embedding_profile_change_invalidates_generated_vectors(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    first = VectorStore(store, TinyProvider(model="fixture-a", dimensions=4))
    first.upsert(object_id="KNO-vector-profile", object_type="concept", title="One", text="one")
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM vector_items").fetchone()[0] == 1
        first_profile = conn.execute(
            "SELECT model,dimensions FROM embedding_profiles WHERE active=1"
        ).fetchone()
    assert first_profile is not None and tuple(first_profile) == ("fixture-a", 4)

    second = VectorStore(store, TinyProvider(model="fixture-b", dimensions=6))
    assert second.profile.model == "fixture-b"
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM vector_items").fetchone()[0] == 0
        active = conn.execute(
            "SELECT model,dimensions FROM embedding_profiles WHERE active=1"
        ).fetchall()
    assert [tuple(row) for row in active] == [("fixture-b", 6)]


def test_real_learned_semantic_paraphrase_benchmark_when_model_cached() -> None:
    """Real learned acceptance; no cloud text egress, local model only.

    The model is part of Phase 2.5 release preparation. If it cannot be acquired, this test
    fails rather than silently converting semantic acceptance into a skip.
    """
    provider = LearnedLocalEmbeddingProvider(
        cache_dir=str(Path.cwd() / "vault" / ".brain" / "cache" / "embeddings")
    )
    provider.prepare()
    metrics = semantic_paraphrase_benchmark(provider, k=3)
    assert metrics.cases == 5
    assert metrics.recall_at_k >= 0.8
    assert metrics.mrr >= 0.65
