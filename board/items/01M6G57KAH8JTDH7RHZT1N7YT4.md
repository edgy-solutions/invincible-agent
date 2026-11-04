---
title: Red in tests/security on an area run: two files leave a directory on sys.path (#233)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#233]
ruling_ref: none; found by gov's area run at ac1ebe69
updated: 2026-11-03
---

`test_both_callers_go_through_the_one_helper` was red because #210's seal put `agent_fleet/` on `sys.path`: gov's own defect. The two `test_q8_flips_on_one_precondition` reds came from `test_effect_write_gate.py` putting `ontology_service/` there. Both reproduce with the two files alone. Neither is on lane/01's full-suite census at ac1ebe69; that they show only on an area run is inference, not measured. #233 removes both path entries. `test_effect_write_gate.py` is not gov's by history, and #233 says so.
