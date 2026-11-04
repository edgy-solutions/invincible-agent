---
title: Two SDK convergence swaps ca says are now open: EvidenceRef at ingest, Refusal at the envelope
feature: api-sdk-mcp
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: ca's 11-03 packet on two stated convergence conditions
updated: 2026-11-04
---

`ingest_api.py:200` can take the SDK's `EvidenceRef`; run `tests/test_an_evidence_ref_is_the_sdks_rule_page_fractions_or_a_422.py` before it. `src/iagent/authz/refusal.py:124` can use `Refusal` at the current pin. `PartialRefusal` needs a later SDK pin than ours.
