# Retrieval and Verification Pipeline

## Global storage, scoped retrieval

The vault is one global brain. Retrieval chooses the smallest useful evidence set; it never loads the entire vault into every prompt.

```text
query
  |-- FTS5 lexical/exact
  |-- local semantic vectors
  |-- exact metadata / IDs / hashes / filenames
  |-- project/entity scope
        |
        v
reciprocal-rank fusion
        |
        v
temporal / authority-aware reranking
        |
        v
bounded one-hop relationship expansion
        |
        v
context budget + dedupe
        |
        v
provenance / temporal / conflict verification
```

## Query classes

The service detects exact-looking identifiers/paths/hashes/quoted phrases, current-state, historical, decision, source-lookup, cross-project and conceptual queries. Exact queries strongly favor lexical/metadata channels. Current-state questions boost active project state and newer decisions; historical queries may intentionally retrieve superseded material.

## Local semantic V1

V1 ships an offline hashing-based vectorizer using tokens, bigrams and character trigrams. It is dependency-light, deterministic, private and fully rebuildable. It is useful for shared-concept/near-paraphrase retrieval but is not equivalent to a large pretrained embedding model. The provider boundary allows a stronger local embedding implementation later without changing canonical data.

Semantic-only candidates below the configured safety floor are discarded so every vector index's unavoidable “nearest neighbor” does not become false evidence for an unrelated question.

## Fusion and graph

FTS, semantic and metadata rankings combine with reciprocal-rank fusion. One useful relationship hop is expanded by default; more hops are configurable but intentionally avoided unless needed.

## Verification

Before presenting a stored-memory answer as factual, verification checks:

- referenced source exists;
- raw evidence is still available;
- segment locator exists where applicable;
- supersession/staleness;
- contradiction records/relationships;
- source authority metadata.

V1's grounded answer path is deliberately extractive: it returns supported evidence text rather than permitting a generation model to add unsupported facts. Natural-language synthesis can be layered later only if checked against the same evidence object.

## Grounded refusal

When no sufficient source-backed evidence exists, the exact answer begins:

`I cannot verify this from the current brain.`

The unresolved question is written to the `questions` table and generated `07 Operations/Unanswered Questions.md`, creating the knowledge-gap flywheel for future sources.
