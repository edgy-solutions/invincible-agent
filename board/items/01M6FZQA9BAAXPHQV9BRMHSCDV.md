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
updated: 2026-11-03
---

wb held `api.deckTemplate.store`: setting it today fails every pptx export, because nothing falls back past a store failure. The chart's bucket list needs `training-workbench` (unless the architect names another), and the api's MinIO identity needs `GetObject`, `PutObject`, `DeleteObject` and a prefix-limited `ListBucket` on `training-workbench/templates/*`.

Not in 0.4.76. Work needs the same three things. wb repeats its lookup, sets `store` and rolls after this is live.
