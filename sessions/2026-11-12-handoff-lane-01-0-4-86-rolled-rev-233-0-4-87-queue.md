to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-11-12 (04:50Z; Wednesday 11-11 22:50 CT)
supersedes: 2026-11-10-handoff-lane-01-0-4-83-cut-no-roll-walk-tuesday.md

# 0.4.86 is rolled (revision 233), sign-in OK, lock released; the 0.4.87 queue

The older handoff still holds every carried order this one does not restate: the landmine, the
per-viewer PR's scope, ADR-0068, the mfg-trace ADR, the work packet's history. Read its NOW section
for those. This file is what changed on 11-11/11-12.

## NOW

**Sandbox runs `invincible-agent-0.4.86` (`cc4104d4`), helm revision 233,** rolled from 03:38:21Z to
03:57:16Z on 11-12.
- Chris's fresh sign-in as alice worked (ui a255a8e, bff cc4104d).
- **The roll lock was released at 04:34:35Z.**
- Post-roll report (findings 1–6, the rulings, the queue):
  `C:\Users\cnogr\AppData\Local\Temp\claude\2f211368c17b1c1f\027a271b-a42a-41e3-a9a1-a42794b57dc4\scratchpad\postroll0486.md`.

**The night, in order.**
1. 0.4.85 (#363, #361, cut #366) rolled as revision 231 and FAILED: the realm-reconcile hook's
   argument was 153 KB, over the 128 KiB per-argument limit.
2. Sandbox was rolled back to 230's values on 0.4.84 (rev 232). **RULED: 0.4.85 stays tagged and is
   never rolled.** Its release notes say so.
3. The entitlements/CPU incident: cortex-bff was CPU-throttled at 500m. Chris hand-set cpu 2.
   0.4.86 carries it in values (`cortexBff.resources.limits.cpu: "2"`).
4. #367, the realm reconcile moved pre-upgrade and its bodies into a Secret and ConfigMap, merged.
   0.4.86 = 0.4.85 + #367.
5. Values diff (37 of 244 keys) approved by Chris, then rolled.

## Waiting on others

- **Chris:**
  - the wrong-audience token check (its pass lifts OpenDDIL's person-token hold; send them one line);
  - the export test;
  - the Topaz seed run for fin's three refusal datasets (see below);
  - delete `secret/iagent-engine-da-m2m` by hand.
- **OpenDDIL:** packet placed, master
  `sessions/2026-11-12-packet-to-openddil-from-lane-01-0-4-86-is-rolled-revision-233-mint-a-new-token.md`.
  - They mint a new token and run their walk.
  - Then Lane 1 reads the door's side for `iagent-openddil`, and sends the live ActionRecord comparison
    against the 11-11 sample (contract "2", v0.9.19).
- **fin's URNs: NOT in the directory.** `ev_refusal_fixture`, `ev_refusal_missing_column` and
  `ev_refusal_wrong_type` are 404 as Topaz `dataset` objects; the control `ev_fixture` is 200.
  - Sandbox runs `datahub_topaz_sync` only inside the Topaz seed (`topazSeed.enabled: false`), which
    Chris runs by hand.
  - After his seed, re-run `finurns.py` (scratchpad `N`) in the BFF pod.
  - If they still 404, the URN form is wrong, and that is fin's.
- **perf:** packet placed: read CPU throttling per service before latency.

## 0.4.87 queue (nothing started; master is unfrozen)

1. **engine-f `/health` 500s on 0.4.86.** `agent_fleet/presentation_agent/main.py:1819`:
   - `-> Dict[str, str]` returns the int `telemetry_misses`, so response validation fails, the pod
     is unready, and engine-f still serves 0.4.84 (RS `5d998d4fcd`).
   - Fix: `-> Dict[str, Any]`.
   - Seal: a TestClient call of every engine's `/health`, asserting 200 and an int; the control is
     today's tree.
   - perf's `30d36560` brought it in; their AST census seal never calls the route.
2. **The cortex `0654bb1` (`a7b81f5a`) pin.** cortex also ships, per the architect:
   - the non-reviewer "Export as…" card rule;
   - the three display fixes, with their seals.

   The Promote page needs nothing.
3. **bob's sample grants (RULED):**
   - a new `policy/overlays/sample/capability_grants.yaml`, `granted_by: seed`, switched on by a
     sandbox values key; the shared seed stays free of sample users;
   - the grants are `can_export:part-list`, `can_export:part-list-reviewed` and `ingest:exportBatch`
     ONLY, to **the group that does the reviewing** (find which group holds the part-list review
     task);
   - same loader rules as the other overlays (add, nothing else);
   - seal: they apply only where the sample overlay is on.

   Measured tonight: alice holds all 8 `can_export:*`; bob holds none.
4. **The 0.4.87 work packet must say plainly:**
   - the export grants go to the group that does the reviewing;
   - the Promote reviewers' group must hold `ingest:exportBatch` and the work profile's
     `can_export` grant, or the button stays hidden from them.
5. **The architect's drift order** (verbatim in the transcript, 11-12 ~03:00Z):
   - **DENIED_USER_SUBS:** find its readers. Unread: remove it. Read: report the entry count (never
     the subjects) and the code path, and it becomes a policy row with a reason.
   - **ENABLE_DISPOSITION_AUTHZ:** `true` on engine-a only through hand drift; the code defaults it
     off (`review_starter.py:165`). Fix authz-off first, then put it in values with a reason, or
     remove it.
   - **MEM0_\*:** points at LiteLLM in values. List any service that calls Ollama directly.
   - **Unmanaged services:** redis, clickhouse, minio and redpanda get an inventory under `docs/`
     giving owner, version, how installed and what depends on them.
     - redis: rendered by the chart that owns the gateway broker (decide with the dag-tools owner),
       or declared external with its version.
     - clickhouse and minio: a managed install with a pinned version and an owner; propose the chart.
     - redpanda: goes with DataHub.
     - dag-tools' Q13: the mfg-trace ClickHouse version is the sandbox one; read it from the
       inventory.
   - 30 hand-added env entries on 12 workloads survive any roll. The drift sweep is
     `drift-and-cpu-history.md` in the same scratchpad as the post-roll report.
6. **The per-viewer PR comes FIRST on the train after 0.4.86** (scope in the older handoff).
7. Unfrozen, for 0.4.87 or later: #327, #357, #360, #362, #365, and saf's export-by-range.

## Open, unexplained

- The first 0.4.86 BFF pod (03:39–03:57Z) got `Connection refused` fetching the JWKS; its replacement
  fetches fine. That is a hypothesis only (BFF and Keycloak restarted together). Read it live if it
  recurs on the next roll.
- task-grant-sync's per-row log is lost to the hook delete policy. Capture hook logs live during a
  roll.

## Worktrees

- `wt\01\tag0486`: detached at the tag, with a `.venv` and the secret values copy (git-ignored).
  Rolls run from here.
- `wt\01\rel484`: its `.venv` runs the scratch scripts.
- `wt\01\realmfix`: #367's branch, merged.
