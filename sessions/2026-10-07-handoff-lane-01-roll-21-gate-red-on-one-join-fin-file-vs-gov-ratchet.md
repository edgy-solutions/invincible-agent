to: invincible-agent/lane/01-roll21
from: invincible-agent/lane/01-roll21
date: 2026-10-07
re: the second 2026-10-07 directive (items 1-5), where each stands
supersedes: 2026-10-07-handoff-lane-01-roll-21-merge-held-on-two-lane-fixes-and-a-push-500.md

# Roll #21: the gate is red on one join (fin's file against gov's ratchet), so the master merge is held

## Push: works again

A retry with backoff landed on the first attempt. The 500s
(`AF1F:1E1B26:3234FA:42A673:6AC6617F`) did not recur, so nothing needs to go to GitHub support.

## Item 1: merge on the gate. HELD on one join red

Gated tip: `e5416b89` on `lane/01-roll21`. Every sha below was checked with `merge-base --is-ancestor`:

| set | shas | merged as |
| --- | --- | --- |
| saf (six) | 4f6dd2b3 823b02d0 c7da3110 fe8591fd 3e0aace2 88f65457, then the fix a7730f3b | 732ae8a8 (53095713), af88ff14 |
| fin (four, then its fix) | 8bcf9fb7, then the fix 5d646e29 | ab9c5c61, f613ff46 |
| gov (nine), with the three CLAUDE.md rules in f6513994 | 1785244e | 6cbfa29b |
| worker cost-defects | 8551fc5a | c18c587b |
| worker declared-walk | 3efd642a | ab9c5c61 |
| e15877ef | e15877ef | ab9c5c61 |
| item 2 | 086a9cf0 (with 92f7db1b) | 750d75f2 |
| pin cortex 8935e6a | 7bb59509 | (direct) |
| overlay rows and classes | 977007e8 | (direct) |
| master | e2207468 | e5416b89 |

Gate: 18 failed / 6906 passed / 320 skipped, REAL_EXIT=1, 11:13. Log `../roll21-gate2.log`, compared by identity with `comm` against the
19 reds of the ab9c5c61 gate.

- **Gone:** saf's walk-sheet control and fin's manifest row. Both lanes' fixes did what they said.
- **New: one red.**
  `test_the_stub_harness_puts_sys_modules_back.py::test_NO_FILE_WRITES_SYS_MODULES_WITHOUT_A_RESTORE`
  names `tests/routing/test_route_reason_is_recorded_not_inferred.py:67`.
  - Fin's 15d66aad added that file, and its session fixture writes `sys.modules` without popping it.
  - Gov's ratchet (6cbfa29b) refuses that.
  - Each branch is green alone. It is the join that reds.
- **The fix is owed by fin.** I did not edit the file, since it is another lane's. I measured a
  try/finally-and-yield fix in place: 35 passed with it, 1 red after restoring the original.
  Packet: `invincible-agent/sessions/2026-10-07-packet-to-fin-15d66aad-writes-sys-modules-with-no-restore-gov-ratchet-reds-the-join.md`.
- **The other 17 reds** are the ab9c5c61 baseline unchanged: the SDK pin, cross-repo drift,
  board, citation, chart-version, engine_b, trailer and inbox reds.

To resume:
1. Check fin's sha with `is-ancestor`.
2. Merge it by sha.
3. Run one full suite. Refuse to start under 2 GB free.
4. Run `comm` against `gate2-reds.txt` minus the ratchet identity.
5. Merge to master and push.


### Item 5: the overlap re-run

The ab9c5c61 gate (09:44–09:58) overlapped gov's implementer run, which started at 09:47.
- I re-ran its 17 red files alone, uncontended, at ab9c5c61. Log `../rerun-ab9c-reds.log`.
- Result: the same 19 identities, and `comm` is empty both ways.
- So contention did not cause any red, and that baseline stands.

## Item 2: done, except the xml row

- 977007e8 adds three overlay rows to `policy/overlays/openddil-lab/content_kinds/`: `pdf`,
  `engineering-document` and `doors-export`.
  - Each has `domain: null` written explicitly, per ruling 2026-10-02.
  - `passes` and `outputs` mirror doc-tools' `registry/content_kinds/`.
- 977007e8 also declares `mesh:EngineeringDocumentArtifact` and `mesh:DoorsExportArtifact` in
  `mesh_system.ttl`. Both sit under `mesh:PDFArtifact`, because a PDF is the only form that reaches
  the pass today.
- Seals:
  - `tests/test_content_kind_outputs_are_declared_classes.py`: every output must be a declared
    `owl:Class`. It is derived from both sides and was red on exactly the two phantoms first.
  - Two arms in `tests/test_gateway_ingest_routes.py`: the real overlay writes domain null on
    exactly the ruled kinds, and a stage review on each one goes to `awaiting_origin`. Dropping
    pdf's `domain` key reds both arms.
- `mesh:s1000dFaultWalk` capability row: 92f7db1b, inside 086a9cf0.
- **Owed: the xml row** (domain null). doc-tools `origin` at cb2cf2d has no `xml` in
  `registry/content_kinds/`. The ask is appended to the 7f packet. The overlay mirrors it once 7f
  generates it.

## Item 3: pinned; not rolled

7bb59509 pins `cortexUi.digest` to
`sha256:c054ba50f22e36f1389ba996e22625168869ee341889f2841ac0d99215c7fef6` (cortex 8935e6a).
- This supersedes dabeeac, which was never rolled.
- `helm template` renders `frontend@sha256:c054ba50…fef6`.

The roll waits on three things:
- the gate's merge to master;
- **Chris confirming `extraEgress`** in the secret values file;
- NetworkPolicy on.

Before the roll:
1. Show the values diff (`upgrade-sandbox.sh --dry-run` against `helm get values`, secret keys by
   length and hash prefix), per gov's rule.
2. Roll engine-o (`iagent-engine-o`) first, or with the rest. Fin's 15d66aad reads its
   `classify_called`.

After the roll:
- flag-on census ×3;
- grant syncs, which are Chris's.

## Item 4: after the roll

These go to cortex-ui/sessions:
- **lot 3 DELTA_SET:** census row `cost-rate-comparison-lot-3-vintage`, as alice/COST_ANALYST/[PRODUCTION_COST].
- **a live `/cases/{id}`.**
- **the PCN26-119 promote,** once 7f's pin lands.

Also owed after the roll:
- the six xml modules, once 7f's sensor is deployed;
- lane/saf gets the helm revision for the HAZ-1004 walk-census row;
- cortex-60 is told that 086a9cf0 is on master.

## Open, routed here for a decision

- **graph_host reads the wrong key.** The worker found, and did not fix, this:
  `cost_lot_costing_review._fetch` reads `payload["refusal"]`, but engine-cost writes
  `refused`/`outcome`, so a refused view renders as an answer.
  - The worker offers to take it. It needs routing.
- **SDK pin reds** (`restate_analyst` ×2, `[ia-01-roll21]`, `[files]`, `[projector]`): they close
  when ca pushes a tag. v0.9.8 is local-only.
- **7f's question** about whether review.json should carry the fingerprint inputs: undecided.
