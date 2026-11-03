---
title: Master red: the phantom allowlist's acceptance-consumer entry is past 30 days
feature: cross-cutting
lane: invincible-agent/lane/74
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_citation_paths.py::test_phantom_allowlist_is_honest fails on the `…acceptance-consumer…` entry: allowlist line 94, f63f3b94, PENDING 34 days. It retires when `lane/74-acceptance-and-docs-subject` (cea00aad) merges or is retired, so lane/74 decides which.
