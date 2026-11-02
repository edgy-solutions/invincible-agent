---
title: Rule whether a delegate must name a principal where it can
feature: api-sdk-mcp
lane: invincible-agent/seat/architect
repo: invincible-agent
status: done
priority: now
blocked_on: []
pr: []
ruling_ref: architect 2026-10-31 (blank on_behalf_of from a delegate)
updated: 2026-10-31
---

Ruled 10-31. A blank on_behalf_of from a delegate means the service acts as itself, the same reading as the ingest door's "". It is allowed only where policy lists that service for the route, and the audit names the service. Lane 1 builds it on #187 (item 01M6AEP44NBJ5AZW5Y6HCPXW32).
