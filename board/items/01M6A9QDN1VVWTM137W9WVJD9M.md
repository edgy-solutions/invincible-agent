---
title: concepts.normalise alignment pass, contract v5
feature: training
lane: doc-tools/lane/tr
repo: doc-tools
status: review
priority: next
blocked_on: []
pr: [doc-tools#195]
ruling_ref: architect 10-30: ALIGNS_TO from Concept side flipped, doc-tools owns alignment
updated: 2026-10-30
---

Open PR (PR B): alignment pass writes PROPOSED_ALIGNS_TO, ownership of CanonicalConcept/ALIGNS_TO moves from wb to doc-tools, stays dry until wb's harmonizer is off. Golden v5 hash ef1a8799 pending a re-golden from a clean start after merge; wb told not to re-pin.
