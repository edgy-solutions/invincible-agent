---
title: Send cortex the PRODUCER_REF packet
feature: api-sdk-mcp
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-11-06
---

Re-filed from 01M6A9QDN1VEWA9EZWB70GCHMB. Owed since #99 merged (10-26 handoff). cortex-ui's `.github/workflows/build.yml:241` pins `PRODUCER_REF: aac9900b…`, the invincible-agent commit its BFF OpenAPI check reads. The packet tells cortex what the pin should follow.
