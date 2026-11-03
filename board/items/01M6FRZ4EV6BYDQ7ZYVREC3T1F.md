---
title: Master red: three cited docs paths don't resolve
feature: docs
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_citation_paths.py::test_every_cited_docs_path_resolves names `docs/contracts/training-workbench.md` (docs/releases/0.4.70.md:91), `docs/pcn-corpus-validation-2026-09-21.md` and `docs/releases/v0.5.0.md` (both cited from Lane 1 sessions).

A fourth path is on fin's item, so the test stays red until both are done.
