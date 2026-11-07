---
title: Classification dimensions (levels.yaml -> dimensions.yaml) and the holds:<dimension>:<value> rail, validator only
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#282, invincible-agent#288]
ruling_ref: Chris 11-06 (levels.yaml -> dimensions.yaml; cleared_for stays for the hierarchical dimension; holds rail for set dimensions), and the architect on #282's readings
updated: 2026-11-06
---

The ruling, verbatim: "gov: policy/classification/levels.yaml → dimensions.yaml (name, type, vocabulary, owner); `cleared_for:<level>` stays for the hierarchical dimension; `holds:<dimension>:<value>` rail for set dimensions; validator refuses a value outside the vocabulary. Still validator-only. #268's seal updates."

Branch `lane/gov-classification-dimensions`, from master `9bb11c97`. What it builds:

- `policy/classification/dimensions.yaml` (renamed from `levels.yaml`). Each row has `name`, `type` (`hierarchical` or `set`), `vocabulary`, `owner` and `ratified_by` (each a seat). A hierarchical vocabulary is ordered, least restrictive first. It ships empty.
- The `cleared_for:<level>` rail (`policy/level_readers.yaml`, #268) reads the hierarchical dimension's vocabulary. #268's seal is updated.
- The new `holds:<dimension>:<value>` rail is `policy/dimension_holders.yaml`, with family `dimension_holders` and `object_scoped: true`. It has one row per value of each set dimension, and refuses a value outside the vocabulary. A `holds:` capability row is refused.

The architect's ruling on gov's three readings (via Chris, 11-06), verbatim: "(1) one hierarchical dimension at most — yes, as ADR-0055 has it (one classification, many categories). (2) No: rows keep `ratified_by: owner` (house rule for every shipped row); `owner` on a dimension is who decides what its values mean — both fields, different questions. (3) File name fine."

Applied on #282:
- At most one hierarchical dimension is confirmed. The validator refuses a second.
- A dimension row has both `owner` and `ratified_by`, each a seat and never an identity.
- The rail stays `policy/dimension_holders.yaml`.
