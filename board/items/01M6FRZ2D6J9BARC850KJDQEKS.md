---
title: Master red: the input-declared route doesn't upper-case its scope; one census line is stale
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

Red on master at e0a2ab9b, full suite and alone. First red at bd52c7fd (10-19, tip 46e54949, lane/74).

- `test_the_ROUTES_upper_case_the_scope…`: real against the seal. `_input_declared_pool` is passed `list(domains)` from raw `request.domains` (ontology main.py:3734-3735), without the upper-casing the other routes do (4286, 6678). The seal says normalise, don't widen. Whether a mis-cased scope can reach it wasn't measured; the auth layer sends upper case.
- `test_the_REQUEST_MODELS_BOTH_carry_the_person…`: identity is NOT dropped. main.py:2849 hands on `user_email=request.user_email`. The census equality is stale, so update the census.
