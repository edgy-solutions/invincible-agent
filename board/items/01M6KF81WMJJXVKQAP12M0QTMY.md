---
title: The BFF's DELEGATE_ON_BEHALF_OF reads policy/gateway_delegates.yaml (one list, two readers)
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect 11-04 on #224's three readings
updated: 2026-11-04
---

Architect 11-04, reading 1: `policy/gateway_delegates.yaml` is the central gateway's list. The BFF's `DELEGATE_ON_BEHALF_OF` (R-089) is the second internal door; it stays in the chart's values today and reads the same file at the next cut, where a BFF-only row carries `door: bff`. Scheduled for lane/01, not a retrofit in #224.

`validate_policy` refuses a `door` key today (`_GD_ROW_FIELDS`), so the same change adds it there.

#251 builds the first half: the `door` key in `validate_policy`, and the BFF reading the `door: bff` rows for `human_tasks.register` (the list #251 added). `DELEGATE_ON_BEHALF_OF` itself still comes from the chart. It names, for each delegate, which people it may act for, and a rail row has no field for that, so moving it is a question for the architect.
