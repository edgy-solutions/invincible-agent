# Prime pre-registration — the two canvas-seed classes

> ## THE LAW THIS RUN TAUGHT
>
> **Every instrument that failed reported success at the resolution of "I ran", not "I did the thing."**
>
> Three of them, in one night, each hiding the next. Three green lights. **One working check:
> the graph edges themselves.** If you read nothing else here, read §WHAT WENT WRONG, and do
> not verify a registration by asking the engine about itself.

**RUN 2026-08-27/28. Executed, verified, and CORRECTED BELOW.** The canvas classes landed; the
run also exposed that this doc's own post-condition 3 was an instrument that passes a completely
unregistered engine. The corrections are inline and marked.

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

> ### ⛔ CORRECTED 2026-08-28 — `verbs: 14` IS NOT A VALID POST-CONDITION
>
> The line below said this was "the signature that matters most". **It is not a signature at
> all.** `/health`'s `verbs` counts Engine P's OWN IN-PROCESS TABLE, built from a hardcoded
> list at startup. It reads 14:
>
> * when the mesh holds **bare** endpoints (measured — it did)
> * when the engine **never re-registered at all** (measured — it had not)
> * when `reregister` never ran (measured — the job was never created)
>
> **It measures the engine's opinion of itself, not the mesh's record of it.** It would
> green-light exactly the failure it was chosen to detect.
>
> **Use this instead — the graph's verb edges, which are the actual record:**
>
> ```bash
> kubectl --context edge exec -n sandbox deploy/iagent-engine-e -- python -c "
> import os
> from neo4j import GraphDatabase
> drv = GraphDatabase.driver(os.environ.get('NEO4J_URI','bolt://iagent-neo4j:7687'),
>                            auth=(os.environ.get('NEO4J_USER','neo4j'), os.environ['NEO4J_PASSWORD']))
> q='''MATCH ()-[e]->() WHERE e.endpoint_url IS NOT NULL AND e.endpoint_url CONTAINS 'iagent-'
> RETURN DISTINCT split(split(e.endpoint_url,'//')[1],'/')[0] AS host, count(*) AS edges ORDER BY host'''
> with drv.session() as s:
>     for r in s.run(q): print(' ', r['host'], 'edges=', r['edges'])
> drv.close()"
> ```
>
> Engine P must show **14 edges at the FQDN host** (`iagent-engine-p.<ns>.svc.cluster.local:8095`).
> A bare host means it registered pre-fix; a missing host means it did not register.
>
> The credentials are the POD'S OWN — read from its env by the code it runs. Do not fetch the
> secret yourself.

**The atomic-rejection concern is still real** — Contract D refuses a batch whole, so a partial
verb set is the shape to watch. Just measure it in the GRAPH, not at `/health`.

## The run

```bash
helm upgrade iagent ./helm/invincible-agent \
  --namespace sandbox \
  --reuse-values \
  --set primeSubstrate.enabled=true \
  --set primeSubstrate.wipe=false
```

> ### ⏱ USE `--timeout 90m`. NOT 40m — AND 40m WAS THIS PLAYBOOK'S OWN TRAP
>
> **CORRECTED 2026-08-29, and the correction is more instructive than the number.** This
> section said `--timeout 40m` while the paragraph directly beneath it said **the job took 43
> minutes**. A recommendation that contradicts the measurement printed beside it, and it
> survived because nobody re-read the paragraph — including me, who wrote both halves.
>
> The next prime took **44 minutes** over 17 ingests. `40m` would have cut the hook chain
> again, for the second time, from advice written to prevent exactly that.
>
> **Under-waiting splits the substrate; over-waiting costs nothing.** Helm timing out is benign
> for the prime itself — the Kubernetes Job keeps running and finishes — but it cuts the hook
> chain, so `reregister(20)` never fires: no re-registration, engines stuck at their old
> counts, and helm reporting `failed` while the Job quietly succeeds. Everything looks healthy
> from outside.
>
> Dagster's `QueuedRunCoordinator` is capped at **2 concurrent runs** and the prime launches
> **16-17 ingest runs**, so ~25-45 min is the floor, not the tail. 90m is slack, deliberately.
>
> Helm timing out is BENIGN for the prime itself — the Kubernetes Job keeps running and finishes
> — but it **cuts the hook chain**, so `reregister(20)` never fires and the release is left
> `failed`. That is what happened.
>
> ### 📡 READ THE PRODUCTION CALL SITE BEFORE TRUSTING ANY PROBE
>
> **Match the payload field for field — especially scoping and auth fields, whose absence
> changes WHICH answer you get rather than WHETHER you get one.**
>
> Measured 2026-08-29. A sweep of the stable-phrasing corpus posted `entitled_domains` to
> `/resolve`. `ResolveRequest` has no such field, so it was ignored and `domain` fell back to
> its default `"MAINTENANCE"` — scoping the candidate pool to the maintenance ontology. Every
> planning phrasing then resolved to an MRO/IOF class, **22 of 22 "MOVED"**, at varied
> confidences from 0.10 to 0.86.
>
> That is exactly the shape of the post-prime subject drift the sweep existed to find, so it
> **carried its own corroboration** and would have been reported as *"the entire planning demo
> corpus broke post-prime."* Corrected payload: 22 of 22 HOLD at 0.95–0.99.
>
> **A PLAUSIBLE RESULT HAS NO TELL.** The other two instrument failures that night announced
> themselves — a uniform `None`/`0.00`, and a DBMS `property key does not exist` warning. This
> one produced varied names and varied numbers, and staring at them would never have revealed
> it. The only thing that caught it was diffing the harness's request against
> `dynamic_supervisor.py`'s actual `/resolve` payload.
>
> **And its sibling:** measure the store the CONSUMER reads. The same night, `frontend_id` and
> archetype counts were read from Neo4j because the claim said "edges"; the menu source reads
> Weaviate, where every row carries both. Wrong store, clean numbers, wrong conclusion.

