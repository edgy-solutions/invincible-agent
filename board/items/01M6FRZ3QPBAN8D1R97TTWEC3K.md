---
title: Master red: three Lane 1 sites name a kind with no audit disposition
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

Red on master at e0a2ab9b, full suite and alone.

tests/test_kind_hardcode_audit.py::test_every_DERIVED_site_has_a_disposition names `extraction_defect` in steward_correction (daea261a), and `document_empty_confirm` (d5061ffb) and `extraction_defect` (fd69eb9a) in the gateway.

The test has six sites across lanes 01, 74 and gov, each on its own item, so it stays red until all three are done.
