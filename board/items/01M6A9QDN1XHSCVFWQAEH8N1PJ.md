---
title: Batch fixture scrubber and column-map schema
feature: docs
lane: doc-tools/lane/7f
repo: doc-tools
status: done
priority: later
blocked_on: []
pr: [doc-tools#196, doc-tools#198]
ruling_ref: architect 10-30 batch chain
updated: 2026-10-31
---

Scrubber (#196) and the schema/validator (#198) merged 10-31. The scrubber refuses to call its own output committable; notice numbers are not in its allowlist.
