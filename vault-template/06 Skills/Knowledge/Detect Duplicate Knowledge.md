---
id: SKL-390806e2-cefc-56bd-aab6-4ce92aae78a6
type: skill
title: Detect Duplicate Knowledge
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 0
---

# Detect Duplicate Knowledge

## Purpose
Find semantically overlapping concepts without collapsing distinct meanings or history.

## Trigger
Compiler matching, weekly audit, or explicit duplicate check.

## Inputs
Candidate concept, lexical/semantic retrieval, titles/aliases, source provenance, relationship graph.

## Procedure
Search exact title/aliases; retrieve semantic neighbors; compare definitions, scope, evidence, projects, and temporal applicability; label candidates as duplicate, related, or distinct; propose merges only when meaning equivalence is well supported.

## Verification
A merge proposal explains evidence for equivalence and lists information that would be lost or combined.

## Failure Conditions
Similarity without semantic equivalence, conflicting definitions, missing evidence, or insufficient context.

## Outputs
Duplicate candidates, related links, or staged merge proposals.

## Side Effects
No canonical merge automatically; generated candidate metrics may update.

## Permission Level
Level 0/1 detection; Level 2 merge.

## Example
Two notes using different wording but the same evidence/definition become a merge proposal, while two similarly named but differently scoped ideas stay distinct.
