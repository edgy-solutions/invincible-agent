---
id:         helm-release-stuck-pending-upgrade-97
status:     blocked-on-human
owner:      human
blocked-on: A CHOICE BETWEEN TWO RECOVERIES, both with real costs, on a shared cluster. (a) `helm rollback iagent 96` unsticks the lock but revision 96's manifest predates engine-cost, so it DELETES that Deployment/Service and runs the chart's hook chain again (~51m prime); a follow-up upgrade then runs it a third time. (b) Surgery on the helm release Secret to mark 97 failed/deployed — faster, no re-prime, but it is hand-editing helm's own bookkeeping and should be somebody's deliberate decision rather than a lane's. The DEPLOYED STATE IS CORRECT AND VERIFIED either way, so this is not urgent — it is a blocker for the next `helm upgrade`, not an outage.
closed-by:
repo:       invincible-agent
code-site:  sandbox release `iagent` revision 97 (chart invincible-agent-0.3.55)
summary:    THE SANDBOX RELEASE IS STUCK AT pending-upgrade AND THE NEXT `helm upgrade` WILL BE REFUSED — "another operation (install/upgrade/rollback) is in progress". CAUSED BY THIS LANE 2026-09-02: the upgrade was given a 600-second timeout against a prime whose measured runtime is 51 minutes, so the helm CLIENT was killed mid-hook while the hooks completed in-cluster. That is runbook §10 row 13 exactly, committed by the lane that had just read it. THE LOCK IS STALE, not an active operation — verified, no jobs running. THE DEPLOYED RESOURCES ARE CORRECT: engine-cost Running 1/1, six verbs registered and verified by name in the graph, prime complete 18 ok / 0 failed. Only helm's bookkeeping is wrong. A SECOND CONSEQUENCE, ALREADY REPAIRED: the client died before creating the post-prime reregister hook, so engine-cost held its failed boot-time registration until an explicit `kubectl rollout restart`.
---

# The sandbox helm release is stuck at `pending-upgrade` (revision 97)

**Caused by this lane, 2026-09-02.** Filed rather than fixed because both recoveries have
real costs and one of them deletes a working engine.

## What happened

```
95  superseded      invincible-agent-0.3.52   Upgrade complete
96  deployed        invincible-agent-0.3.53   Upgrade complete
97  pending-upgrade invincible-agent-0.3.55   Preparing upgrade   <-- stuck
```

`scripts/upgrade-sandbox.sh` was run under a **600-second** timeout. The chart's hook chain
includes `iagent-prime-substrate`, whose **measured runtime is 51 minutes**. The helm client
was killed at ten minutes; the hooks carried on in-cluster and completed correctly.

**This is runbook §10 row 13, walked end to end by the lane that had just read it**: *a
recommendation that contradicts the measurement printed beside it survives because nobody
re-reads the paragraph.* The dispatch for this work said `--timeout 90m`. The command that ran
said 600s.

## What is and is not broken

**NOT broken — verified:**

- `iagent-prime-substrate` Complete, **18 ok / 0 failed / 0 unfinished**.
- `engine-cost` Running 1/1, `/health` ok, six verbs, nine lots.
- **Six verb edges in the graph by name**, non-null, correct subject and output per verb, at
  the FQDN endpoint. Eleven `cost:` classes by name. `PRODUCTION_COST` present.
- Neighbours untouched: engine-p 16 verbs, engine-fin 8.

**Broken — bookkeeping only:**

- The next `helm upgrade` is **refused**: `Error: UPGRADE FAILED: another operation
  (install/upgrade/rollback) is in progress`. Reproduced.
- **The lock is STALE, not live** — checked: no jobs running in the namespace.

## The second consequence, already repaired

The client died **before creating the post-prime reregister hook**, so the hook that restarts
engines after a prime never existed. `engine-cost` had failed its boot-time registration
(Keycloak was not yet reachable — the known boot-order race) and, with no hook to repair it,
held six `UNREGISTERED` alarms. Repaired by an explicit `kubectl rollout restart`, after which
all six registrations logged OK and were verified in the graph.

**Worth noting for anyone reading the alarm history: those six errors are expected on a fresh
upgrade and are NOT a defect in the engine.** The alarm was loud and named, which is the
fleet's design working.

## The two recoveries

| | what it does | cost |
|---|---|---|
| **(a) `helm rollback iagent 96`** | unsticks the lock by rolling back | **Revision 96 predates engine-cost, so its resources are DELETED.** Runs the chart's hook chain (another ~51m prime); a follow-up upgrade runs it a third time. Ends clean, costs ~2 hours and temporarily removes a working, verified engine |
| **(b) patch the release Secret** to mark 97 `failed` or `deployed` | unsticks without re-priming | Hand-editing helm's own bookkeeping. Fast and low-churn, but it is not a lane's call to make on a shared cluster |

**Not urgent.** Nothing is down and no user path is affected — this blocks the *next* upgrade,
not the current system.

## The lesson, for the runbook rather than for this item

§10 row 13 already says the timeout must clear the measured runtime. What this instance adds
is **what an under-set timeout costs beyond the wait**: the hooks that run *after* the
long one are never created at all. The prime completed and looked fine; the reregister hook
simply did not exist, and the only evidence was an engine whose pod age never changed —
**the same tell Engine P's omission produced.** An under-set timeout is not "waiting less"; it
is silently dropping the tail of the hook chain.

**And one instrument note from the recovery attempt**: the retry was run as
`helm ... | grep ...; echo "EXIT=$?"`, which captured **grep's** status, not helm's, and
printed `EXIT=0` over a failed upgrade. The failure was visible only in the piped output.
`$?` after a pipeline is the last command's.
