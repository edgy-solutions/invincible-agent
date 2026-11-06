---
title: Rule the MCP server's open questions
feature: api-sdk-mcp
lane: invincible-agent/seat/architect
repo: invincible-agent
status: open
priority: now
blocked_on: []
pr: []
ruling_ref: architect 2026-10-30 ruling 2 (resource server with token exchange, no passthrough) - partial
updated: 2026-11-06
---

Owed to Lane 1 and ca: finance has no BFF route; token passthrough vs the MCP spec; signing; flag vs chart; the /orchestrate audit line; a 14th tool; whether 401/403 are declared via responses= (ingest-v1 routes in the set would move the shapes lock, a minor bump); the stubbed token-exchange step.

Sweep 2026-11-06 (Lane 1): partly ruled. Ruled: token passthrough (ruling 2: a resource server with token exchange, no passthrough), folded into sessions/2026-10-30-packet-to-architect-cc-ca-saf-from-lane-01-mcp-server-over-the-bff-one-page-spec.md section 3. Still open: the finance BFF route, flag vs chart, a 14th tool, 401/403 via responses=, the stubbed token-exchange step. Signing and the /orchestrate audit line: the spec may fold them in; not confirmed by this sweep.
