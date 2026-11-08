---
title: Batch export control and card-declaration schema need capabilities/consumer
feature: api-sdk-mcp
lane: cortex-ui/master
repo: cortex-ui
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: cortex 2026-11-08 report: canExportBatch reads capabilities (cortex-ui 96adc3f); card-declaration half open
updated: 2026-11-08
---

Neither field is served at 0.4.73 (Entitlements has no capabilities; FrontendCapability has no consumer). Cortex's card-declaration schema already carries both; only producer citations were updated.

Sweep 2026-11-08, partial. The capabilities half is built: cortex-ui `96adc3f` reads `capabilities` for `canExportBatch`, against invincible-agent `c3b51ed7` (#290). Its blocker 01M6A9QDN15JXEWSZYYQ6VV6TG merged as #290, so the item is unblocked.

Cortex asked for review in its 11-08 report. The sweep sets it to open instead, because `96adc3f` was pushed to master with no PR and the board's rule says review needs one. Still open: the card-declaration half (`FrontendCapability.consumer`).
