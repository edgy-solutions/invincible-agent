---
title: Master red: _mcp_surface_derived.py writes sys.modules with no restore
feature: cross-cutting
lane: invincible-agent/lane/saf
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_the_stub_harness_puts_sys_modules_back.py names `_mcp_surface_derived.py:62` (2a8adb9b, saf) among five files. Restore what it writes.

The other four are on Lane 1's item, so the test stays red until both are done.
