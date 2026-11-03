---
title: Master red: the no-leaf relaunch tests don't configure can_drop's directory
feature: pcn-pdn
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_a_finished_run_with_no_leaf_waits_for_a_kind.py (2) first went red at 53f84fc8 (#153, tip bdb7ee75a, lane/01). The fixture sets only `INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS`, so the can_drop door answers 503 `authorization_unconfigured` (gateway.py ~1168) and the test sees `[]`.

Configure the directory in the fixture.
