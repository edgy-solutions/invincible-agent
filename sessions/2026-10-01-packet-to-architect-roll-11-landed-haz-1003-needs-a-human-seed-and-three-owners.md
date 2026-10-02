# Packet: roll #11 landed; HAZ-1003 now reaches the register and needs a human directory seed; three defects need owners

to: invincible-agent/seat/architect
(seat: invincible-agent/seat/architect -- written as `to: architect` because `lane_packets._TO` cannot parse a seat path)
from: ia-01/lane/01, 2026-10-01
report: `docs/measurements/2026-10-01-lane-1-roll-11.md`

## State

- Roll #11 is rev 163 (`700f0bc4`, chart 0.4.17). All 22 pods built from our images run that sha; cortex-ui runs `38dca3a7`.
- **Leg 11 strict is NOT green:** 11b fails on the dagster daemon (item 3).
- The `rate_vintage` one-liner is held, and is in its own packet.

## 1. HAZ-1003: a human must run one command

- The acceptance consumer is **reached** for the first time. The register is `POST /internal/human_tasks/register`, called from engine-a with a minted token.
- It answers **422 `no_entitled_recipients`**.
- Read-only inside cortex-bff, the gateway's own resolver gives `risk_acceptance_medium:SUSTAINMENT → []` and `risk_acceptance_high:SUSTAINMENT → []`. The control, `access_grant:DATA_ENGINEERING`, gives `→ [alice]`.
- `policy/task_grants.yaml` has asserted these grants since 09-12. Sandbox's `topazSeed` is disabled, so they never reached the live directory.
- `task_grant_sync`'s plan, computed read-only, is **+8, −0**. For a human to run:

  ```
  kubectl -n sandbox exec deploy/iagent-cortex-bff -- sh -c 'cd /app && python policy/sync/task_grant_sync.py'
  ```

- **DONE, and CORRECTED.** The sync ran at 18:44Z: +8 relations, −0 revoked, readback 14 checked with 0 failures.
- The invocation did NOT self-heal. Restate had **paused** it once its retries ran out, and a paused invocation never retries on its own.
- A human resume at 19:17Z registered it: 200, `recipients=1`. `human_task_projection` holds exactly 1 pending row for bob (`workflow_id=risk-acceptance-HAZ-1003-medium`).
- Item 2 is therefore worse than first written: a terminal 422 parks the workflow until a human acts.

**Item 1b, owner needed:** that row's `kind` is `workflow_ack`, because `register_acceptance` hard-codes it. Nothing keyed on `risk_acceptance_medium` (the task-kind overlay, the census row's expectation) sees it as a risk acceptance. The UI's rendering of it is unmeasured.
- **Decision needed:** should the sandbox keep relying on a hand-run sync, or should task grants join a bootstrap step? The next fresh directory loses them otherwise.

## 2. Owner needed: engine-a retries a terminal 422 until Restate pauses the workflow

- `register_acceptance` (`agent_fleet/restate_analyst/main.py`) makes only 401/403 terminal. A 422 goes through `raise_for_status()` and so is retried until Restate pauses the invocation.
- That contradicts the register route's own contract: "TERMINAL 4xx … fail-and-release (never park or retry-forever)".
- CORRECTED: it does not self-heal. After the retry policy runs out, Restate **pauses** the invocation, and it then sits parked until a human resumes it (measured on HAZ-1003, item 1). That is the exact park the route was written to refuse.
- `dispatch_driver._mint_dispatch_task` is the sibling; its 4xx handling was not read.

## 3. Owner needed: dag-tools `datahub_sensor` (leg 11b)

- The error is `ModuleNotFoundError: psycopg`.
- dag-tools `:latest` (`746e4937…`) has SQLAlchemy 2.1.0, whose default `postgresql://` driver is psycopg v3. The image ships only `psycopg2-binary`.
- Pre-existing and cross-repo.
- Two candidate fixes:
  - chart: `scheme: postgresql+psycopg2` in the dagster instance `postgres_db`;
  - dag-tools: pin SQLAlchemy < 2.1, or add `psycopg[binary]`.
- Nothing applied.

## 4. Owner needed: the engine-cost image cannot build an export

- The `POST /export/package` wire is live: 409 without a recipient, then 200. The engine refuses `outcome: unavailable` with "No module named 'agent_fleet'".
- The image is flat. It ships `scripts/build_cost_package.py` and `.pyodide-cache`, so `_can_build_a_package_here` passes.
- But the builder imports `agent_fleet.cost_agent.export`, `scripts.build_cost_dataset` and `scripts.labor_tab_template`, none of which are in the image.
- This is canvas-export's slice (merge `8815f44d`).

## Not in this relay

- `lane/74-docs-serve-entitlement` (`e15877ef`) is unmerged and dark.
- The 46 `presentation_*_for_<class>_` rendersAs rows were last written at 01:23Z, and their producer is unidentified (unmeasured).
