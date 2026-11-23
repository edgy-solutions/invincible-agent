---
title: Merge the answer-export loader into the export-profile loader
feature: cross-cutting
lane: invincible-agent/lane/saf
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: architect ruling 2026-11-10 (export profile server, item 5 tail)
updated: 2026-11-10
---

The review-export loader (`src/iagent/export_profiles.py`) now takes overlays, `accepts`, `grain`, `dedupe` and `version`. The answer-export loader (policy/exports/answers/) still has its own copy of the overlay rules. Fold it into the one loader so a profile set is composed once (the #148 failure was two loaders, two sets). Not on 0.4.85.
