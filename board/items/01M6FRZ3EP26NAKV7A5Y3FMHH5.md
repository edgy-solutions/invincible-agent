---
title: Master red: the 409 seal reads a 200's content argument as a status
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone. This is a seal false positive.

tests/test_every_409_carries_a_message.py names gateway.py:13948 (a14e21b5): `JSONResponse(export_profiles.to_json(...), headers=disp)` is a 200, and the seal's `_status` reads `args[0]` as a status. Pass `content=` or fix the seal.

Lines 2919 and 3619 of the same test are on fin's item, so it stays red until both are done.
