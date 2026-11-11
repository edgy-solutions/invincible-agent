---
to: invincible-agent/lane/saf
from: invincible-agent/lane/saf
date: 2026-11-10
---
# Handoff

This is the newest saf handoff. Rounds 39 and 40 (the attestation split, then the attestation read from the kind row, PR #354, on the 0.4.85 train) are in `2026-11-10-handoff-lane-saf-attestation-split-sealed.md`; Round 40 rides on #354 and is not on master until it lands. This file is a separate file so the two PRs do not conflict.

## Round 41 - the export-profile server (Job 24; NOT on 0.4.85)

Ruling (architect): overlay on the export-profile loader (add, replace by name, tombstone) plus registry entry and optional chart line; profiles gain `accepts`, `grain` (+ optional `dedupe`), `version`; the server serves only the profiles the caller may use and lists unexportable notices with reasons before any file is built; one route `POST /ingest/export/notices` records actor, notice ids, profile id and version; a generic `part-list` sample (per_part, one column) in the sample overlay; a seal plus control for each; merging the answer-export loader in is a later item (board `01M75A0S4X1E9T3N7WQ2D6HKZB`).

Built on branch `lane/saf-export-profile-server` (from origin/master a02cfda3): `src/iagent/export_profiles.py` (one composed set, overlay env `INGEST_EXPORT_PROFILE_OVERLAY_DIRS`), `src/iagent/gateway.py` (filtered listing, preflight, route, `iagent.audit.ingest_export` record line), `ingest_api.py`, registry row, chart line (optional, off by default, NO version bump), `can_export:part-list` seed row, manifest entries.

Seals: `tests/routing/test_the_export_profile_server_is_sealed.py` (27 tests, each with a control); 15 mutants, all killed, restored by `cmp`.

Open: decisions 1-13 are in the PR body for the architect. Next step for whoever picks this up: if accepted, enable the overlay env in a values file (a chart bump, which rolls every pod: a separate, scheduled change).
