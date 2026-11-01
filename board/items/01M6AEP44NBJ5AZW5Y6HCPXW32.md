---
title: A delegate with a blank on_behalf_of acts as itself only where policy lists it for the route
feature: api-sdk-mcp
lane: invincible-agent/lane/01
repo: invincible-agent
status: claimed
priority: now
blocked_on: []
pr: [invincible-agent#187]
ruling_ref: architect 2026-10-31 (blank on_behalf_of from a delegate)
updated: 2026-10-31
---

The ruling is item 01M6A9QDN1RESBJKHWMZEJARRY. Today `_admit_on_behalf_of` returns (caller, None) for any blank on_behalf_of, with no policy check. To build: a policy-rail listing of which services may act as themselves on which routes (no such listing exists yet), a refusal classified in the ratchet where the service is not listed, and an audit line naming the service. It lands on #187 after the 10-31 merge train.
