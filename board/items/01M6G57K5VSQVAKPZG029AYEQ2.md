---
title: The gateway delegate list is a rail file with its validator; nothing reads it yet (#224)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#224]
ruling_ref: architect overnight instruction (the delegate list as a rail file with its validator)
updated: 2026-11-04
---

`policy/gateway_delegates.yaml` and a `validate_policy` arm. No answer changes: the reader, the manifest relation and any sync stay with lane/01, whose bound question is 01M6FZQ9TK0F5VQS2E1ERZ927Y. Three readings are gov's and not ruled, and #224 asks the architect to check them: which list this is, the first row (`svc:data-analyst` on `assets.authorize`), and `GATEWAY_ROUTES` as a module constant. Mutants G1-G14 killed.

#224 is merged. This stays in review because the three readings have had no answer from the architect as of 2026-11-04.
