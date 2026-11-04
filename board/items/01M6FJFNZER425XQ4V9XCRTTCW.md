---
title: A malformed PDP answer is a 503 at every site, including the fail-closed ones (fork 22; #210)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#210, invincible-agent#231]
ruling_ref: architect 11-02 fork 22; fork 24 (transport outage is 503 too)
updated: 2026-11-04
---

The sites that read every failure as a deny now give a malformed answer its own arm. A route answers 503; a Restate gate raises TerminalError(503) inside its ctx.run; a tool-loop engine discards the chunk and fails after the loop. Also moves two behaviours: the autonomous gate's deny is now terminal, and POST /internal/origin/write answers 503 where it answered 500. Under 0.4.76, not yet cut; 0.4.75 was tagged at aac9900b without it. Fork 24 is ruled: a transport outage at these sites is a 503 too.

#231 builds fork 24: an unreachable Topaz or a non-2xx answers 503, and a 404 from a directory check stays a no. It changes what a caller sees during a blip. In-process only; nothing ran live for it.

Both merged. Nothing has run live for either until a chart carrying them rolls.
