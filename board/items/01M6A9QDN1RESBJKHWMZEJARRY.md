---
title: Rule whether a delegate must name a principal where it can
feature: api-sdk-mcp
lane: invincible-agent/seat/architect
repo: invincible-agent
status: open
priority: now
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-10-31
---

Measured on #187: a declared delegate posting a blank on_behalf_of on a route that takes one (/ingest, /human_tasks/{id}/act) acts as itself; _admit_on_behalf_of returns (caller, None). The door admits it by design; whether the handler must then refuse is the fork.
