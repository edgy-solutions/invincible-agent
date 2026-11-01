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
updated: 2026-11-01
---

0.4.74 carries #177 #178 #180 #182. Fork 1 binds the roll: the stored evidence refs are counted on sandbox first (read-only SQL prepared, needs Chris's OK). Values diff to Chris before the roll. The ReviewCoverage deletion is its own PR (fork 3).

Fork 1 measured 10-31: the sandbox stores 0 evidence_ref values (ddr 10, htp 126, isp 110 rows scanned; literal control 2 of 2). The SDK rule refuses no stored data. No roll overnight; the two syncs are in the packet to Chris of 10-31.

Cut 10-31 as #197, merged as ab339ceb (cortex c27e6d3, fa7e51ff). Values diff vs live: cortexUi.image.digest and global.imageTag only (in the packet to Chris). The roll waits on Chris's two syncs and his OK on the diff.
