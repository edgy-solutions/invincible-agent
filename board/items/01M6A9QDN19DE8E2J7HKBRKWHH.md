---
title: Relays pass through and the case key is stamped (relay + I3)
feature: workflow-socratic
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#186]
ruling_ref: architect post-roll list 10-31
updated: 2026-10-31
---

#186: an engine's 409/422 keeps its status and keys (a 409 gains message), an empty or null 2xx answer is a named 502 engine_empty_answer, an empty 422 is engine_empty_body. I3's stamp was already on master; #186 adds its none/wrong/right seal.

Merged 10-31 as 16d0b6a6 (the train).
