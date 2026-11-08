---
title: promote_answer_artifact's publish step posts a body register can't take, with a token in it
feature: cross-cutting
lane: invincible-agent/lane/74
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; found building the identity fix
updated: 2026-11-06
---

`policy/workflows/promote_answer_artifact.yaml` step `publish_artifact` is a `direct_call` bound to `/internal/human_tasks/register`. `execute_direct_call` posts `task_id`, `task_type` and `capability`, with no `audience`, `title` or `summary`, which the route requires, so the step is a 422.

It also puts `user_jwt` in the request body when the identity has one. Both predate the identity fix.

Measured for #251: the incomplete body is a 422 with a person's token, so the step could not succeed before that gate either. With a complete body, a person's token now gets 403.

Reassigned 2026-11-06 from invincible-agent/lane/01 to invincible-agent/lane/74 (architect confirmed Lane 1's reassignment table, 2026-11-06).

Split, architect 2026-11-06: this item is the workflow file (the incomplete body). The token-in-body half is a door defect, Lane 1's, on 01M6QGKFTKSD18ZAPMA285F25X.
