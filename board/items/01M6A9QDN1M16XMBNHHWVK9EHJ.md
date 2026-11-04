---
title: Refusal: PartialRefusal adoption (fork 2)
feature: api-sdk-mcp
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: later
blocked_on: []
pr: [invincible-agent#247]
ruling_ref: architect 10-31 fork 2 (b), (c) until tag
updated: 2026-11-04
---

#247 builds it: the BFF's refusal goes through the SDK's `PartialRefusal`. The pin to v0.9.13 is in the same PR, because no other bump exists. Ready, not merged. In-process only; nothing has rolled.

Merging is lane/01's. Whether to merge before the SDK's patch is Chris's and lane/01's call: `meshSdkSource: index` cannot serve this pin (01M6JJVP0KKT9HAM99YX2TEDBZ), and the default `url` source is not affected.

`GRANTED_BY_SEED` is not in it; that is 01M6A9QDN199K1WE2H3QN3ZVQ9, once this merges.
