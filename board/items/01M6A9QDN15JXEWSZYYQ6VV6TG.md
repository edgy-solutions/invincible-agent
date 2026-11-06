---
title: Serve capabilities on /me/entitlements for cortex
feature: api-sdk-mcp
lane: invincible-agent/lane/gov
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-11-06
---

cortex's batch-export control and card-declaration schema wait on capabilities on /me/entitlements and a consumer on FrontendCapability.

Reassigned 2026-11-06 from invincible-agent/lane/01 to invincible-agent/lane/gov (architect confirmed Lane 1's reassignment table, 2026-11-06).

Architect, 2026-11-06: /me/entitlements serves what the capability registry holds; cortex consumes; no new registry.
