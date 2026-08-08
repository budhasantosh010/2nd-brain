"""Export selected Pydantic domain models as JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

from second_brain.models import (
    BrainAnswer,
    CanonicalFrontmatter,
    ConceptRecord,
    DecisionRecord,
    KnowledgeExtraction,
    OperationPlan,
    ParsedDocument,
    ReviewItemModel,
    SourceRecord,
)

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "schemas"
MODELS = {
    "canonical-frontmatter": CanonicalFrontmatter,
    "source": SourceRecord,
    "parsed-document": ParsedDocument,
    "concept": ConceptRecord,
    "decision": DecisionRecord,
    "knowledge-extraction": KnowledgeExtraction,
    "brain-answer": BrainAnswer,
    "review-item": ReviewItemModel,
    "operation-plan": OperationPlan,
}


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, model in MODELS.items():
        path = TARGET / f"{name}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(f"Exported {len(MODELS)} schemas to {TARGET}")


if __name__ == "__main__":
    main()
