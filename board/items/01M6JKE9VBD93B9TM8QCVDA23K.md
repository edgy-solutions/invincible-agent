---
title: promote_answer_artifact's publish step posts a body register can't take, with a token in it
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; found building the identity fix
updated: 2026-11-04
---

`policy/workflows/promote_answer_artifact.yaml` step `publish_artifact` is a `direct_call` bound to `/internal/human_tasks/register`. `execute_direct_call` posts `task_id`, `task_type` and `capability`, with no `audience`, `title` or `summary`, which the route requires, so the step is a 422.

It also puts `user_jwt` in the request body when the identity has one. Both predate the identity fix.
