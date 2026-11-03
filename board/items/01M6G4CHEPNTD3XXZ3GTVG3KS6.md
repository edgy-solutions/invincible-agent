---
title: Master red: #212 edited a runbook and left the docs corpus stale
feature: docs
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: now
blocked_on: []
pr: [invincible-agent#212, invincible-agent#230]
ruling_ref: none; 11-03 full-suite census at ac1ebe69, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Five reds in `tests/test_docs_corpus_drift.py`. Witness: 16 passed at `d0ef4110`, 5 failed at `121272dc` (#212). #230 regenerated the corpus and merged at `d8074282`.

The 0.4.76 tag carries the stale corpus; see `01M6G4CHZGJB4CGFXRMJC9199A`.
