---
id: SKL-aba25696-fa2b-53e5-b9a7-835b5acb05ea
type: skill
title: Close Project
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 1
---

# Close Project

## Purpose
Mark an outcome complete/closed while preserving final state, decisions, sources, outputs, and resume history.

## Trigger
User confirms project completion/closure or completion is unambiguously evidenced under configured policy.

## Inputs
Project bundle, success criteria, final evidence, open loops, outputs.

## Procedure
Verify closure criteria; resolve or explicitly retain remaining open loops; create final handoff/state; mark project status closed; move/archive using a transaction so history and links survive; update project index/briefs. Never delete project history.

## Verification
Closed project remains retrievable with final outcome, evidence, decisions, and unresolved items clearly marked.

## Failure Conditions
Success criteria unresolved, ambiguous closure, or risky archive move fails preconditions.

## Outputs
Closed project record and archived/canonical project bundle.

## Side Effects
Project status/move may be canonical; ambiguous closure/restructure is staged.

## Permission Level
Level 1 for explicit closure; Level 2 when closure/archival meaning is ambiguous.

## Example
A delivered project is marked closed, final results recorded, and folder moved to `99 Archive/Projects` without deleting source relationships.
