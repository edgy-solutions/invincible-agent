---
title: MCP door refuses a service token (seal 1)
feature: api-sdk-mcp
lane: invincible-agent/lane/01
repo: invincible-agent
status: blocked
priority: now
blocked_on: [01M6A9QDN1Q15XZS1VP0PJ729F, 01M6AEP44NBJ5AZW5Y6HCPXW32]
pr: [invincible-agent#187]
ruling_ref: architect post-roll list 10-31
updated: 2026-10-31
---

#187: every MCP-tagged route refuses a service caller 403 service_token_refused; a declared delegate passes only where the body has on_behalf_of. saf's /orchestrate audit seal is red under it (S-audit); the blank-on_behalf_of delegate was ruled 10-31 and is built here. Excluded from the 10-31 train until saf reports.
