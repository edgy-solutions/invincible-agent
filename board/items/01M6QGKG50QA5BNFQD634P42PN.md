---
title: Master red: test_document_grants_are_in_the_form_the_gate_builds.py writes sys.modules with no restore
feature: cross-cutting
lane: invincible-agent/lane/saf
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect 2026-11-06: U3 splits by file subject
updated: 2026-11-06
---

`tests/test_the_stub_harness_puts_sys_modules_back.py` names `tests/test_document_grants_are_in_the_form_the_gate_builds.py: lines [96]` at 483da280 (measured 2026-11-06, alone). The file came in with a4a00e38 (saf). Use monkeypatch.setitem/delitem, `stub_modules`, a try/finally, or a fixture that restores after its yield. Siblings: 01M6FRZ3K5477A0CNFKW1D9BBM (Lane 1's four), 01M6FRZ1Z5BNQ9GQ85GY72YRPC (saf's `_mcp_surface_derived.py`).
