---
title: Master red: two socratic sites name a kind with no audit disposition
feature: workflow-socratic
lane: invincible-agent/lane/74
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_kind_hardcode_audit.py::test_every_DERIVED_site_has_a_disposition names `next:chaining` in socratic_elicitation (40576353) and in scripts/socratic_measure (630a6359).

The test has six sites across lanes 01, 74 and gov, each on its own item, so it stays red until all three are done.
