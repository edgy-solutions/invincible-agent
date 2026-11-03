---
title: The action-record door records a principal declared only for another delegate
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris:the architect rules whether a recorded name is bounded by the delegate list]
pr: []
ruling_ref: A2 fork ruling; saf's 11-03 packet asks whether it reaches records
updated: 2026-11-03
---

saf measured it: `POST /internal/cases/{case_id}/action-record` answers 200 and writes `req.on_behalf_of` as `produced_for.user_id` for a principal declared only for another delegate. It never asks `_delegate_principals()`. Strict xfail: `test_a_delegate_cannot_name_a_principal_declared_only_for_another_delegate[site3]`.

The architect's ruling (bounded by the list, or "records, not acts") also decides `requested_by` on `/internal/human_tasks/register`, `dropped_by` and `approver` on `/internal/origin/write`, and `seeded_by` on `/internal/cases/{id}/seeded-by` and `/summary`. Lane 1 recommended bounded.
