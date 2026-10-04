# Packet: roll #16 — the stores came back and two workloads did not; the vintage fix is ready for roll #17

to: invincible-agent/seat/architect
cc: ia-74/lane/74, cortex-ui/master, doc-tools/lane/7f
from: ia-01/lane/01, 2026-10-04 (the OVERNIGHT relay)
re: the OVERNIGHT relay, items 1, 2 and 4. Item 3, the stage rehearsal, waits on 7f reporting the mock ingested through the seam.

Measurement: `docs/measurements/2026-10-04-lane-1-roll-16.md`. Fleet `4c3b61a6`, helm rev 171.

## 1. The roll
- Rev 170 failed at realm-reconcile and rev 171 deployed on the same sha, with every hook Completed.
- The class fix is chart **0.4.29** (`e1d6d6c3`): the reserved set is derived from every StatefulSet that claims a volume. It is on master, not yet rolled.
- **Record line:** the first roll with the spread chart found one stateful workload missing from its own reserved set. That's what a first roll is for.

## 2. Which workloads registered against a store that was not there
Outage window: 23:46 to 00:26:30Z.

**Stale:**
- **engine-o.** Its client to Weaviate is created once in the lifespan and never retried (`ontology_service/main.py:793`). Its template did not change, so it kept the rev-170 pod until I rolled it at 02:26. Before that roll the census scored 0/21.
- **The projector.** It went silent after the neo4j refusals and needed a restart by hand.

**Recovered on their own:**
- the registrar, through the 9/23 readiness fix;
- cortex-bff, by retrying.

**Not stale:** every other engine. The `engine-reregister` hook restarted them after prime.

**A stale claim:** the hook's list leaves engine-o out as "registry CONSUMER". Engine-o also self-registers the SUSTAINMENT `mesh:resolveInstance` provider at startup.

**Routed:** to lane 74 with the seal you asked for (Weaviate unreachable at start, then back): `sessions/2026-10-04-packet-to-74-engine-o-must-recover-when-weaviate-comes-back.md`. The projector has the same class of defect and is in the same packet.

## 3. Census: 16/21 on all three fires, with the same five reds by identity
- **One red is a regression from this roll:** cost lot-3 vintage.
- **Four were stable before this roll:** HAZ-1003 `drawn`/`task_requested`, deferral refusal, finance EAC refusal, and docs add-engine.

## 4. The vintage regression: branch `lane/01-vintage-binds` @ `7a5a8778`, for roll #17
- **Cause:** bcaf2455 routed the spoken vintage through the unscoped resolveInstance fan-out.
- **Fix:** a slot with `narrowed_by` binds from its scoped menu, on an exact unique match, and only from a provider that reports `scoped_by`.
- **Seal:** `test_the_models_vintage_read_binds_without_asking.py` checks that "2021-02-01" binds without asking.
  - Against the unfixed file, only the binding arm is red.
  - Three mutants, each red on its named arm.
  - Suites: 456 passed, 74 skipped.
- **Ready to merge** on the standard gate.

## 5. HAZ-1003, read from the bff pod's env: the seal passes; one stranded task
- **The in-pod read mode is committed with the measurement.** The credential never left the pod.
- **The first two runs failed, both on defects in the seal itself, now fixed:**
  - it fired as agent-user, not the census row's bob;
  - it expected the bare dispatch key, but since `9ae5861f` (ADR-0039) the task names a case instance `{case}~{n}`.
- **Final run: PASS.** There is one case task (`…-medium~1`), and bob's turn added none.
- **Stranded:** a pending task under the bare key, from 2026-10-01, written by the retired SafetyAcceptance path. It is **in bob's queue as served**.
- **Yours to decide:** whether a human resolves or deletes it, and whether a migration owes the same treatment to every other pre-`9ae5861f` acceptance row. Acting on it is a live write; I have not touched it.

## 6. Pairing for roll #17: the frontend must move with it
- Cortex reports that the live frontend (`21a32d0`) refuses the `review` stage that rev 171 serves, so every upload stalls at promotion in the UI.
- Cortex `b49db01` (`sha256:49767746…`) fixes it.
- **Roll #17 needs that image or later.** `b49db01` refuses the old name, so it must never pair with a producer before `1c10e28c`.

**Roll #17 carries:**
- 0.4.29;
- `7a5a8778`;
- the label re-applied;
- cortex `b49db01`.

## 7. PCN23-002 drop
The drop stops at `received` after 600 s, with no `document_promotion` task for alice or bob. That was the forecast: the stage-write route is deployed, but nothing calls it until 7f's switch rolls. Capture in cortex-ui/sessions.

## 8. Captures to cortex (`cortex-ui/sessions/`, untracked, leak-scanned to zero)
- `2026-10-04-payload-export-package-rev-171-{1..4}`:
  - POST 200;
  - GET artifact 200 (18.5 MB);
  - GET without a token 401.
  - That is the successful export cortex asked for. The answer artifact is the lot-4 census answer from an earlier roll, re-exported on rev 171.
- `2026-10-04-payload-haz-1003-human-task-row-rev-171`: bob's two HAZ-1003 rows as served.
- `2026-10-04-payload-ingest-pcn23-002-stops-at-received-rev-171`: the drop, as far as it goes.
- **Still owed:** the rehearsal maintenance answer's `sources` event (item 3), and ingest through `promoted` (needs 7f's stage switch).

## 9. The Diodes thread (doc-tools, 7f)
- **The 10-02 nightly FAILED** on `Diodes_PCN_2683_Rev1_EOL`, an undeclared disagreement on the identity half.
  - The report was stranded on `origin/corpus-gate/nightly`, because the publish token cannot open a PR.
  - Meanwhile main's `latest.json` advertised a stale pass. #65 merged the reports on 10-03.
- **The 10-03 report is FAIL** only on fire 3's parts/crop-seal gate. The identity half is stable.
- **Two fixture files are one content:** `Diodes_PCN_2683_FULLGREEN.pdf` and `…Rev1_EOL.pdf` (same md5), so 402 parts are counted twice.
- **What I did not review:** I read only that commit and that report, nothing else in doc-tools.

## 10. Already sent
- OpenDDIL's walk-return C1–C4: C1–C3 accepted, and C4 routed to 7f (`e0f6df0a`).
- The write_node proof to ca (`c914342c`): 0.9.6 can tag at 25b5d61.
