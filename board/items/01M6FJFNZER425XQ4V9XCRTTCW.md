---
title: A malformed PDP answer is a 503 at every site, including the fail-closed ones (fork 22; #210)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#210]
ruling_ref: architect 11-02 fork 22
updated: 2026-11-02
---

The sites that read every failure as a deny now give a malformed answer its own arm. A route answers 503; a Restate gate raises TerminalError(503) inside its ctx.run; a tool-loop engine discards the chunk and fails after the loop. Also moves two behaviours: the autonomous gate's deny is now terminal, and POST /internal/origin/write answers 503 where it answered 500. Under 0.4.76, not yet cut; 0.4.75 was tagged at aac9900b without it. Open question to the architect: a transport outage at these sites is still a no.
