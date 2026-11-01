---
title: Caller JWTs at rest in the checkpoint store: remediate existing rows
feature: cross-cutting
lane: 
repo: invincible-agent
status: open
priority: now
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-09-24
---

dormant since 09-21; was lane 32's, handed to lane 74. Durable checkpointer held five distinct caller bearer tokens, fifteen plaintext copies, no expiry (measured 09-23/09-24; counts only). A write-side scrub, agent_fleet/graph_host/identity_scrub.py, is on master (wiring not checked). No purge of existing rows found in sessions after 09-24 (grep, not exhaustive). Waiting on: chris: remedy for rows already stored (09-24 report: neither remedy is lane 74's).
