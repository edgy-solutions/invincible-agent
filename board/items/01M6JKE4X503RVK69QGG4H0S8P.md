---
title: Serve the pause record: paused_call, instruction, GET /me/paused-runs
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: review
priority: now
blocked_on: []
pr: [invincible-agent#249]
ruling_ref: names agreed with cortex 11-03; architect 11-03 on the card
updated: 2026-11-04
---

Adds the two fields to the vault's pause, the `run_awaiting_reauth` event and a new read. Not in 0.4.78; it needs a later chart. Doubles only, no live pause.

`paused_call` is built from the supervisor's leg label, so some read as internal words. A friendlier name would be a row per leg. Not built.
