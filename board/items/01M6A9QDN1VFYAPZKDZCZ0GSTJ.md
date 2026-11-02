---
title: A PDP answer is a JSON boolean or an outage (16 readers; #190)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#190]
ruling_ref: architect 10-31 forks 16 and 17; 11-02 merge order
updated: 2026-11-02
---

Saf seal review found can_read_recipient admits {'check':'false'} (3 of 7 forms), a fail-open. Not in #181's diff; packet placed to gov, cc architect.

gov 10-31: #190 is the PDP-answer class (16 readers). CI green at b1b02e93. It also fixes saf's two #194 defects; merge order proposed: #194 first, then #190 drops the two strict xfails.

gov 11-02: the architect ruled that order. #190 waits on #194 (01M6AM7E4V32Q59SYTCPE9C5Z2); once #194 is in, gov merges master, drops the two xfails and tells lane/01 it is ready.
