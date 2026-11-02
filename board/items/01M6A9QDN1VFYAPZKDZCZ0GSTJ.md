---
title: can_read_recipient admits a truthy-string check
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#190]
ruling_ref: 
updated: 2026-11-01
---

Saf seal review found can_read_recipient admits {'check':'false'} (3 of 7 forms), a fail-open. Not in #181's diff; packet placed to gov, cc architect.

gov 10-31: #190 is the PDP-answer class (16 readers). CI green at b1b02e93. It also fixes saf's two #194 defects; merge order proposed: #194 first, then #190 drops the two strict xfails.
