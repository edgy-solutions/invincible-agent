to: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-06 ~19:30Z
re: the overnight order, run on 7f's go-ahead (9781dde1)

# Roll #18 landed; the drop stops at `received` because doc-tools' ingress sensor is STOPPED

## 1. The roll: rev 174, fleet `06b81540`, leg 11 strict GREEN

- **Trigger, checked by identity:** doc-tools runs `sha256:1f1e1680` at helm rev 34, and
  `IAGENT_GATEWAY_URL` is present (checked by name only). The pin that landed was #74 /
  `e8893c7`, not #73.
- **Merge:** `lane/01-roll-18` @ 5dc8edbe merged to master as `06b81540` (`--no-ff`, trailer
  parsed). 7f's packet had been committed in this shared tree without a `Lane:` trailer, so the
  pre-push hook refused it. I amended the trailer in, with the tree byte-identical, and it is
  on master as `9781dde1`.
- **Gate:**
  - Full suite on `06b81540`: 50 failed vs roll #17's 49. The one new red,
    `test_relative_markdown_links_resolve`, fires only on untracked `.claude/worktrees/agent-*`
    copies inside the master tree, with 0 tracked files. At the same sha in the clean `ia-roll17`
    worktree it passes, and only the known `test_every_cited_docs_path_resolves` stays red. It is
    environmental.
  - Images: all 17 chart images at the full sha answer 200 in ghcr, and the sha with its last
    hex digit altered does not. cortex renders at `8b929940`.
- **Fire:** `upgrade-sandbox.sh --set global.imageTag=06b81540...`, REAL_EXIT 0. Chart 0.4.32,
  rev 174. 22 containers run the roll sha.
- **Leg 11:**
  - The first run was strict RED on 2 undecided windows (data-analyst, engine-e). The cause was
    the chart's own `engine-reregister` job, which patches `restartedAt` on all 13 engines ~30
    minutes after the fire. It is by design.
  - After the rollouts finished: strict GREEN, 49/49 clean, 0 Traceback.
- engine-w `KNOWLEDGE_SEARCH_VIA_MESH`: off (code default `"false"`, no chart value).

## 2. The drop: first stage not reached is `extracting`

PCN26-117 (never dropped before) went in as alice at 18:22:51Z, `content_kind=pcn`:

- Door: 200, `ingest_id sha256:b58ec2f6...`, not a duplicate.
- Status: 46 polls over 905s, every one `received`.
- **The hop's log:** Dagster GraphQL in the webserver pod reads `doc-tools ingress_user_sensor
  STOPPED`, **zero ticks**. The cortex-bff log has **zero** `POST /ingest/{id}/stage` calls.
  No tick means no run and no callback.

Capture: `cortex-ui/sessions/2026-10-06-payload-ingest-pcn26-117-rev-174.json` (hops 1-3;
cortex-ui `38ddb8d`, committed and NOT pushed; it is another repo's master).

`review` was not reached, so there was no bob act, no "which parts does PCN26-117 affect" and
no provenance_floor reading.

## 3. Owner and one-line fix: 7f's, not ours

Fix, in `doc_tools/definitions.py`, `ingress_user_sensor = S3SensorComponent(...)`:

    default_status="RUNNING",

- **Why it is stopped:** the installed component maps `"RUNNING"` to
  `DefaultSensorStatus.RUNNING`. No doc-tools sensor sets it. `ontology_sensor` and
  `sustainment_sensor` run only because someone started them by hand, and nothing in either repo
  starts a sensor. That is hand-seeded state no bootstrap reproduces.
- **Sent:** packet `c8f0f717` to 7f. It also warns that a started sensor fires every PDF already
  under `ingress-user/pdf/` at once, and answers 7f's `IAGENT_GATEWAY_URL` question:
  `iagent-cortex-bff:8090` is right.
- **Not done:** I built nothing, did not re-roll, and did not start the sensor by hand in Dagster
  (an instance write on 7f's component).

## 4. PCN23-002 (Oct 4, `sha256:0096a523...`)

- Status: still `received`, `updated_at == created_at` (2026-10-04 04:27Z), read before and
  after the roll.
- What this does not show: whether the record moves "on its own once the sensor is live". The
  sensor is not live, so that question is still open.

## 5. Census x3 on fleet 06b8154, and HAZ-1003

| fire | result | failing rows |
|---|---|---|
| 1 | 17/4 | haz-1003, deferral-risk-refusal, finance-eac-refusal, docs-under-mesh |
| 2 | 16/5 | the same four + finance-performance-indices |
| 3 | 18/3 | haz-1003, deferral-risk-refusal, docs-under-mesh |

- **Red in all three fires:**
  - `safety-haz-1003-risk-assessment`: `drawn`, row accepts `task_requested`.
  - `safety-deferral-risk-refusal`: fallback, `no_compatible_verbs`.
  - `docs-how-do-i-add-an-engine-under-mesh`: fallback, `domain_scope_excluded`, 0 pages.
- **Intermittent:**
  - `finance-eac-refusal`, 2 of 3. Fire 1: fallback, `infra_error`. Fire 2: `drawn` on
    `fin_eac_comparison` instead of `fin_eac_calculation`.
  - `finance-performance-indices`, 1 of 3: `slot_required`, ELICITATION in place of MULTI_SERIES.
- **Moved green:** `cost-rate-comparison-lot-3-vintage` passes 3/3. It was red in all three
  pre-roll fires.

HAZ-1003 seal: **PASS**, but idempotently. The turn opened nothing new, because the pending
`risk-acceptance-HAZ-1003-medium~1` (2026-10-04 02:36Z) already holds the case. One
superseded bare-key row is printed STRANDED, as before.

- **`requested_by` is blank on both rows** (read-only, inside the pod). Both predate the
  requester fix, so this is the old code's output, not a regression.
- **The fix is not yet observable live:** a fresh case cannot open while `~1` is pending, and
  resolving it is a human's live write. Yours to call.
- **Hypothesis, NOT measured:** the census row's `drawn` versus `task_requested` may be the same
  dedupe, since the task already exists. It needs a read of how the row's disposition is
  computed before anyone acts on it.

S1000D mock modules: **held** (the drop did not reach `extracted`). Nothing was posted, so 7f's
post-once hazard is untouched.

## Open, for roll #19 or for a ruling

1. 7f's one-liner, then a re-drop (or simply the backlog firing) to measure past `received`.
2. Whether to resolve the pending HAZ-1003 `~1` so a fresh case can show `requested_by`.
3. The `.claude/worktrees/` copies make a markdown-link test go red only in the master tree. A
   cleanup or a collection exclusion, whichever you prefer; I changed neither.
