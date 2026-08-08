---
id: SKL-7bf334d4-164d-58fe-8daf-2db8fc242d4b
type: skill
title: Create Project
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 1
---

# Create Project

## Purpose
Create a complete project memory bundle from an identified outcome without requiring the user to hand-build project files.

## Trigger
Explicit create-project request or an accepted project candidate from compilation.

## Inputs
Project title, goal/outcome, known constraints/success criteria, initial evidence/source IDs.

## Procedure
Generate stable `PRJ-` ID; copy the project template into `04 Projects/Active Projects/<Project>`; populate `PROJECT.md`; initialize `STATE.md`, decisions/open loops/context/sources/handoff; create structured project row and index entry through transaction manager.

## Verification
All required project files exist, use the same project ID, and handoff/state can be read by another session.

## Failure Conditions
Name/path collision that cannot be resolved safely, invalid metadata, or transaction failure.

## Outputs
Complete project folder and structured project record.

## Side Effects
Canonical project creation and generated index update.

## Permission Level
Level 1 when project creation is explicit/unambiguous; ambiguous inferred projects remain candidates/review as appropriate.

## Example
`Create Project: Global Brain V1` creates PROJECT/STATE/DECISIONS/OPEN LOOPS/CONTEXT/SOURCES/HANDOFF plus Inputs/Working/Outputs/Feedback.
