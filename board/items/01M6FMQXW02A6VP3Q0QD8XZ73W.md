---
title: A red test still says the sandbox renders three openddil principals; the values list four
feature: openddil
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#222]
ruling_ref: none; found by gov's consumer run for #210, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b. Broken by 6a10a62a (2026-10-21): green at its parent, red at that commit, run in today's venv.

- tests/test_a_delegate_acts_on_behalf_of_a_declared_principal.py::test_I_the_sandbox_renders_openddils_three_principals

That commit added regioneast to the svc:openddil delegate list in the sandbox values, ruled 10-21, and updated tests/test_oidc_broker_chart.py but not this test. It reads as a stale assertion after a deliberate change; the author's read decides.

Fix (lane/01-five-reds): the test expected three principals; regioneast joined the list (ruled 10-21, 6a10a62a). The expected set gains PRINCIPAL_REGIONEAST and the test is renamed to four_principals.
