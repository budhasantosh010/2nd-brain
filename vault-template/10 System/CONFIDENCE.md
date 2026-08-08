# CONFIDENCE — Evidence State, Not Model Vibes

The system must not rely solely on an LLM producing a statement such as `confidence = 97%`. Model self-confidence is not evidence.

## Evidence states

- `verified` — evidence directly supports the claim and required temporal/provenance checks pass.
- `supported` — evidence supports the claim but verification is not exhaustive or authority/temporal limits remain.
- `provisional` — useful derived interpretation awaiting stronger verification; default for automatically generated knowledge.
- `uncertain` — evidence is incomplete, ambiguous, or materially weak.
- `contradicted` — credible stored evidence conflicts with the claim; both sides remain visible.
- `stale` — evidence may once have applied but is old relative to the question or superseded by newer state.

## Numeric scores

Ranking systems may calculate similarity, authority, recency, retrieval fusion, or other numeric scores. Those numbers help order candidates; they must not be exposed as proof or substituted for evidence state.

## State changes

Evidence state changes require provenance. A model may propose a change, but important upgrades to `verified`, conflict resolution, or meaning-changing downgrades must be justified by source evidence and the applicable review policy.
