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
updated: 2026-11-05
---

Adds the two fields to the vault's pause, the `run_awaiting_reauth` event and a new read. Not in 0.4.78; shipped in 0.4.79 (released 11-04 21:35Z, not rolled).

`paused_call` is built from the supervisor's leg label, so some read as internal words. A friendlier name would be a row per leg. Not built.

Live, 11-05 on 0.4.78: the pause itself reproduces. Run `f27e058a…` emitted `run_awaiting_reauth` with `run_id` and `reason` only, and was terminated. `/me/paused-runs` answers 404 there, as it should. Open: read `paused_call`, `instruction` and `/me/paused-runs` live after the next roll.
