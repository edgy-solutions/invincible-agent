---
title: Where the person goes when requested_by comes from the token
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris:the architect's ruling on the register field]
pr: []
ruling_ref: register defect part (b) collides with the 2026-10-05 acceptance-row rule and R-117
updated: 2026-11-04
---

`FIX_B` collides with `tests/safety/test_the_acceptance_row_names_its_requester.py`, `tests/test_expired_token_seal.py:483` and `tests/test_dispatch_driver.py:283`. The runners hold a service token and name a person, so taking the field from the token fails or renames every real register.

The options are in `sessions/2026-11-04-packet-to-architect-from-lane-01-requested-by-from-the-token-would-erase-the-person-on-real-registers.md`. One is built and kept on `lane/01-register-field-held` (`ebe71b71`), with no PR and no mutation pass.
