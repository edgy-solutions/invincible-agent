---
title: Declare the 401/403 RefusalEnvelope on every MCP-tagged route
feature: api-sdk-mcp
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#298]
ruling_ref: architect 2026-11-06 G5 (401 and 403 via responses=); Chris 2026-11-06 (refusal optional, envelope-less 403s listed exactly)
updated: 2026-11-07
---

saf's seal 4 found the MCP routes' 401/403 undocumented. Lane 1 declares them once the architect rules whether responses= is the form (it would move the ingest-v1 shapes lock).

Reassigned 2026-11-06 from invincible-agent/lane/01 to invincible-agent/lane/gov (architect confirmed Lane 1's reassignment table, 2026-11-06).
