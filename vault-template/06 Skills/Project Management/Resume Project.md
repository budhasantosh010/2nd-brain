---
id: SKL-708a7c35-bf0d-5f5d-9da8-d7302a859164
type: skill
title: Resume Project
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 0
---

# Resume Project

## Purpose
Give a new AI/session the exact current project position without reconstructing it from old chats.

## Trigger
`Resume Project Y` or a current-state question scoped to a project.

## Inputs
Project ID/name, project bundle, latest structured state/decisions, relevant source evidence.

## Procedure
Read `PROJECT.md`, `STATE.md`, `DECISIONS.md`, `OPEN LOOPS.md`, `CONTEXT.md`, `SOURCES.md`, and `HANDOFF.md`; retrieve latest verified supporting evidence; check supersession/conflicts; summarize goal, exact state, completed work, active decisions, blockers, next action, and do-not-do constraints.

## Verification
Current-state assertions are supported by active state/newer evidence and older conflicting snippets are not presented as current.

## Failure Conditions
Project not found, stale/missing state, or evidence conflict prevents reliable current-state determination.

## Outputs
Scoped resume context and any stale-state/knowledge-gap warning.

## Side Effects
Normally read-only; may record retrieval event/gap.

## Permission Level
Level 0/1.

## Example
A resumed coding project starts from the latest handoff/commit state rather than a months-old conversation.
