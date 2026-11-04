---
title: Master red: five person-refusal seals since #229 (no_run_id)
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref:
updated: 2026-11-04
---

Red on master at 8a2717e0: `tests/security/test_enumerate_instances_refuses_a_caller_who_is_not_a_person.py` (3) and `tests/security/test_fill_slots_refuses_a_caller_who_is_not_a_person.py` (2). They fail on `CallerIdentityUnavailable: no_run_id` at `dynamic_supervisor.py:1754`.

Witness: the two files give 24 passed, 1 xfailed at b72edf34 and 5 failed, 19 passed, 1 xfailed at 7cbc2a53, the merge of #229 (`lane/01-run-bound-vault`).

Not decided: whether the seals need a run id in their setup, or a caller who is not a person no longer reaches the refusal these seals defend. Gov has not read past the raise.
