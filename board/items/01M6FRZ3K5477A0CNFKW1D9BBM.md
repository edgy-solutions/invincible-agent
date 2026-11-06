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
updated: 2026-11-06
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_the_stub_harness_puts_sys_modules_back.py names `test_bff_openapi_is_current.py:24` (95db114b), `test_ingest_v1_is_stable.py:35` (1fb9e242), `test_the_board_renders…:20` (83850d98) and `test_the_mcp_surface_is_stable.py:25` (5924135f).

The fifth file is on saf's item, so the test stays red until both are done.

Re-measured at fd45d864: the test names six files. These four are this item; `_mcp_surface_derived.py` is saf's and the malformed-PDP seal is gov's new item.

Split by file subject (architect, 2026-11-06). All four files here are the door's or the board's, so this item stays with Lane 1: `test_bff_openapi_is_current.py` and `test_ingest_v1_is_stable.py` (published BFF contracts), `test_the_mcp_surface_is_stable.py` (the BFF's mcp tag surface) and `test_the_board_renders_from_items_deterministically.py` (the board).

Re-measured 2026-11-06 at 483da280: the stub-harness test names six files. These four; `tests/mcp_seals/_mcp_surface_derived.py:62` on saf's 01M6FRZ1Z5BNQ9GQ85GY72YRPC; and `tests/test_document_grants_are_in_the_form_the_gate_builds.py:96` (a4a00e38, saf), new, on 01M6QGKG50QA5BNFQD634P42PN. Gov's malformed-PDP seal (01M6FZV0KNF7A3GT4QEJ44CEMB) is done and no longer named.
