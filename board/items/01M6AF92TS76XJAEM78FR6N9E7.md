---
title: Finding rows carry artifact null on answered verbs: contract needs a third state
feature: finance
lane: 
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-09-23
---

dormant since 09-21; was lane 32's. Brief rows show artifact null on verbs that ran and answered. Lane 74 (09-23) found engine-fin's payload carries neither artifact_id nor id, so the graph does not drop one. Per 32's own branch the SourceLedger contract (artifact string or null) needs a third state; awaiting architect ruling, none found on master. Waiting on: architect: rule the third state for artifact on finding rows (lane 74 found no artifact exists for those verbs).
