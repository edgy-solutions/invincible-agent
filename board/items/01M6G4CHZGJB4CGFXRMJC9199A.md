---
title: Which chart rolls: 0.4.78 is cut and can't meet the #229 ruling as cut
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: now
blocked_on: []
pr: [invincible-agent#244]
ruling_ref: architect 2026-11-04: roll 0.4.78 now
updated: 2026-11-04
---

The 0.4.76 tag has the stale corpus from `01M6G4CHEPNTD3XXZ3GTVG3KS6`. The prime's own drift predicate, run against the tag, names `rolling-a-service.md`, so the post-upgrade prime would refuse. The roll itself has not been run.

0.4.77 carries cortex `26a2049`, #222, #225 and #230. Its changelog says what was wrong with 0.4.76. Then: values diff to Chris, one `topaz_sync`, the roll, and tr's lock hour before any other lock.

0.4.77 stands as cut at `8fc02746` and rolls nowhere, as ruled. 0.4.78 is published at `8a2717e0`, 19 of 19 images, not rolled. It carries #229, but neither the card nor the exchange: the card needs a later chart (pause fields and a cortex pin), and the exchange needs a chart change or a hand-made client. The choice is in the 11-04 morning note. The live release is 0.4.75.

Ruled 2026-11-04: roll 0.4.78 now. It rolled as revision 226, and helm reports it deployed with every pod ready.
