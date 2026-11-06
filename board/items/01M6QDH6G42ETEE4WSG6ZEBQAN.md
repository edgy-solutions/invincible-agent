---
title: Contract files carry level per column and max_level per dataset, validated against policy/classification/levels.yaml (ADR-0066 provisional)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: architect via Chris 11-06 (contracts as data), and #276 fork 4 (`level:` per column, `max_level` on the dataset)
updated: 2026-11-06
---

The ruling on fork 4, verbatim: "Contracts use `level:` (per column, plus `max_level` on the dataset), the levels.yaml vocabulary; `classification` stays the compartment word on workflow rows."

So a contract file names a `level:` on each column and a `max_level` on the dataset. `validate_policy` checks both against `policy/classification/levels.yaml`, the same check #268's rail makes. Since levels are ordered, it will presumably also refuse a column whose level is more restrictive than the dataset's `max_level`. That check is gov's reading and should be confirmed when the work starts.

Not started, because there is nothing to put the fields on. No contract file exists as data on master (`9bb11c97`), and ADR-0066, which would define one, is not written. Gov builds the check when the contract file format lands.

On workflow rows, `classification:` keeps its meaning: a compartment. All `policy/workflows/*.yaml` rows set it to `null` (`WorkflowDefinition.classification`).
