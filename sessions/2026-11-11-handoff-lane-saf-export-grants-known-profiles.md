---
to: invincible-agent/lane/saf
from: invincible-agent/lane/saf
date: 2026-11-11
---
# Handoff

This is the newest saf handoff. Earlier rounds (39-43) are in `2026-11-10-handoff-lane-saf-export-profile-server.md`.

## Round 44 - rulings owed from #356 (recorded)

Architect via Chris, 2026-11-11: (1) "reviewed" means the served state `review`. (2) An absent `exportable_states` list means promoted. (3) The uncorrected check (`corrections_not_applied`) stays a record rule. (4) The regenerated API docs stand; other lanes rebase onto them.

## Round 45 - Job 26: export grants and known profiles (0.4.85 train, green by Thu 2026-11-12 12:00Z)

Ruling: (1) An export profile with no grant is not an error anywhere: deny by default, absent from listings, refused at the route. (2) A `can_export:<name>` grant naming a profile this deployment does not know refuses that row only, with a report; the rest of the sync proceeds. (3) Known = the image's base profiles plus the deployment's policyOverlay exports; sample profiles are known only where the sample overlay is loaded. Accepted plan: the grant-sync Jobs see the same overlay as the pods, a template/values edit with no Chart.yaml bump (the release bumps it).

Built on `lane/saf-export-grants-known-profiles` (from 8c3eb9af): `validate_policy` no longer errors on an unknown name or a profile with no row (only COLLISION/REFUSED notes); `offline_overlays` is gone from the registry; `capability_grant_sync.main` refuses unknown `can_export` rows one at a time (stderr `REFUSED ROW capability[...]` line each, stdout `can_export rows: N applied, M refused`, exit 0; a refused row's old relation is pruned; if the known set cannot be composed nothing is refused and a WARN says so); chart helper `invincible-agent.podOverlayEnv` exports the pods' `*_OVERLAY_DIRS` (and, in git mode, every policyOverlay component dir that exists) in the topaz-seed CronJob and task-grant-sync Job; values-sandbox sets `INGEST_EXPORT_PROFILE_OVERLAY_DIRS` (the sandbox never loaded the sample review exports before).

Finding for the architect: the `can_export:cdrl_*` rows exist in `policy/capability_grants.yaml` but no engine consults `can_export` for a CDRL profile (recipient-reader checks gate the CDRL path), so those rows gate nothing today.

Seals: `tests/security/test_an_export_grant_names_a_known_profile_or_that_row_is_refused.py` (16, each with a control); 8 mutants, all killed, restored by `cmp`. Edited other lanes' files: gov's `test_can_export_capability_rail.py` (sections 1, 4, 5), `test_task_grant_startup_sync_renders.py` (window 4500 to 6000). Live syncs are Chris's; the sandbox needs the chart roll for the Jobs to see the env.
