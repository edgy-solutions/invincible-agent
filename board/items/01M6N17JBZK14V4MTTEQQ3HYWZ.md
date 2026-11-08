---
title: The cleared_for:<level> rail and the levels registry, validator only (ADR-0064 B)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#268]
ruling_ref: architect via Chris 11-05 (ADR-0064 item B; forks ruled a/b/c); Chris 11-04 (validator only, no reader yet)
updated: 2026-11-05
---

ADR-0064 (Proposed, #266) item B. `policy/classification/levels.yaml` is the one ordered registry of levels; list position is the order. `policy/level_readers.yaml` is the `cleared_for:<level>` rail, one row per level naming groups. `policy/grantors/level_readers.yaml` is its grantor seed. Both files ship empty, and `validate_policy` checks them when present. No code reads either until dag-tools step 5 serves a dataset's level.

The three forks are ruled (architect via Chris, 11-05): (a) one levels file, owned by policy, which dag-tools reads from the deployment's ConfigMap; (b) a grant at a level is a ceiling, so the validator refuses a group listed at more than one level; (c) the relation is `cleared_for:<level>`, and `can_read` stays what it is. #268 builds all three (`9c4d768e`). The ConfigMap is 01M6P8PTFES1FTRD1JAKSSVFFC.

Merged as #268 (`d77050cd`), with the three rulings built: the registry is `policy/classification/levels.yaml`, a grant is a ceiling (a group is listed once, at its highest level), and the relation is `cleared_for:<level>`. Both files ship empty, and nothing reads them until step 5. The chart ConfigMap that serves the registry to dag-tools is 01M6P8PTFES1FTRD1JAKSSVFFC.
