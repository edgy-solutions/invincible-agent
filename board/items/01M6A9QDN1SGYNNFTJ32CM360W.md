---
title: Cut and roll chart 0.4.74 (#177 #178 #180 #182)
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris:topaz_sync for mcp-callers before the roll, chris:the recipient readers sync before the roll]
pr: [invincible-agent#177, invincible-agent#178, invincible-agent#180, invincible-agent#182]
ruling_ref: 
updated: 2026-10-31
---

0.4.74 carries #177 #178 #180 #182. Fork 1 binds the roll: the stored evidence refs are counted on sandbox first (read-only SQL prepared, needs Chris's OK). Values diff to Chris before the roll. The ReviewCoverage deletion is its own PR (fork 3).

Fork 1 measured 10-31: the sandbox stores 0 evidence_ref values (ddr 10, htp 126, isp 110 rows scanned; literal control 2 of 2). The SDK rule refuses no stored data. No roll overnight; the two syncs are in the packet to Chris of 10-31.
