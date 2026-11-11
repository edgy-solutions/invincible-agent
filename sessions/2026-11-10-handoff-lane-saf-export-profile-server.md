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

## Round 42 - the architect's rulings on #356 (2026-11-11)

Rulings: (1) cortex's three questions are answered in the PR body: the wire says `notice_ids` (request) and `notice_id` (the unexportable list), never `ingest_id`; the download is gated on `ingest:exportBatch` AND `can_export:<profile>`; no separate resolve route, the one route resolves and returns the unexportable list. (2) Build to the rulings. If green by Thursday 2026-11-12 12:00Z it rides 0.4.85 behind reviewExport. (3) #354: Lane 1 merges by 180ce007. (4) #356 keeps its edits to other lanes' tests; each owner approves its file by packet before Lane 1 merges.

Done on #356 (forward commits): the unexportable list items are `{notice_id, reason}`; seals for "no response or record key is ingest_id/ingest_ids" (with a control), each gate alone refused (with a control), `check_only` records nothing and builds nothing (the same call without it records once), one POST route and no resolve route. Packets placed untracked in the master tree `sessions/` for gov, fin and Lane 1 (cc the architect seat): the merge precondition.

reviewExport: a cortex-ui flag, introduced by cortex-ui#48 (merged); no open PR in this repo carries it, so "merges after" names no PR here. #354 sha note: Lane 1 merges #354 at 180ce007; it carries Round 40 (the attestation read from the kind row).
