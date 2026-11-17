---
title: Master red: four cited docs paths don't resolve
feature: docs
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#430]
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-16
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_citation_paths.py::test_every_cited_docs_path_resolves names `doc-tools/docs/contracts/training-workbench.md` (cited bare by the 0.4.70 release note, line 91), `pcn-corpus-validation-2026-09-21.md` at the docs root and `v0.5.0.md` under docs/releases (both cited from Lane 1 sessions).

A fourth path is on fin's item, so the test stays red until both are done.

Measured at the 0.4.78 cut: the dead paths are also cited from sessions, `docs/releases/0.4.70.md` and a test docstring, not only from this item, so the fix is more than a board edit. The fourth is mine: 0.4.78's changelog cites cortex-ui's card spec by a path the test reads as this repo's; the identity fix branch rewords it.

Reassigned 2026-11-06 from invincible-agent/lane/01 to invincible-agent/lane/gov (architect confirmed Lane 1's reassignment table, 2026-11-06).

2026-11-16, Lane 1, on the architect's overnight order: the cross-repo cites are qualified with their repo (doc-tools, cortex-ui); the scanner reads tracked files only, so session packets no longer count; dag-tools' verbatim mfg_trace fixture is a declared vendored copy. Fixed on branch lane/01-three-citation-reds.
