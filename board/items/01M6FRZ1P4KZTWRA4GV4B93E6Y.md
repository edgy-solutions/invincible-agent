---
title: Master red: values-sandbox.yaml cites a proposal that isn't in docs/
feature: finance
lane: invincible-agent/lane/fin
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#238]
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_citation_paths.py::test_every_cited_docs_path_resolves names `docs/proposals/a-measure-is-an-overlay-row-…` at values-sandbox.yaml:112, from 1390ce8f (fin). Land the proposal or change the citation.

Three other paths in the same test are on Lane 1's item, so it stays red until both are done.
