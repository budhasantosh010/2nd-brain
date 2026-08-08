---
id: SKL-bf50a44c-12ab-5337-8cef-e6bf134191ea
type: skill
title: Verify Sources
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 0
---

# Verify Sources

## Purpose
Check whether stored evidence actually supports a proposed important claim and remains temporally applicable.

## Trigger
Important answer/update, disputed claim, contradiction review, or explicit verification request.

## Inputs
Claim, source IDs/locators, relevant newer evidence, source authority and dates.

## Procedure
Resolve source; inspect cited locator/context; compare claim wording to evidence; identify interpretation/hypothesis boundaries; check dates/validity; search newer contradictions/supersession; assign evidence state and record limitations.

## Verification
The result explicitly answers support, availability, temporal applicability, contradiction, and evidence state.

## Failure Conditions
Missing source/locator, evidence does not support claim, or temporal context cannot be established.

## Outputs
Verification result and possible conflict/staleness/knowledge-gap record.

## Side Effects
May update generated verification metadata; meaning-changing canonical changes follow review policy.

## Permission Level
Level 0/1.

## Example
A claim cited to PDF page 14 is checked against that page and a later project decision before being called current.
