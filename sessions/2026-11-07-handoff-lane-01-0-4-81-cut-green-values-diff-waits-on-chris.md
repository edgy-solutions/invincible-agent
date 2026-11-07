to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-11-07 (05:40Z)
supersedes: 2026-11-06-handoff-lane-01-0-4-80-rolled-synthetic-event-waits-on-a-credential.md

# 0.4.81 is cut and master is green; the roll waits on Chris's approval of the values diff

## NOW: waiting on Chris (nothing is rolled)
- **The report to Chris** is in the master tree, uncommitted:
  `sessions/2026-11-07-packet-to-chris-from-lane-01-0-4-81-is-cut-master-is-green-the-values-diff-for-your-approval.md`.
  It asks five decisions: approve the values diff; which six architect items the sweep closes, with
  ruling texts; a menu row or a ruling for FLOW_DECOMPOSITION; cortex's `data_provenance` question;
  the cortex pin (93d76e8 vs 0dc53663).
- **The values diff:** `<scratchpad>/valdiff-481-masked.txt` (28 of 238 keys).
  - The two fin flags, the cortex digest, and 19 image digests. All 19 equal `image-digests.json`.
  - Six secret-file keys show by hash only. Their live hashes are identical to 0.4.80's, so not a
    change.
  - Between the tags, templates are unchanged.
- **The release worktree** is `<scratchpad>/rel481`, detached at `f08217b2`. The release assets are
  in `<scratchpad>/rel0481`.
- **The sandbox:** rev 227 (0.4.80), deployed, 7 of 7 nodes Ready (05:30Z).

## Done this window
- **#283** `de9f5fee`, **#280** `b71a6aa2`, **#286** `2cc05912`, **#289** `2ebb91d0` (saf's
  finding, `not_the_seeding_delegate`), all merged.
- **#284 (the cut)** merged at `f08217b2`, which is tag `invincible-agent-0.4.81`.
  - The master Build is green on every job, including the release.
  - `image-digests`: 19 images, 19 expected, nothing missing, failed or conflicting.
- **Board:** cortex's item `01M6T3M9MZ74CZJ4T0W6HRRW5Q` is committed in the cut.
  - Two renders: `docs/BOARD.md` comes from `docs/plans` via `scripts/generate_board.py`, and
    `board/BOARD.md` comes from `board/items` via `scripts/render_board.py`.
  - The generator writes CRLF on this box; strip it before staging.
- **Packets placed (uncommitted):**
  - saf, in the master tree `sessions/`: #287 must merge master and drop its strict xfail.
  - cortex, in `cortex-ui/sessions/`: the flow row is held, because no menu carries
    FLOW_DECOMPOSITION.
- **Gov's G6:** no packet needed. Gov's own G6 packet already says authz_id is served and that
  #286 is Lane 1's half.

## Held
- **The FLOW_DECOMPOSITION projector row:** branch `lane/01-flow-decomposition-is-projected`
  (`01ef9bcb`, pushed, no PR), worktree `<scratchpad>/flowrow`.
  - `test_every_archetype_in_the_projector_is_CLAIMED_or_EXCUSED_BY_NAME` is truly red on it.
  - Waits on a cortex `assembleCapabilities` row, or a ruling. Never excuse it falsely.

## The roll, after approval only
1. **Gates:** the doc-tools window; avoid 07:00Z; all nodes Ready; list STARTED runs; re-read every
   inbox; roll lock as `invincible-agent/lane/01`.
2. **Then:** fin's live check (granted and denied callers, 3 runs each, plus a CDRL export each).
   If either caller fails, roll back to rev 227 under the same lock.
3. **Then** the refile walk with the `/me/entitlements` readiness step.
4. **Then** tr's hour.
5. **After the roll:** tell cortex and 7f the case fields are live, and tell cortex its board item
   has unparked.

## Queued
- **The board sweep (six items)**, once Chris names them.
- **Forks 1+3** (`01M6KF81WMJJXVKQAP12M0QTMY`): ruled for 0.4.81, not built.
- ADR A–E; the alice Topaz delete (goes to Chris); NetworkPolicy (Jena → Weaviate → Neo4j, by
  12-01).
- Clean up `<scratchpad>/rel480`.
- Items `01M6QGKGVF12QW1REN9K0K1HMB` and `01M6QGKFTKSD18ZAPMA285F25X`.
