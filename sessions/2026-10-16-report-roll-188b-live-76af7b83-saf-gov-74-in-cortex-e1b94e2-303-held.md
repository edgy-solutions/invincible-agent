# Report: roll 188b is live on `76af7b83`. #46, #47 (bb0b5190), #51, #52 (as 74's 26274c52), the item-1 fix at :400, cortex e1b94e2. `:303` is held

to: invincible-agent/seat/architect
cc: invincible-agent/lane/saf, invincible-agent/lane/gov, invincible-agent/lane/74, cortex-ui/master
from: invincible-agent/lane/01, 2026-10-16
re: Chris's night-1 order, item 1: "188b: #46, #47 (bb0b5190+), #51, #52, the step-1 permission
fix, cortex e1b94e2. Roll. Report line on master. Tell 74/saf/gov."

## The roll line

- **helm revision:** 192, deployed 2026-10-16 05:06Z, chart `0.4.46`. Revision 191 was 188.
- **fleet image:** `76af7b83`, the full-sha tag, on all 19 invincible-agent deployments, each 1/1.
- **frontend:** cortex-ui `e1b94e2`. The running pod's imageID is `sha256:8d0234ab…`, the digest
  pinned in `values-sandbox.yaml`.
- **master:** `785a0d5d..76af7b83`, fast-forward. The set was merged by sha on `lane/01-rev188b`,
  each part `--no-ff`:
  - #46 saf `dbe0339b` (`21d27c46`);
  - #47 gov `6780e7d9` (`d70315a5`), then gov's tip `bb0b5190` (`b0dfbd67`): a `svc:` user_email
    is absent in every census arm;
  - #51 lane/74 `689388db` (`9879cb93`): one identifier namespace, one claimant;
  - the step-1 permission fix `4250548f`: a declared query (a mesh verb) is checked as the run's
    acting identity, never as the case runner;
  - #52 as lane/74's `26274c52` (`b85a86ff`): the Engine A smoke is an ORIGIN with a sealed
    source. My hop 18 (`891134e2`) is reverted in `51e1dc4a`;
  - chart 0.4.46 `32dad527`: cortex-ui pinned to e1b94e2 by digest, `VITE_REVIEW_ROW_EDITS`
    "false".
- **gate:** 41 test files, one at a time, against the merged tree: the merges' own files, every
  identity and walk consumer, and the chart seals. 40 exit 0. The one red was lane/74's
  person-chain seal (`test_the_person_reaches_the_migrated_route.py`), on #52's unregistered
  smoke dispatch. 74's `26274c52` settles it: 55 passed. My two mutants red on its arms: M1, a
  literal persona; M2, the environment key renamed. CI on `76af7b83`: image build and chart
  release both green.
- **Dagster:** before the roll, 0 runs were QUEUED, STARTING or STARTED. One run was STARTED at
  05:27Z, after the roll. It completed on its own; at 05:30Z there were 0 in progress.
- **after the roll:** the BFF `/health` answers 200. The Dagster daemon and webserver each
  restarted once at start, on "too many retries for DB connection" while postgres came up. Both
  have been Running since.

## What the roll does not carry

- **`:303` is held.** Chris's order: "Roll with :303 held". A `direct_call` keeps the runner's
  identity, so `origin.write` stays `svc:case-runner`'s. Your ruling between (a), (b) and (c) is
  still open. 188b ships (a)'s behaviour.
- **Steward row edits are off** on the sandbox (`VITE_REVIEW_ROW_EDITS: "false"`, chart 0.4.46).
  Your condition for keeping them on was one confirmed live correction, and none exists.
- **A pre-existing red, not 188b's:** `test_citation_paths` was red on master before 188b, and is
  unchanged by it.
- **A red that IS 188b's, and that my gate missed.** lane/gov's ratchet
  `test_the_stub_harness_puts_sys_modules_back.py` fails on `76af7b83` (1 failed, 23 passed). The
  one file it names is #51's `tests/routing/test_one_identifier_namespace_one_claimant.py`, lines
  170 and 174: a mesh_registrar loader that writes `sys.modules` with no put-back. It is a test
  hygiene red, not a runtime one: nothing that rolled changes. #51 added a test file, and the
  ratchet scans every test file, so it belonged in the 188b gate and was not there. The 189 gate
  caught it. The fix is lane/74's file, and the seal is gov's. Both are told.

## The manufacturing-stewards group: synced live, and it survived this roll

`manufacturing-stewards` was synced to Topaz by hand, from 189's policy. I read it live after
this roll: the group object is present (200), and its one relation is `member` →
`user:bob@example.com`. Neither of the roll's two Topaz hooks (`topaz-manifest-load`,
`task-grant-sync`) removed it. No topaz seed CronJob runs on the sandbox.

**A hand-run `topaz_sync` from a pre-189 policy would prune it.** 188b's `policy/` has no
`manufacturing-stewards`, and `topaz_sync` deletes what its policy does not name. Until 189
rolls, run `topaz_sync` only from `lane/01-rev189`'s policy.

## For saf: HAZ-1003, and which build your FRACAS batches ran on

HAZ-1003: exactly one live task — `risk-acceptance-HAZ-1003-medium~1:acceptance`, pending, bob,
opened 2026-10-04 02:36Z; your three sends attached to that open case (same WorkflowRunner key),
opening nothing new; the only other row is the retired SafetyAcceptance task, superseded 10-05.
The vector backfill touched nothing (187 dry run would-relocate 0; no apply since) — your FRACAS
1-2 (by 16:43Z) and 3-5 (by 17:10Z) straddle roll 188: BFF on c9091040 from 16:37:48Z, every
engine restarted and re-registered 16:51–16:52Z; your batches were not all on 49aa5e28.

Saf's 10-12 digest is on master (`ca168055`, in 188b), with the from/to lines added and a kube
context name removed from line 3. That is a forward scrub: the name is still in saf's pushed
`23e2a383` and `78b7a2be`, which I did not rewrite.

## Next

- 189 is staged on `lane/01-rev189`, not rolled. Its gate and contents go in a separate packet.
- The broker flip (#41, now chart 0.4.47 on `lane/01-broker-flip`) waits on OpenDDIL's CA. The
  client Secret is in; the CA Secret is not.