> ### 🔎 A BY-NAME CHECK MUST ASSERT THE NAMES ARE NON-NULL
>
> **Measured on this run**, and it is the by-count defect wearing a by-name coat. A
> verification query used `e.verb` and returned **count = 8 with eight `None`s**: the property
> does not exist — the verb is the RELATIONSHIP TYPE, `type(r)`, not a property on it.
>
> The count was RIGHT, so the check read as passing. It was a by-count check with blank names,
> which is precisely the thing the by-name rule exists to replace.
>
> **The assertion shape:** returning rows is not the claim. Assert the names came back
> non-null, and compare them to an expected set:
>
> ```python
> rows  = list(session.run("MATCH ()-[r]->() WHERE ... RETURN r.iri AS iri, type(r) AS rel"))
> named = [x for x in rows if x["iri"]]
> assert len(named) == len(rows), "a row came back with a NULL name — by-count in disguise"
> assert {x["iri"] for x in named} == EXPECTED
> ```
>
> A check that cannot fail on a wrong property name is not checking the property.

> **Fast path when the ontology is already ingested and you only need `reregister`:**
> `--set primeSubstrate.triggerIngest=false`. The prime job then completes in ~40 SECONDS and
> the reregister hook still fires. Measured.

> ### ⚠️ `--reuse-values` MAKES A CHART-DEFAULT DELETION INERT — helm semantics, not a bug
>
> `--reuse-values` reuses the last release's **MERGED** values (chart defaults + overrides as
> they were THEN) as the base for the new render. So a key you DELETE from `values.yaml` is
> carried forward from the previous release and re-applied.
>
> **Measured cost:** a fix removing three shadowing `ENGINE_*_PUBLIC_URL` literals was
> committed, built and deployed **three times with zero effect**. The ConfigMap showed the new
> FQDN; the pod env showed the old bare name; every signal said the fix had landed.
>
> **If your change DELETES a chart default, `--reuse-values` cannot deliver it.** Either drop
> `--reuse-values` and re-supply the values files, or null the key explicitly:
>
> ```
> --set enginePlanning.env.ENGINE_P_PUBLIC_URL=null
> ```
>
> Null the KEY, never the block — `engineE`/`engineW` carry other env (MEM0_*) that nulling
> `engineE.env` would destroy.

> ### ⚠️ `primeSubstrate.enabled=false` DOES NOT "SKIP THE PRIME AND KEEP THE CHAIN"
>
> The reregister hook renders under
> `{{ if and .Values.primeSubstrate.enabled .Values.primeSubstrate.reregisterEngines.enabled }}`.
> Turning the prime off removes **the tree the hook hangs from**. Helm then exits **0 having
> done nothing** — success at the resolution of "I ran".
>
> To fire `reregister` you need `primeSubstrate.enabled=TRUE` with `triggerIngest=false`.

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

## WHAT WENT WRONG — three instruments, three green lights, one working check

Recorded because the next runner will meet all three.

| # | instrument | said | truth |
|---|---|---|---|
| 1 | `/health` `verbs: 14` | registered | in-process table; engine had not re-registered |
| 2 | `--reuse-values` + committed fix | deployed | chart-default deletion carried forward; fix inert |
| 3 | `--set primeSubstrate.enabled=false` | exit 0 | removed the hook's own tree; did nothing |

**The one check that caught anything twice: THE POD NAME CHANGING.** `values.yaml`'s
`reregisterEngines` comment records the 2026-08-22 run where *"every hook reported success; the
only visible evidence was the pod name not changing"* — and it caught this again on 2026-08-27.
**Read that comment before running.** It is the shortest true thing written about this hook.

**Always check the pod name across a reregister**, and verify registration in the GRAPH.

## B4a GATE — before ANY restart

`reregister` restarts the engines it covers, and `PlanStore` is in-memory: a restart destroys
every scenario **silently**. Verify empty first — `0 scenarios, baseline v0` — because "should be
empty" and "is empty" are different claims:

```bash
kubectl --context edge exec -n sandbox deploy/iagent-engine-p -- python -c \
"import urllib.request,json; print(json.loads(urllib.request.urlopen('http://localhost:8095/scenario').read()))"
```

## Residue after the 2026-08-27/28 run — named, not left

| host in graph | edges | why it is not a defect |
|---|---|---|
| `engine-a:8081` (bare) | 13 | exempted stale-image pin, USER-SUPPLIED in values-sandbox; `--reuse-values` preserves it by design |
| `engine-o:8084` (bare) | 1 | deliberately excluded from `reregisterEngines` — registry CONSUMER |
| `engine-e:8086`, `engine-w:8088` (bare) | 1 each | one stale edge apiece; off the planning path. Findable, not urgent |
| `data-analyst:8089` (bare) | 2 | **SELF-HEALS** — DA registers `analyzeDataset` on startup, so its next natural restart fixes these. Schedule no work for it |
| `restate:8080` | 2 | not an engine |

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
