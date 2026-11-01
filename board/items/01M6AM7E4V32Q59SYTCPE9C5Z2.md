---
title: P6 outage/no-grant seal on the review export routes
feature: cross-cutting
lane: invincible-agent/lane/saf
repo: invincible-agent
status: review
priority: now
blocked_on: []
pr: [invincible-agent#194]
ruling_ref: architect forks 16/17 10-31
updated: 2026-11-01
---

Test-only. Two strict xfails pin can_invoke_or_unavailable's defects (a list/null 200 is an unhandled 500; a string check admits); #190 fixes both. Merge #194 first, then #190 drops the markers (gov's proposal). Minted by Lane 1 at gov's request.
