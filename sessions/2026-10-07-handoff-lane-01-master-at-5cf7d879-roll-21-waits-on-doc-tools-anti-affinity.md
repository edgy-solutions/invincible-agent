to: invincible-agent/lane/01-roll21
from: invincible-agent/lane/01-roll21
date: 2026-10-07
re: the third 2026-10-07 directive (items 1-5), where each stands
supersedes: 2026-10-07-handoff-lane-01-roll-21-gate-red-on-one-join-fin-file-vs-gov-ratchet.md

# Master is at 5cf7d879, gated; roll #21 waits on doc-tools' anti-affinity

## Item 1: done. Fin's red fixed, gated, merged, pushed

- **979a1c78:** the sys.modules restore in fin's `tests/routing/test_route_reason_is_recorded_not_inferred.py`.
  Committed by Lane 1 on Chris's instruction. Packet to fin:
  `invincible-agent/sessions/2026-10-07-packet-to-fin-lane-01-committed-your-sys-modules-restore-at-979a1c78.md`.
- **Gate on `5cf7d879`:** 16 failed / 6927 passed / 320 skipped, REAL_EXIT=1, 10:30. Log `../roll21-gate3.log`.
  - Compared by identity with `comm` against the e5416b89 gate: nothing new.
  - Gone: gov's sys.modules ratchet and `test_every_archetype_cortex_can_draw_has_SOME_projector_path`.
  - The 16 that remain are the standing baseline: the SDK pin (×5), cross-repo planning/finance
    drift, board, citation, chart-version, engine_b, trailer and the inbox addressing of old files.
- **`origin/master` fast-forwarded `e2207468` → `5cf7d879`** by sha, after checking that master
  had not moved. The push took on the first try.

## Item 2: the merge set, all ancestors of 5cf7d879

| set | merged as |
| --- | --- |
| saf (7): the six + a7730f3b | 732ae8a8, af88ff14 |
| fin (5) | ab9c5c61, f613ff46 |
| gov (9) at 1785244e | 6cbfa29b |
| cost-defects at 2eb22d56 | c18c587b (8551fc5a), d16db4f7 |
| declared-walk 3efd642a, e15877ef | ab9c5c61 |
| xml row 086a9cf0, with the grant row 92f7db1b (item 5) | 750d75f2 |
| pin cortex bd782c5 → `sha256:840d51145e75478caed2971a821cf66b27f6b9ff7d05596365c7b6d9fd84c9b3` | 5cf7d879 |
| projector rows ILLUSTRATION, WORKFLOW_CASE | 76d84e17 |

- **Gov's two newer commits** are NOT merged, because the directive said nine:
  - e5fb8319 (inbox addresses are `<repo>/<branch>`);
  - 97d22816 (handoff).
- **d16db4f7 conflicted in `gateway.py`.**
  - 2eb22d56 edited the export route's inline refusal block, which fin's 8bcf9fb7 had moved into
    `_shape_export_package_response`. That helper is shared by the cost and finance routes.
  - I kept the helper and moved the `outcome: unavailable` → 503 rule into it, so both routes
    say it the same way.
  - Measured: tests/cost/ plus the 16 export/review files gave 475 passed / 3 failed. All 3 were
    already in the baseline.
- **2eb22d56 also fixes the graph_host defect** the worker reported: `_fetch` now reads `refused`.
  It no longer needs routing.
- **Projector rows:** they sit in `_FLAT_ARCHETYPES`, each with its one required object
  (`illustration`, `case`), read from cortex's contracts. No producer emits either yet.
  Dropping WORKFLOW_CASE reds the coverage arm naming exactly WORKFLOW_CASE.
- **Pin, measured:**
  - the full tag resolves to the digest (OCI index, amd64 + arm64 + 2 attestations);
  - the short tag and the altered digest are 404;
  - the 8935e6a tag still resolves to c054ba50;
  - no Dockerfile, entrypoint or .github change;
  - `helm template` renders 840d5114.
- **Still owed: the xml content-kind overlay row** (domain null). doc-tools has no `xml` in
  `registry/content_kinds/` at e0e93d0. 7f has been asked.

## Item 3: roll #21, BLOCKED on one precondition

- **worker6 is Ready**, as are all 7 nodes. Read at 21:3x local.
- **7f's anti-affinity pin is NOT live.** The doc-tools Deployment has no `affinity` at all.
  - It is on helm rev 36 (10:51 today, image `c39c4092…`), the roll in the worker6 death timeline.
  - doc-tools `origin` e0e93d0 pins cb2cf2d and does not mention affinity.
- When it is live:
  1. Show the values diff (`upgrade-sandbox.sh --dry-run` vs `helm get values`, secret keys by
     length and hash prefix).
  2. Roll with NetworkPolicy on. engine-o goes first or together; fin's 15d66aad reads its
     `classify_called`.
  3. Run the flag-on census ×3.
  4. Grant syncs are Chris's.

## Item 4: after the roll

- The fresh-notice PCN drop end to end: bob promotes, alice asks, provenance_floor.
- The six mock modules as xml/s1000d-data-module.
- The walk from the live graph.
- Rehearsal questions ×3, plus one refusal.
- Captures to cortex-ui/sessions:
  - lot 3 DELTA_SET (`cost-rate-comparison-lot-3-vintage`, alice/COST_ANALYST/[PRODUCTION_COST]);
  - a live `/cases/{id}`;
  - the promote.
- Owed after the roll: lane/saf gets the helm revision for the HAZ-1004 walk-census row, and
  cortex-60 gets the revision.

## Item 5: done

- The `mesh:s1000dFaultWalk` grant row is 92f7db1b, on master.
- engine-o's ordering is in item 3.

## Told

- **cortex-60:** xml is on master at 5cf7d879, plus the two projector rows.
  `cortex-ui/sessions/2026-10-07-packet-to-cortex-60-xml-is-on-master-at-5cf7d879-and-two-archetypes-now-project.md`.

## Noticed, not in this directive

- **The SDK tag may now exist.** cortex-ui 1e70904 says "ca pushed it" (v0.9.8). If that is true,
  the five SDK-pin reds can close with a re-pin to the tag. Gov's 97d22816 calls the re-pin a
  fleet fork, so the decision is the architect's.
