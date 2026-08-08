# VERIFICATION — Evidence Before Important Claims

Verification is a separate step after retrieval and before an important answer or canonical knowledge update.

## Required questions

For each important claim ask:

1. Does the cited source actually support the statement?
2. Is a date/validity period available and relevant?
3. Is the information still applicable to the user's question?
4. Is there newer contradictory or superseding information?
5. Is this a fact, interpretation, hypothesis, or operational decision?
6. Is the cited source still available and does its locator resolve where possible?
7. Does source authority materially affect how strongly the claim should be stated?

## Verification states

Use `verified`, `supported`, `provisional`, `uncertain`, `contradicted`, or `stale`. Verification does not delete contradictions. It makes disagreement visible.

## Grounded refusal

When the current brain cannot support an answer, return:

> I cannot verify this from the current brain.

Then report what was searched, what relevant material was found, and the evidence that is missing. Record the unresolved query in `07 Operations/Unanswered Questions.md` and structured storage so future source ingestion can resolve the gap.

## Current versus historical truth

A superseded decision is evidence that the old position existed, not evidence that it remains current. Current-state questions must distinguish active from superseded state; historical questions may intentionally retrieve the old position and explain what replaced it.

## Citations

Evidence references should retain source ID plus the most specific available locator (page, slide, range, line span, heading, paragraph, timestamp, etc.). A citation to a source that cannot be found must be surfaced as a verification problem.
<!-- PHASE25_FINAL -->
## Phase 2.5 hardening

Ask from verified bounded evidence. Current questions must not present superseded/stale evidence as current. Invalid synthesis falls back to extractive evidence or grounded refusal.
