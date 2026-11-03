---
title: Master red: provenance has no steward-entered rung, and the ruled behaviour is unbuilt
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

tests/test_the_answer_carries_its_provenance_floor.py::test_the_rung_tuple_AGREES_with_the_SDKs_copy. SDK v0.9.11 added `steward-entered`; src/iagent/provenance.py:43-45 lacks it. The red arrived with the pin bump at 5c16695f.

Nothing refuses live today: `steward_correction.provenance_for` (restate_analyst/steward_correction.py:283) stamps `steward-corrected` on an ADDED row. But promotion_stores.py:505 cites the architect's 10-23 ruling that a hand-entered part is `steward-entered`, so that behaviour isn't built. If anything emitted it, promotion_stores.py:518 and provenance.py:159 would refuse it.

Add the rung and stamp added rows as ruled.
