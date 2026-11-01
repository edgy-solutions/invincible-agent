---
title: Runner refuses a pixel box (normaliser)
feature: pcn-pdn
lane: invincible-agent/lane/01
repo: invincible-agent
status: review
priority: next
blocked_on: []
pr: [invincible-agent#188]
ruling_ref: architect post-roll list 10-31
updated: 2026-10-31
---

#188: the runner's normalize_evidence_ref validates a dict ref with the SDK EvidenceRef, so it refuses what the BFF refuses. No hand-coded null-note rule; the SDK aligns it in v0.9.13.
