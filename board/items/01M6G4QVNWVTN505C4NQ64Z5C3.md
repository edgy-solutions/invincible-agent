---
title: One vault reference per run, redeemed per call, with awaiting_reauth
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#229]
ruling_ref: the architect's four answers, items 1 and 2
updated: 2026-11-04
---

Draft PR, built on `01M6G4QVG15J6NZF07W2GKGKJW`.

It can't roll until cortex has a sign-in card or the Keycloak exchange is configured. Otherwise a run that meets a near-expiry token sits paused until its budget ends, holding one of the two run slots. Cortex has the wire in its 11-03 packet. The architect has the slot question.

#229 merged at `7cbc2a53`, in 0.4.78. Not rolled. The roll gate lives on `01M6G4CHZGJB4CGFXRMJC9199A`; the card is `01M6JKE3PMXK4S4EWMQ88ATZ9D` and the exchange is `01M6JKEC9B1AHTR74S0Y3BGTPP`.
