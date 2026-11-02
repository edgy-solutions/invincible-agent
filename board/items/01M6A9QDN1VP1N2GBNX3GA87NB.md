---
title: Per-panel seed progress for POST /canvas/seed
feature: finance
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-10-31
---

Cortex's New Canvas dialog wants 'k of 6' progress, but /canvas/seed is one synchronous call that reports nothing until the end. Cortex needs per panel: index, total, artifact or refusal envelope. Cortex builds against a PROPOSED fixture meanwhile.
