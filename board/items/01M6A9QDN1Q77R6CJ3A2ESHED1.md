---
title: SDK EvidenceRef schema: no null note, bbox exactly 4 numbers 0..1
feature: api-sdk-mcp
lane: iagent-mesh-sdk/lane/ca-0.9.13
repo: iagent-mesh-sdk
status: open
priority: now
blocked_on: []
pr: []
ruling_ref: architect 10-31 fork 1
updated: 2026-10-31
---

Lane 01 asks ca for v0.9.13: note optional but null-free in the schema, bbox published as 4 numbers in 0..1. Until then ingest_api keeps its served model with an equivalence seal; lane 01 swaps to the import in 0.4.74 or 0.4.75.
