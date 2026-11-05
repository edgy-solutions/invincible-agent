---
title: Master red: the pick seal finds the wrong slot_resolution emission
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

Red on master at e0a2ab9b, full suite and alone. This is a stale seal, not a defect.

tests/routing/test_a_pick_gets_a_row.py::test_the_merge_happens_where_the_artifact_can_still_see_it first went red at fd411b63 (#152, tip 64342c850, lane/01). `_SUP.index('"slot_resolution": MetadataValue.text(')` now finds the no-verb exit's `{}` emission at dynamic_supervisor.py:2671, before the merge at 3049. The real emission, at 3245, is after the merge.

Anchor the seal on the real emission.
