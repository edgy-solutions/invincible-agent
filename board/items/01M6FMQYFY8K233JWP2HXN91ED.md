---
title: Who may change the deck template is a capability: can_configure:deck_template (#215)
feature: training
lane: invincible-agent/lane/gov
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris:topaz_sync at 0.4.76 or later for training-admins]
pr: [invincible-agent#215]
ruling_ref: architect 11-02 (new capability, group training-admins, sandbox alice, seed row)
updated: 2026-11-03
---

Seed row `can_configure:deck_template`, granted_by seed, to the capability-only group training-admins. Sandbox member alice is a fixture. Deny-by-default: deleting the row leaves the deck template configurable by nobody. A deployment configures its own in its own policy repository. Not checked against a registry at this PR; fork 25 ruled that it gets one, which is 01M6G57JZYCM0EZ3A9WNQCEZ4C.

Order after merge: the chart cut that carries it; Chris runs topaz_sync at that release's sha, in the streamed form; the ia chart roll, whose hook writes the row (topaz_sync alone leaves can_invoke false for everyone, alice included); then the workbench roll. The surface that asks is wb's; the workbench has no configure route yet.

#215 merged and is in 0.4.76 (tag ce589473).
