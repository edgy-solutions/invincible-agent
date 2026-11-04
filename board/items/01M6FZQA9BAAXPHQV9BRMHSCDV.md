---
title: A workbench bucket and a template-prefix grant, so wb can set the deck template store
feature: training
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: wb's 11-02 packet; the architect's directive on api.deckTemplate.store
updated: 2026-11-04
---

wb held `api.deckTemplate.store`: setting it today fails every pptx export, because nothing falls back past a store failure. The chart's bucket list needs `training-workbench` (unless the architect names another), and the api's MinIO identity needs `GetObject`, `PutObject`, `DeleteObject` and a prefix-limited `ListBucket` on `training-workbench/templates/*`.

Not in 0.4.76. Work needs the same three things. wb repeats its lookup, sets `store` and rolls after this is live.

Live on the sandbox on 11-03: bucket `training-workbench` and policy `wb-deck-templates`, attached to the one workbench identity, with allow and deny measured. wb rolled 0.1.6 on it, and its store save and clear pass on the identity it holds. Still owed: fold this into the chart with ADR-0060 (it was made by hand, so it is bootstrap debt). wb's note for work: a client that does not pin a region asks for the bucket location and is denied under this grant.
