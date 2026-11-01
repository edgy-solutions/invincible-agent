---
title: One concept call per section, TEACHES replacement, contract v4
feature: training
lane: doc-tools/lane/tr
repo: doc-tools
status: review
priority: next
blocked_on: []
pr: [doc-tools#194]
ruling_ref: architect 10-30 ADR-0059 rulings
updated: 2026-10-30
---

Open PR (PR A): ExtractSectionConcepts per group of up to 8 slides, section summary/objectives to Weaviate chunk_kind=section, stale TEACHES replaced on re-augment. Weaviate rejects chunk_kind filter until a v4 ingest creates the property; wb must not ship the section-exclusion filter ahead of it.
