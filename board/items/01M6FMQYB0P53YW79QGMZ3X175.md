---
title: A red census names four promotion statements; promotion_stores has a fifth
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; found by gov's consumer run for #210, triaged by Chris's 11-02 instruction
updated: 2026-11-02
---

Red on master at e0a2ab9b. Broken by a14e21b5 (2026-10-28): green at its parent, red at that commit, run in today's venv.

- tests/test_the_promotion_stores_keep_the_record_and_move_the_objects.py::test_the_statement_population_is_the_four_known

`_PROMOTED_BETWEEN_SQL` was added to promotion_stores.py, and the census names four statements. It reads as a stale census after a deliberate change, but a census exists to make a new statement be looked at, so someone should read the new one against what the census defends rather than only add a name.
