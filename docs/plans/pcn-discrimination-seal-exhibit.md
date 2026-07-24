# PCN can_act discrimination seal — LIVE on the rails (exhibit)

Ran 2026-07-24 on sandbox `edge`. Proves the reconciled `can_act` (`task_audience`, NOT the retired
bespoke `disposition_item`) discriminates correctly — AND that config **arrived by the deployment
MECHANISM** (the real `task_grant_sync.py` from the product image: validate → reconcile → readback →
prune), not hand-written Topaz relations. So it proves the pcn wiring AND re-proves work's rails as
consumed by a new caller.

## Mechanism (not hand-surgery)
- Sandbox policy repo (`C:\tmp\iagent-policy-sandbox`, work's 7-file shape, sandbox content) — the grant
  is one `task_grants.yaml` audience entry `pcn_disposition:SUSTAINMENT`, subjects in sandbox's **email**
  format (observed from a live JWT: sandbox authz subject = `email`; work = employee-id — the banked
  identity divergence).
- Ran the ACTUAL syncs in the cortex-bff pod (which carries `/app/policy/sync/*`), `TOPAZ_DIRECTORY_URL=
  topaz-svc:9393`. `task_grant_sync.py` owns `task_audience actor` relations: adds asserted, PRUNES
  unasserted (removal=revoke), readback-gates (each grant resolves `can_act` TRUE).
- The check is the same Topaz DIRECTORY check `can_act_via_topaz` uses (`/api/v3/directory/check`,
  `task_audience`/`can_act`).

## Evidence — FOUR legs + revocation, all via the mechanism

| leg | check | result |
|---|---|---|
| **gate (bonus)** | `validate_policy.py` on an unbacked default cell (bob) | **REFUSED, exit 2** — "default cell not in group grants; nothing applied" (the gate bites) |
| **leg-0 deny-before-grant** | alice `can_act pcn_disposition:SUSTAINMENT` BEFORE any grant | **false** (object not found → deny) |
| **leg-1 entitled** | alice, after `task_grant_sync` (readback `checked=1 failures=0`) | **true** |
| **leg-2 absent** | bob (a valid non-reviewer) `can_act pcn_disposition:SUSTAINMENT` | **false** |
| **leg-3 wrong-compartment** | bob granted `pcn_disposition:AVIATION` only → checked on SUSTAINMENT | **false** (bob→AVIATION **true**, bob→SUSTAINMENT **false** — the COMPARTMENT KEY discriminates) |
| **revocation-by-removal** | remove AVIATION entry → re-sync (`-1 revoked`) → bob `can_act AVIATION` | **false** (the removal-sync took — the one mechanism nothing had exercised); alice→SUSTAINMENT still **true** |

Leg-3 is the point: bob is an actor of *a* `pcn_disposition` audience yet denied SUSTAINMENT — the key
does the work; if it were cosmetic bob would leak across compartments. And the sync's own readback is the
positive control (leg-1) — reference-independent, the same gate the seed runs.

## Final state (clean)
alice granted `pcn_disposition:SUSTAINMENT` (persists — the demo entitlement); AVIATION fixture revoked
via removal-sync. `bob` exists as a non-reviewer. The sandbox policy repo (`e0f6ee9`) reflects the clean
state; the AVIATION entry lives only in this exhibit's history, not the repo (fixture, not residue).

## Remaining to make it a standing loop (not blocking — the seal is proven)
The syncs were run manually in-pod (the mechanism). To make it CONTINUOUS: host the sandbox repo on git,
create the `iagent-policy-repo` secret (a PAT), and `helm upgrade` sandbox with `deploy/values-sandbox.yaml`
(`topazSeed.enabled: true`) — then the CronJob reconciles on every tick. That's infra wiring (needs the
git host + PAT + the sandbox helm release/base-values), distinct from the mechanism proof, which is done.
NB `topaz_sync.py` (personas/cells) needs a `personas.yaml` source in the dir or a flag — irrelevant to
`can_act`/`task_audience`, but resolve it before enabling the full seed.
