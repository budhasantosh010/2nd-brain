---
id: SKL-21d4f234-b6eb-5d2b-806d-d8e23392717a
type: skill
title: Update Knowledge
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 1
---

# Update Knowledge

## Purpose
Incorporate new evidence into existing compiled knowledge without erasing provenance, contradiction, or history.

## Trigger
Compiler classifies a candidate as UPDATE, CONFLICT, or SUPERSEDES.

## Inputs
Existing note/record, new source-backed extraction, evidence state, change/review policy.

## Procedure
Read current canonical content and hash; compare new evidence; append/adjust current understanding and evidence links; preserve change history; use supersession for decisions; stage meaning-changing merges or ambiguous reinterpretation; apply accepted low-risk update atomically.

## Verification
Updated content still references prior and new provenance, and history remains reconstructable.

## Failure Conditions
Precondition hash changed, provenance missing, contradictory evidence unresolved, or proposed edit exceeds permission level.

## Outputs
Updated canonical knowledge or a review proposal.

## Side Effects
Atomic canonical write plus structured DB/index refresh.

## Permission Level
Level 1 for additive/provisional updates; Level 2 for meaning changes.

## Example
A concept gains a new supporting source and updated applicability note while its original source remains cited.
