---
title: Pinned overlay-drift seal and gate triggers (nightly suspended)
feature: docs
lane: doc-tools/lane/7f
repo: doc-tools
status: done
priority: later
blocked_on: []
pr: [doc-tools#179, doc-tools#181]
ruling_ref: architect 10-27 suspend nightly
updated: 2026-10-30
---

Nightly corpus gate suspended, fires on pin bump or explicit lane fire; staleness is a digest. Drift seal now reads a pinned sha (#181, merged 10-30). Residual: required job's warning text still falsely says a measured fail blocks the pin.
