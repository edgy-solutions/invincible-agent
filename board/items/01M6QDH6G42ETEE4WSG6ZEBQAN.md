---
title: Contract files carry level per column and max_level per dataset, validated against the hierarchical classification dimension (ADR-0066 provisional)
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

Chris's later ruling (11-06) renames `levels.yaml` to `policy/classification/dimensions.yaml`. "The levels.yaml vocabulary" is therefore the hierarchical dimension's vocabulary in that file, which is gov's branch `lane/gov-classification-dimensions`.

So a contract file names a `level:` on each column and a `max_level` on the dataset. `validate_policy` checks both against that vocabulary. Since the values are ordered, it will presumably also refuse a column more restrictive than the dataset's `max_level`. That check is gov's reading and should be confirmed when the work starts.

A contract file now exists as data. It is `contracts/ev_fixture.yaml` (fin, #275, merged), modelled by the SDK's `AssetContract`. The SDK has to move first:
- `AssetContractColumn` and `AssetContractDataset` forbid unknown fields.
- Neither has a `level` or `max_level` field. That was measured in the sibling SDK repo at v0.9.14-1, and master pins v0.9.13.

So `level:` in a contract would be refused until the SDK adds both fields. After that, gov's check runs on `contracts/*.yaml`.

On workflow rows, `classification:` keeps its meaning: a compartment. All `policy/workflows/*.yaml` rows set it to `null` (`WorkflowDefinition.classification`).
