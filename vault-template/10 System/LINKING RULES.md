# LINKING RULES — Meaningful Typed Relationships

Links exist to improve retrieval, provenance, explanation, or operational continuity. Do not create links simply to make a graph dense.

## Supported link types

- `supports` — evidence strengthens a claim/knowledge item.
- `contradicts` — evidence conflicts with another claim/state.
- `supersedes` — a newer decision/state replaces an older one while preserving history.
- `derived-from` — knowledge/summary was created from evidence or prior knowledge.
- `related-to` — meaningful non-specific conceptual relationship; use sparingly.
- `part-of` — containment or component relationship.
- `applies-to` — knowledge/skill/framework is relevant to a project/entity/context.
- `created-by` — artifact/entity authorship or generation relationship.
- `mentions` — a source materially mentions an entity/topic.
- `depends-on` — project/decision/task relies on another object/condition.
- `result-of` — outcome follows from a decision/action/process.

## Creation rules

Every link should have identifiable endpoints, type, and provenance where the relation was source-derived. AI-proposed links default to provisional unless deterministically known or verified.

Prefer a small number of high-value typed links over many vague links. Relationship traversal defaults to one useful hop. Cycles are allowed when they represent reality but should not be manufactured.

## Contradiction and supersession

Never collapse contradiction into a generic related link. Preserve both sides and link them explicitly. Supersession does not delete old knowledge; it marks what is current while retaining history.

## Broken links

Weekly maintenance detects relationships whose endpoints no longer exist. Generated maps may omit broken links, but canonical relationship records should be repaired through normal policy rather than silently discarded.
