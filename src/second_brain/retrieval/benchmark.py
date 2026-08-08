"""Deterministic retrieval benchmark helpers used by Phase 2.5 acceptance."""

from __future__ import annotations

from dataclasses import dataclass

from second_brain.embeddings.base import EmbeddingProvider
from second_brain.embeddings.local import cosine


@dataclass(frozen=True, slots=True)
class SemanticCase:
    case_id: str
    source: str
    query: str


SEMANTIC_PARAPHRASE_CASES = (
    SemanticCase(
        "attrition",
        "Employee attrition increased sharply during the last quarter.",
        "More staff are leaving the company.",
    ),
    SemanticCase(
        "cac",
        "Customer acquisition cost is rising across paid channels.",
        "We spend more money to get each new buyer.",
    ),
    SemanticCase(
        "deployment",
        "The deployment was postponed until the reliability work is complete.",
        "The release got pushed back.",
    ),
    SemanticCase(
        "shutdown",
        "The founder decided to discontinue the product after repeated losses.",
        "Why did we shut the product down?",
    ),
    SemanticCase(
        "hiring-freeze",
        "Leadership paused recruitment for the remainder of the quarter.",
        "Why did the company stop adding new employees?",
    ),
)

ADVERSARIAL_NEGATIVES = (
    "The cafeteria changed its lunch menu and coffee supplier.",
    "A new office lease was signed near the train station.",
    "The design team changed the homepage accent color.",
    "Quarterly tax forms were submitted before the deadline.",
    "The customer support team bought new headsets.",
)


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    recall_at_k: float
    mrr: float
    cases: int


def semantic_paraphrase_benchmark(
    provider: EmbeddingProvider,
    *,
    k: int = 3,
) -> BenchmarkMetrics:
    """Measure learned paraphrase retrieval with lexically-different adversarial negatives."""

    documents = [case.source for case in SEMANTIC_PARAPHRASE_CASES] + list(ADVERSARIAL_NEGATIVES)
    vectors = provider.embed_batch(documents)
    query_vectors = provider.embed_batch([case.query for case in SEMANTIC_PARAPHRASE_CASES])
    hits = 0
    reciprocal_rank = 0.0
    for expected_index, query_vector in enumerate(query_vectors):
        ranking = sorted(
            range(len(documents)),
            key=lambda index: (-cosine(query_vector, vectors[index]), index),
        )
        rank = ranking.index(expected_index) + 1
        if rank <= k:
            hits += 1
        reciprocal_rank += 1.0 / rank
    count = len(SEMANTIC_PARAPHRASE_CASES)
    return BenchmarkMetrics(
        recall_at_k=hits / count,
        mrr=reciprocal_rank / count,
        cases=count,
    )
