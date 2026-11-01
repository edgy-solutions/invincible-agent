---
title: MCP door refuses a service token (seal 1)
feature: api-sdk-mcp
lane: invincible-agent/lane/01
repo: invincible-agent
status: review
priority: now
blocked_on: []
pr: [invincible-agent#187]
ruling_ref: architect post-roll list 10-31
updated: 2026-10-31
---

#187: every MCP-tagged route refuses a service caller 403 service_token_refused; a declared delegate passes only where the body has on_behalf_of. saf's /orchestrate audit seal is red under it (S-audit); the blank-on_behalf_of delegate is a fork (AR-delegate).
