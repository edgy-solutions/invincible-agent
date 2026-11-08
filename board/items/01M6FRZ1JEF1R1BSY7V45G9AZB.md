---
title: Master red: finance_agent registers through kwargs, which the seal cannot check
feature: finance
lane: invincible-agent/lane/fin
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#238]
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_registration_calls_bind_to_the_helper.py calls `register_engine_to_mesh(**kwargs)` at agent_fleet/finance_agent/main.py:598 UNCHECKABLE. Line blame says ab71e070 (08-29), but that isn't a witness for the kwargs form, so confirm with `git log -L`.

Pass the arguments by name so the seal can bind them.
