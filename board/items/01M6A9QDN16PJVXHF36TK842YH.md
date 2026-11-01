---
title: #181 recipient readers rail: 503-on-outage fix and template-door seal
feature: finance
lane: invincible-agent/lane/fin
repo: invincible-agent
status: review
priority: now
blocked_on: []
pr: [invincible-agent#181]
ruling_ref: architect 10-31: an outage answers 503, no readers answers 403
updated: 2026-10-31
---

saf seal review at 2a3385f0: six doors hold, but GET/POST /export/package/recipients answer 200 with [] on an outage. Seal P6 (18 red) and the template-door gap must land in #181 before it merges.
