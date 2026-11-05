---
title: Master red: five person-refusal seals since #229 (no_run_id)
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#250]
ruling_ref:
updated: 2026-11-05
---

Red on master at 8a2717e0: `tests/security/test_enumerate_instances_refuses_a_caller_who_is_not_a_person.py` (3) and `tests/security/test_fill_slots_refuses_a_caller_who_is_not_a_person.py` (2). They fail on `CallerIdentityUnavailable: no_run_id` at `dynamic_supervisor.py:1754`.

Witness: the two files give 24 passed, 1 xfailed at b72edf34 and 5 failed, 19 passed, 1 xfailed at 7cbc2a53, the merge of #229 (`lane/01-run-bound-vault`).

Not decided: whether the seals need a run id in their setup, or a caller who is not a person no longer reaches the refusal these seals defend. Gov has not read past the raise.

Read and decided: setup, not a lost refusal. `_caller_token_for` returns `""` when no person is behind the run, and the route-level arms never stopped passing. The five failing tests act for a person, and since #229 a person's leg redeems a token first. #250 adds the usual redeem stub and changes no assertion: 24 passed, 1 xfailed, and mutating either refusal reader still reds its seal.

Done: #250 merged at `823da645`. On `f64d42fb` (master after #256, plus #267) the two files give 24 passed, 1 xfailed, the count from before #229.
