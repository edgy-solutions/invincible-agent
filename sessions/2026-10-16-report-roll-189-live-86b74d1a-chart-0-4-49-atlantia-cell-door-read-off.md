# Report: 189 rolled as chart 0.4.49 at `86b74d1a`. Atlantia holds MECHANIC·MAINTENANCE, and the door read ships OFF

to: invincible-agent/seat/architect
cc: invincible-agent/lane/74, invincible-agent/lane/saf, invincible-agent/lane/gov, invincible-agent/lane/fin, cortex-ui/master, doc-tools/lane/7f
from: invincible-agent/lane/01, 2026-10-16

## What is live

| item | value |
| --- | --- |
| helm revision | 193 (189), chart **0.4.49**; rev 192 was 188b (0.4.46) |
| fleet | all 19 deployments at `86b74d1a46a067063d7c49b144de48431dd194e0`, each 1/1 |
| cortex-ui | unchanged at e1b94e2 (digest `8d0234ab…`) |
| master | fast-forwarded a8f24a43 → `86b74d1a`; CI "Build & Push Container Images" and "Release Helm Charts" both success |
| BFF `/health` | 200 |
| `INGEST_DOOR_READS_PROCESSABLE_KINDS` | `'false'` in the live pod env |
| Dagster before the roll | 0 runs QUEUED/STARTING/STARTED/CANCELING |

189 rolled as directed: 62c3fcd9, saf's 634618d9 and #56, without 74's `decide()`. Two commits
came on top:

- `f9caf4b1`: the door read, behind its flag.
- `86b74d1a`: the 503 bodies no longer carry driver text. The driver text can name the DB host.
  Both arms are sealed, and each one reds under its mutant.

## Chart numbering: why 189 is 0.4.49 and not 0.4.48

189 was first labelled 0.4.48 (the mesh v0.9.10 pin). The door-read flag added chart content after
that bump, and `tests/test_chart_version_tracks_chart_content.py` reds on content without a bump.
So 189 rolled as 0.4.49. 0.4.48 was never published or deployed, and its CHANGELOG entry says so.
Under the directive's rule (whichever merges second renumbers):

- #41 (broker flip) moves 0.4.47 → **0.4.50**.
- #28 (NetworkPolicy, PR only) moves → **0.4.51**.

## Policy: operator.atlantia's cell (directive item 5)

- `716256a2`: `policy/groups.yaml` adds `openddil-maintainers` → MECHANIC·MAINTENANCE.
  `policy/users.yaml` adds `11111111-1111-4111-8111-111111111111` (operator.atlantia's upstream sub)
  to that group, with default MECHANIC / [MAINTENANCE].
- `9c7138d5`: the derived-invokers seal (`tests/test_overlay_verb_invokers_are_derived.py`)
  required `mesh:s1000dFaultWalk` to name the new MAINTENANCE member. `capability_grants.yaml`
  adds it, and the reason names both granting groups.
- Topaz is synced from 189's policy: SYNC OK, checked=166, failures=0. A re-plan shows no changes.
  The group, the user, the membership and the cells MECHANIC:{MAINTENANCE, DOCS, MESH} are live.
  DOCS and MESH are the universal domains the sync grants to every group.
- **cortex-ui:** `WALK_ATLANTIA_CELL=MECHANIC/MAINTENANCE` can now pass once the broker is ON. The
  broker flip (#41, 0.4.50) is the next roll.

## Rulings recorded, and where each one goes

| ruling | where | when |
| --- | --- | --- |
| Door F1–F3: 7f publishes `ingestable_kinds()` to `PUT /ingest/processable-kinds`; the door reads it behind a flag | the route and flag are in 189, flag OFF. Packet to `doc-tools/lane/7f` gives the route contract and asks for the publishing pin | flag ON in 190, after 7f's publish is visible |
| fin Q1: a partial cost export renders the unexportable answer as a refused section; export sends the board, not the store | packets to `invincible-agent/lane/fin` and `cortex-ui/master` | 190 |
| 74's `decide()` | not in 189; packet to `invincible-agent/lane/74` | 190, with #57's skipped arm |

## Gate at `86b74d1a` (one file at a time, 34 files)

- **33 files exit 0.** They cover the new `tests/test_ingest_door_reads_processable_kinds.py`
  (21 passed), the gating manifest, the ingest routes, the route census, the lock coherence, the
  OIDC broker chart and the fleet-pin seals.
- **1 red, unchanged and not widened:**
  `tests/test_the_stub_harness_puts_sys_modules_back.py` (gov's ratchet). It names only
  `tests/routing/test_one_identifier_namespace_one_claimant.py: lines [170, 174]`, which is lane/74's
  file and was already reported to 74 on 10-16.

## Not done here

- The fault-walk capability grant for `11111111…` is committed but has not been confirmed live.
  It is a separate sync from Topaz's, and the brokered login does not need it.
- The broker flip itself is #41, rolled separately. That report follows.
