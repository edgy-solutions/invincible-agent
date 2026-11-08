---
title: A run that resumes after its client left writes no answer
feature: cross-cutting
lane: invincible-agent/lane/74
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; found reading #229 for cortex's card, predates #229
updated: 2026-11-06
---

`_dispatch_answer_artifact` in `gateway.py` runs inside the `/interview/stream` generator after its last yield, with no shield. When the client has gone, the generator doesn't reach it, so a run that finishes detached writes no answer. Read from the code, not run.

Cortex's card says this plainly in `resumed_detached` until it's fixed.

Reassigned 2026-11-06 from invincible-agent/lane/01 to invincible-agent/lane/74 (architect confirmed Lane 1's reassignment table, 2026-11-06).
