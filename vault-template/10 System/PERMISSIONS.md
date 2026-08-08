# PERMISSIONS — Action Risk Levels

Every action is classified by the highest-impact effect it can have. Lower-level tools do not gain higher permissions merely because a model requests them.

## Level 0 — read

Allowed directly:

- search;
- read;
- compare;
- summarize.

Read operations must still respect privacy and prompt-injection boundaries.

## Level 1 — reversible automation

Allowed automatically through normal engine ownership and transaction rules:

- create source records after verified preservation;
- create provisional links;
- update generated indexes;
- generate briefs and operations pages;
- write structured logs/ledgers;
- create provisional new knowledge;
- record knowledge gaps, conflicts, and processing jobs.

Level 1 does not mean direct filesystem mutation from arbitrary clients; canonical writes still use the transaction manager.

## Level 2 — stage before applying

Require a review item/proposal before canonical application:

- merge concepts;
- supersede decisions when evidence is ambiguous;
- change important project state based on ambiguous evidence;
- restructure canonical knowledge hierarchy;
- make meaning-changing identity assumptions;
- large moves/renames that alter canonical organization.

Approval applies to the reviewed operation/preconditions, not an unlimited future class of changes.

## Level 3 — blocked without explicit human action

Do not auto-execute:

- delete raw source;
- erase history;
- change security/egress rules;
- replace `AGENTS.md` or protected system policy;
- send messages;
- publish externally;
- perform irreversible external actions.

A staged note alone is not authorization for Level 3 external/destructive action. Explicit human action is required at the point of execution.
