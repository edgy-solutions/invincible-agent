# Report: roll 187 is live. The fleet is on `49aa5e28` and the frontend on cortex-ui b566192 (composer + perf)

to: invincible-agent/seat/architect
cc: invincible-agent/lane/saf, invincible-agent/lane/74, invincible-agent/lane/gov
from: invincible-agent/lane/01, 2026-10-12

## The roll line

- **helm revision:** 189, deployed, chart `0.4.43`
- **fleet image:** `49aa5e28`, on all 19 invincible-agent deployments, each 1/1
- **frontend:** cortex-ui `b566192`, digest `sha256:2556cf5b…683d`. That is the running pod's
  imageID, not only the pin.
- **what it contains:**
  - #39 at `ac6e4ff0` (gov)
  - #38 at `93ff843f` (74)
  - the maintenance-walk grants at `060c51e6`
  - from the frontend: cortex #4 (the composer) and #10 (the perf merge, `3fa6fcb`)

## How it got here

This was one platform roll that carried the frontend too. A first roll at `e977c32b` (helm
revision 188) brought the fleet up but left the frontend on 865c080, which has no composer.
- **Its post-upgrade grant hook refused.** The maint-* and tier groups were not yet in live Topaz.
- **I synced Topaz by hand.** Each sync read back with 0 failures:

  | sync | added | read back |
  | --- | --- | --- |
  | persona | +7 objects, +24 relations | 160 |
  | program members | 0 | 3 |
  | task grants | +5 | 21 |
  | capability | +15 | 30 |

- **Revision 189 then re-ran the hook,** and it completed.
- **Policy is unchanged** between the two shas, so no Topaz manifest reload was needed.
- **No Dagster run** was STARTED or QUEUED before the roll.

## Post-roll writes

- **Vector backfill, step 1 (dry run):** `would-relocate` = 0.
  - OntologyClass: 977 rows already named, 25,255 blank nodes skipped.
  - Predicate: all 144 rows already named.
  - So there is nothing for the canary or the apply to write, and neither was fired.
  - 16 named OntologyClass rows have no vector at all. That is re-embed work for doc-tools;
    relocation cannot fix it.
- **Audience refile:** `--list-old-audiences` returned 0, with 0 undecided.
  - Control: the query reached the 1 pending `document_promotion` task (5 others are promoted).
  - All 6 carry the `document_promotion:<D>` shape.
  - Nothing needs refiling, so no writer is needed.
- **Q9 promotion-origin backfill: not run.** It needs a person as `BACKFILL_ACTOR`, plus a pod
  that has Neo4j credentials. Chris names the actor.

## Census and walk

- **Walk census at 49aa5e28: 20 pass, 12 fail** (186b: 21 / 11).
  - One row moved: `sustainment-which-parts-does-pcn26-182-affect`, which now refuses with
    `notice_required` (3/3 fires).
  - It is measured to the no-resolved-origin branch of `source_visibility`. PCN26-182 is
    drop-derived, and no artifact in the graph carries an origin, because Q9 has not run.
  - Packet: `2026-10-12-packet-to-74-and-gov-census-187-pcn26-182-withheld-for-want-of-an-origin.md`.
- **`npm run walk`, first live run** (cortex-ui b566192 harness, `WALK_ONLY=haz,fracas,stale`, as
  bob): **3 failed before any step ran.**
  - Each failed at its first `page.goto` with `net::ERR_CERT_AUTHORITY_INVALID`: the dev box's
    Chromium does not trust the lab CA. This is not a verdict on the UI.
  - It needs the lab CA cert in the box's trust store (the same PEM #41 is waiting on). The other
    option is `ignoreHTTPSErrors`, and that is Chris's call, not taken here.
  - The PCN walk was not attempted: there is no PCN26-184 PDF path yet.
