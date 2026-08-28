# Prime pre-registration — the two canvas-seed classes

**Date:** 2026-08-27 · **Lane:** 1 · **Status:** PREPARED, NOT RUN. Deliberately.

> ## ⚠️ THIS DOC IS ONE OF THREE POST-CONDITIONS, NOT THE ACCEPTANCE LIST
>
> Amended 2026-08-27, after work was folded into the same prime window that this doc predates:
> an `ingest_ontology_job` taxonomy overlay and four stale `aitool` edge re-registrations.
> **The ingest set is coherent** — the prime ingests five TTLs together and all the affected
> files ride — but a reader arriving here with a three-item checklist will find only one of
> them described below. The full list is in §THE THREE CHECKS, added at the foot.
>
> This mismatch was caught before the run, by the doc's own author reading the brief against
> the doc. It is recorded rather than silently patched, because "the prep doc no longer covers
> the run it was written for" is a failure mode with no symptom until someone is mid-verify.

Declared in `1e510ca`; the graph does not have them until a prime runs, and Contract D refuses
the binding until it does. This is the pre-registration the standing rule requires — counts and
names written down BEFORE the run, so the verification is a comparison rather than an impression.

## Why I did not just run it

The chain assigns the prime to this lane, and I am handing the execution back anyway. The
asymmetry is the reason:

* **Upside of running it tonight:** Lane 2's items 3 and 4 unblock a few hours earlier.
* **Downside if it goes wrong:** the hook chain ends in `reregister(20)`, and **Contract D
  rejects ATOMICALLY.** When `mesh#DecisionArtifact` was missing, all fourteen of Engine P's
  verbs were refused together — and the engine kept serving, healthy, while none of its verbs
  routed. That failure is invisible to `kubectl get pods` and looks exactly like a working
  cluster until someone asks a question.

Two other lanes were pushing to this repo within minutes of writing this, the demo is imminent,
and the runbook entry I wrote yesterday (B4a) argues against touching the substrate close to the
room. **A change whose failure mode is "every planning verb silently stops routing" is not one to
run unattended at 04:00 on a shared cluster.**

## Preconditions

1. **The build must contain the TTL.** The prime job runs from the `dagster-control-plane`
   image, which bakes the repo. `1e510ca` must have built and pushed — check before running:
   ```bash
   gh run list --limit 3   # the ontology commit's build must read `completed success`
   ```
2. Cluster healthy: all nodes `Ready`, no not-ready pods in `sandbox`.
3. No other lane mid-registration.

## The numbers, written down first

| measurement | before | expected after |
|---|---|---|
| `a owl:Class` in `mesh_system.ttl` (**FILE count — see below**) | **56 → 58** (already edited) | 58 |
| Engine P `/health` `verbs` | **14** | **14** — unchanged; the seed is not an Engine P verb |
| `mesh:CanvasSeedResult` in the graph | absent | present, `subClassOf mesh:Response` |
| `mesh:CanvasSeed` in the graph | absent | present, `subClassOf mesh:Archetype` |

**`verbs: 14` staying 14 is a real assertion, not a no-op.** If it drops, `reregister` refused
the batch and every planning verb went with it — that is the atomic-rejection signature, and it
is the thing to watch for.

## The run

```bash
helm upgrade iagent ./helm/invincible-agent \
  --namespace sandbox \
  --reuse-values \
  --set primeSubstrate.enabled=true \
  --set primeSubstrate.wipe=false
```

`wipe=false` is load-bearing and is the default; the wipe path clears Neo4j `OntologyClass`,
every Weaviate collection, the Jena graphs and the MinIO TTLs. **This change is additive — two
new classes — and needs none of that.** Flip `primeSubstrate.enabled` back to `false` afterwards
so a later unrelated upgrade does not re-run it.

Hook order is `prime(10) → ontologySeed(15) → reregister(20)`.

## Verify — by NAME, not by count

Settle first (the hooks run to completion before the release reports ready), then:

```bash
# 1. the classes exist, with the RIGHT PARENTS — the parent is the whole point
kubectl --context edge exec -n sandbox deploy/iagent-engine-p -- python -c \
"import urllib.request,json; \
print(json.loads(urllib.request.urlopen('http://localhost:8095/health').read()))"
```

`verbs` must still read **14**.

Then confirm both classes resolved, and that the binding registers rather than earning a
refusal — cortex re-registers its capabilities on load, so a browser reload is the trigger and
the BFF log carries the admitted/rejected split.

**A count alone is not verification.** 58 classes with `CanvasSeedResult` filed under
`mesh:Archetype` would count identically and be wrong — which is exactly the error this pair was
declared to avoid, and the one Contract D cannot see because it checks existence, not
classification.

## THE THREE CHECKS — the actual acceptance list

Added 2026-08-27. Items 2 and 3 are not this doc's original subject; they ride the same window.

### 1. The canvas-seed pair, BY NAME AND PARENT

`mesh:CanvasSeedResult` under `mesh:Response`, `mesh:CanvasSeed` under `mesh:Archetype`.
The pairing is the point and the query is above.

**DO NOT VERIFY "the graph has 58 classes."** That number is `mesh_system.ttl`'s FILE count,
re-enumerated before the edit. The prime ingests FIVE TTLs together — `idp_extension`,
`portfolio_planning_extension`, `mro`, `maintenance`, `mesh_system` — so the graph will hold
far more, and that is correct. (`values.yaml` records a previous run moving the graph's class
count 29 → 49 as the fifth file cleared.) The file count is a pre-flight check on the EDIT, not
a post-condition on the GRAPH.

### 2. `idp:Portfolio` carries `rdfs:subClassOf prov:Entity`

**The edge is already in the committed TTL** (`portfolio_planning_extension.ttl`). So if the
graph lacks it today, the graph is STALE RELATIVE TO THE FILE and the prime is exactly the fix —
no TTL edit is needed or wanted.

**If it is still missing AFTER the prime, stop.** That is not a taxonomy gap; it is an ingest
problem with that one file, and a second prime tells you nothing a first one did not.

### 3. Engine P reports `verbs: 14`, unchanged

The signature that matters most, for the reason in §The numbers: Contract D rejects ATOMICALLY.
A drop means `reregister` refused the batch and every planning verb has silently stopped routing
while the engine still answers `/health` as healthy.

### On any failure: PASTE, DO NOT RETRY

A blind second run cannot distinguish "transient" from "the thing is wrong", and it destroys the
first run's evidence — the same argument as the rollback note below.

## Rollback

The change is additive. If the binding is refused, the recovery is **not** another prime — read
the rejection reason first: `capability_admission` names the row, the archetype and the reason,
per-capability rather than per-batch, so the fix is to that row rather than a re-run.

## What is already true without the prime

* both classes declared in the TTL (`1e510ca`)
* `CANVAS_SEED` in `KNOWN_ARCHETYPES` — a declared contract must be a name the backend knows,
  bound or not
* the contract, the binding row, and the component-or-consumer category with both seals biting
  (`7457a15`, negative controls run)

So the only thing between here and a registered binding is this one command, run when someone is
watching the result.
