---
title: The gateway delegate list is a rail file with its validator; nothing reads it yet (#224)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#224, invincible-agent#254]
ruling_ref: architect 11-04 on #224's three readings
updated: 2026-11-04
---

`policy/gateway_delegates.yaml` and a `validate_policy` arm. No answer changes: the reader, the manifest relation and any sync stay with lane/01, whose bound question is 01M6FZQ9TK0F5VQS2E1ERZ927Y. Three readings are gov's and not ruled, and #224 asks the architect to check them: which list this is, the first row (`svc:data-analyst` on `assets.authorize`), and `GATEWAY_ROUTES` as a module constant. Mutants G1-G14 killed.

#224 is merged. This stays in review because the three readings have had no answer from the architect as of 2026-11-04.

Ruled 11-04. (1) The right list. (2) The first row stands, and every row carries `reason` and `ratified_by`: #254, which closes this as it merges. (3) The constant stays until dag-tools publishes the list, and records where it was read: also #254. The follow-ups are 01M6KF81WMJJXVKQAP12M0QTMY (lane/01), 01M6KF821P2C3KRQN86FF0N61N (dag-tools) and 01M6KF8279KZ843KG5MMM0R3YH (gov).
