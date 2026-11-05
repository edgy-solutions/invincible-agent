---
title: The can_read:<level> rail and the levels registry, validator only (ADR-0064 B)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#268]
ruling_ref: architect via Chris 11-05 (ADR-0064 item B); Chris 11-04 (validator only, no reader yet)
updated: 2026-11-05
---

ADR-0064 (Proposed, #266) item B. `policy/classification_levels.yaml` is the ordered registry of levels; list position is the order. `policy/level_readers.yaml` is the `can_read:<level>` rail, one row per level naming groups. `policy/grantors/level_readers.yaml` is its grantor seed. Both files ship empty, and `validate_policy` checks them when present. No code reads either until dag-tools step 5 serves a dataset's level.

Open with the architect (packet from gov, 11-05): whether dag-tools' `classification/levels.yaml` and this registry are one file or two; whether the rail must be monotone across levels; and the Topaz relation name a reader syncs to, since `can_read` is already a live relation.
