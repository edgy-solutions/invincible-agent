---
title: Per-panel seed progress for POST /canvas/seed
feature: finance
lane: invincible-agent/lane/fin
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-11-06
---

Cortex's New Canvas dialog wants 'k of 6' progress, but /canvas/seed is one synchronous call that reports nothing until the end. Cortex needs per panel: index, total, artifact or refusal envelope. Cortex builds against a PROPOSED fixture meanwhile.

Reassigned 2026-11-06 from invincible-agent/lane/01 to invincible-agent/lane/fin (architect confirmed Lane 1's reassignment table, 2026-11-06).
