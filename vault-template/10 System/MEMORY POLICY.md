# MEMORY POLICY — Separate Memory by Function

The Global Brain explicitly rejects one giant `memory.md`. Different memory kinds have different authority, update rates, retrieval needs, and privacy implications.

## Identity memory

`09 Identity` contains profile, goals, preferences, communication style, working style, and constraints. Template files begin empty/generic. Runtime identity changes carry provenance/timestamps and ambiguous meaning-changing changes are staged.

## Semantic knowledge

`03 Knowledge` stores reusable concepts, claims, entities, lessons, strategies, tactics, frameworks, anti-patterns, and related maps. It is source-backed, revisable, and not necessarily current project state.

## Episodic history

Sources, operation ledgers, project histories, decisions, handoffs, and historical state retain what happened and when. Episodic history is never silently rewritten into a cleaner fictional past.

## Project state

`04 Projects/.../STATE.md` is the current operational truth for a project. It has stronger ranking for current-state questions but must retain evidence and history. Stable purpose belongs in `PROJECT.md`, not repeatedly rewritten into state.

## Procedural skills

`06 Skills` stores reusable procedures with triggers, verification, failure conditions, outputs, side effects, and permission level. A skill describes how to perform work; it is not evidence that the work occurred.

## Working context

`00 Home/Current Context.md`, `07 Operations/CURRENT.md`, and generated briefs provide short-lived context views. They may be regenerated from canonical state and should not become the sole home of important knowledge.

## Retrieval implication

Query type determines which memory class gets priority. Current-state questions should not be answered from old episodic snippets when newer project state exists. Historical questions should not discard old evidence because current state changed.
