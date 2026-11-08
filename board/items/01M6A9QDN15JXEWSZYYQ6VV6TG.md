---
title: Serve capabilities on /me/entitlements for cortex
feature: api-sdk-mcp
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#290]
ruling_ref: 
updated: 2026-11-06
---

cortex's batch-export control and card-declaration schema wait on capabilities on /me/entitlements and a consumer on FrontendCapability.

Reassigned 2026-11-06 from invincible-agent/lane/01 to invincible-agent/lane/gov (architect confirmed Lane 1's reassignment table, 2026-11-06).

Architect, 2026-11-06: /me/entitlements serves what the capability registry holds; cortex consumes; no new registry.

Chris, 2026-11-06, verbatim: "G6 (/me/entitlements capabilities + authz_id field, with Lane 1), then G5 (RefusalEnvelope on MCP routes)."

Claimed by gov 2026-11-06. What gov builds: `capabilities` on /me/entitlements is every `capability:<key>` object the Topaz directory serves on which the caller holds `can_invoke`, sorted. It never reads policy/capability_grants.yaml directly. An unreadable directory or a failed check is 503, never a partial list. It is an ingest-v1 minor bump. `authz_id` has been served since 2026-10-21, and Lane 1's #286 is its readiness consumer.
