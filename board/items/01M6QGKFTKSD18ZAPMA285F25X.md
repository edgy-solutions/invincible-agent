---
title: execute_direct_call puts a person's token in a direct_call request body
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect 2026-11-06: W3's token-in-body half is a door defect, Lane 1's
updated: 2026-11-06
---

Split from 01M6JKE9VBD93B9TM8QCVDA23K (now 74's, the workflow file). `execute_direct_call` puts `user_jwt` in the request body of a `direct_call` step when the identity has one. That is how `promote_answer_artifact`'s `publish_artifact` step sends a person's token to `/internal/human_tasks/register`. The defect is the door's: a direct call must not carry a person's token in its body, whatever the step's body. Measured for #251: with a complete body, a person's token now gets 403.
