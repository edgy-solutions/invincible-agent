---
title: 0.4.76 must not roll where the prime is on: cut 0.4.77
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: blocked
priority: now
blocked_on: [chris:the word to cut 0.4.77 and which chart rolls]
pr: []
ruling_ref: a defect in a pushed release is a patch that says what was wrong
updated: 2026-11-03
---

The 0.4.76 tag has the stale corpus from `01M6G4CHEPNTD3XXZ3GTVG3KS6`. The prime's own drift predicate, run against the tag, names `rolling-a-service.md`, so the post-upgrade prime would refuse. The roll itself has not been run.

0.4.77 carries cortex `26a2049`, #222, #225 and #230. Its changelog says what was wrong with 0.4.76. Then: values diff to Chris, one `topaz_sync`, the roll, and tr's lock hour before any other lock.
