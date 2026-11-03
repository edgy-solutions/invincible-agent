---
title: A run with no person is a declared pipeline principal: ruled, not built
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: the architect's four answers, item 3; the September ruling
updated: 2026-11-03
---

A run with no person is `pipeline:<name>` with its own entitlements on the rail, never `svc:supervisor` acting as a user and never anonymous. No `pipeline:` prefix exists on master. #213 keeps `svc:supervisor` as interim, and the run-bound vault PR does not build this.

saf's seal holds it as a strict xfail (4 cases) in `tests/identity/test_a_run_with_no_person_is_a_declared_pipeline_principal.py`.
