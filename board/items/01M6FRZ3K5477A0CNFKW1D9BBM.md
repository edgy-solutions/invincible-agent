---
title: Master red: four Lane 1 test files write sys.modules with no restore
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

tests/test_the_stub_harness_puts_sys_modules_back.py names `test_bff_openapi_is_current.py:24` (95db114b), `test_ingest_v1_is_stable.py:35` (1fb9e242), `test_the_board_renders…:20` (83850d98) and `test_the_mcp_surface_is_stable.py:25` (5924135f).

The fifth file is on saf's item, so the test stays red until both are done.
