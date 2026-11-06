---
title: Contract files carry a classification level validated against policy/classification/levels.yaml (ADR-0066 provisional)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: architect via Chris 11-06 (contracts as data; contract files get a `classification` field validated against levels.yaml)
updated: 2026-11-06
---

The brief asks that contract files carry a `classification` field that `validate_policy` checks against `policy/classification/levels.yaml`. The check is the same one #268's rail makes.

Not started, because there is nothing to put the field on. No contract file exists as data on master (`db0d547e`), and ADR-0066, which defines one, is not written. Gov builds the check when the contract file format lands.

Raised with the architect (fork 4 of the 11-06 packet): on a workflow row, `classification:` already means a compartment, not a level. All eight `policy/workflows/*.yaml` rows set it to `null` (`WorkflowDefinition.classification`). If a contract file and a workflow row ever share a key space, the field may need another name.
