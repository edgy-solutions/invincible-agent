---
title: Config-rule: producer wire still names the case (four cortex-hit sites)
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect 10-30 standing rule: code names the mechanism, config names the case
updated: 2026-11-01
---

Cortex opened its own hard-codes (leaf, granularity, droppable_kinds, no-declaration means no actions) but four sit on the BFF producer wire. The drop picker also still needs drop_leaves [{leaf,label}] served (SDK v0.9.11 tagged 10-29).

Sweep 11-01: cortex-ui#59 (merged) was cortex's half. The four BFF producer-wire sites are Lane 1's and have no PR yet, so the item stays open.
