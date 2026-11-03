---
title: No-hardcoded-case rule: registry-driven runtime and domain passes
feature: docs
lane: doc-tools/lane/7f
repo: doc-tools
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: architect 10-30 config rule
updated: 2026-10-30
---

Audit of doc-tools against the rule found KIND_MAPPING and a domain_type if/elif ladder as case-in-code. Queued, not started: runtime reads served registry; ladder becomes passes per domain under ADR-0059. Architect said not a retrofit now.
