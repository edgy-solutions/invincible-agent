---
title: Neo4j Concept-merge migration: sandbox dry run as pod Job
feature: training
lane: doc-tools/lane/7f
repo: doc-tools
status: open
priority: next
blocked_on: []
pr: [doc-tools#167]
ruling_ref: architect 10-25
updated: 2026-10-30
---

Migration must re-point every edge including user-data ALIGNS_TO, run under roll lock with writes paused, abort on count mismatch. Dry run with a report comes first. Still queued as of 10-30 report.
