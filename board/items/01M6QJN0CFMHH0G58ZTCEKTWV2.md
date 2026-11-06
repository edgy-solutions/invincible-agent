---
title: Classification dimensions (levels.yaml -> dimensions.yaml) and the holds:<dimension>:<value> rail, validator only
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#282]
ruling_ref: Chris 11-06 (levels.yaml -> dimensions.yaml; cleared_for stays for the hierarchical dimension; holds rail for set dimensions)
updated: 2026-11-06
---

The ruling, verbatim: "gov: policy/classification/levels.yaml → dimensions.yaml (name, type, vocabulary, owner); `cleared_for:<level>` stays for the hierarchical dimension; `holds:<dimension>:<value>` rail for set dimensions; validator refuses a value outside the vocabulary. Still validator-only. #268's seal updates."

Branch `lane/gov-classification-dimensions`, from master `9bb11c97`. What it builds:

- `policy/classification/dimensions.yaml` (renamed from `levels.yaml`). Each row has `name`, `type` (`hierarchical` or `set`), `vocabulary` and `owner` (a seat). A hierarchical vocabulary is ordered, least restrictive first. It ships empty.
- The `cleared_for:<level>` rail (`policy/level_readers.yaml`, #268) reads the hierarchical dimension's vocabulary. #268's seal is updated.
- The new `holds:<dimension>:<value>` rail is `policy/dimension_holders.yaml`, with family `dimension_holders` and `object_scoped: true`. It has one row per value of each set dimension, and refuses a value outside the vocabulary. A `holds:` capability row is refused.

Gov's readings, to confirm:

- At most one hierarchical dimension, because `cleared_for:<level>` names no dimension.
- `vocabulary` is plain strings. The old per-level `reason` and `ratified_by` give way to the dimension's `owner`, because the ruling lists four fields.
- The rail file's name.
