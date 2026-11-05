---
title: Master red: the RS256 seal looks in get_current_user, and the pin moved to a helper
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#233]
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-04
---

Red on master at e0a2ab9b, full suite and alone. This is a stale seal, not a hole.

tests/security/test_gateway_jwt_verification.py::test_algorithm_is_pinned_to_rs256 first went red at d7a2ab7e (#179, tip 836975328, gov). RS256 is still pinned, at src/iagent/auth.py:205-208, in a helper above `get_current_user`.

Point the seal at the helper, and mutate the pin to prove it still fires.

#233 reads every `jwt.decode` in `iagent.auth` by form and checks that `get_current_user` goes through the helper. Five mutants of the pin killed.

Merged in #233. `test_gateway_jwt_verification.py` is green at master 8a2717e0.
