# RETRIEVAL — Scoped Hybrid Evidence Retrieval

## Principle

The brain is globally searchable but answers use the smallest sufficient context. Never load the entire vault into a prompt merely because storage is global.

## Query classification

Classify the request before ranking evidence:

- `EXACT` — hashes, branch names, task/issue IDs, exact phrases, quoted strings, paths, filenames, project codes, precise dates.
- `CURRENT STATE` — what is happening now, next action, blockers, current decision.
- `HISTORICAL` — old position, prior state, what changed, previous decision.
- `CONCEPTUAL` — ideas, patterns, explanations, related knowledge.
- `CROSS-PROJECT` — relationships across multiple projects/areas.
- `DECISION` — why a decision exists, alternatives, supersession.
- `SOURCE LOOKUP` — locate or inspect a known source.

Exact-looking identifiers strongly favor lexical retrieval. Current-state questions strongly favor `STATE.md`, active decisions, latest handoffs, and newer verified evidence over old conversation snippets.

## Search stages

Run eligible retrieval channels independently:

1. FTS5 lexical/exact search;
2. metadata filters for type, project, entity, date, status, authority, source ID;
3. local semantic vector search for paraphrase/concept similarity;
4. project/entity scope inferred from query and current context.

Fuse ranked lists deterministically, using reciprocal-rank fusion by default. Then apply temporal/authority weighting appropriate to query type, expand at most one useful relationship hop by default, rerank, and build the final context budget.

## Relationship expansion

One useful hop is the default. Expand only relations likely to add evidence: supports, contradicts, supersedes, derived-from, part-of, applies-to, depends-on, result-of, and relevant mentions. Additional hops require a demonstrated retrieval need; graph density itself is not value.

## Temporal ranking

- Current-state queries prefer active/newer operational state and non-superseded decisions.
- Historical queries preserve older records and may downweight current-state dominance.
- Claims with `valid_to`, stale state, contradiction, or supersession must carry those conditions into the answer.
- Source authority is a ranking signal, never permission to erase disagreement.

## Context budget

Select the smallest set of evidence that covers the answer, contradictions, and temporal context. Avoid duplicate segments and low-value near-identical results. Preserve source IDs and locators for each included segment.

## Verification and response evidence

Retrieval is not the final truth step. Before answering, verification checks that sources exist, locators exist where available, excerpts support the claim, dates still apply, contradictory/newer evidence is surfaced, and superseded decisions are not presented as current.

The answer object supports: `answer`, `evidence`, `citations`, `conflicts`, `uncertainty`, and `missing_information`. When evidence is insufficient, produce the grounded refusal defined in `VERIFICATION.md` and record the unresolved question.
