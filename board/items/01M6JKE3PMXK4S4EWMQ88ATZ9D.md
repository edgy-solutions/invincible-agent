---
title: The paused-run sign-in card
feature: cross-cutting
lane: cortex-ui/master
repo: cortex-ui
status: open
priority: now
blocked_on: []
pr: []
ruling_ref: architect 11-03: build the paused-run card; #229 doesn't roll without it or a configured exchange
updated: 2026-11-04
---

Spec `run-reauth-card.md` is in cortex-ui, behind flag `runReauth`, default off. Cortex's gate was that the fields exist at a sha Lane 1 names. Lane 1 named `fc50fc30` (#249, not merged) on 11-04.

Cortex says this isn't small: it touches `AuthProvider`, and the popup needs a browser proof. It's one of the two ways to meet the ruling; the other is `01M6JKEC9B1AHTR74S0Y3BGTPP`. The choice is on `01M6G4CHZGJB4CGFXRMJC9199A`.
