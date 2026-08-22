---
id:         registration-boot-order-race
status:     open
owner:      agent
blocked-on: repair 3 (the registrar discrimination) LANDED in fbf7307. Repair 1 is still owed and unanswered — WHICH of the three ways the re-register hook failed to fire at work. Until that read is done, a deploy still depends on a hook nobody has verified runs.
closed-by:
code-site:  agent_fleet/mesh_registrar/main.py:238
repo:       invincible-agent
summary:    An engine that boots before the ontology ingest lands gets a 422 Contract D rejection and NEVER retries — the ruling says 422 is permanent, and it is right for a real contract violation and wrong for "the graph is not populated yet". Witnessed at work 2026-08-14; recovery was a hand restart. The registrar is the only party that can tell the two apart.
---

# A 422 at boot is two different facts wearing one status code

**Witnessed on the work cluster 2026-08-14.** Engine A started, attempted its ten
registrations against an empty class graph, took ten Contract D rejections, and then served
traffic unregistered until a human restarted the pod ~24 minutes later. Nine of ten verbs
landed on the restart, `mesh:lookupOwnership` among them. Reported log stamps put the failed
registrations at 02:21:37 and the `ingest_ontology_job` completion at 02:21:56 — nineteen
seconds apart, in the wrong order.

Nothing here is a mystery, and that is the point: the chart PREDICTED this state in prose
(`helm/invincible-agent/values.yaml:900-919` — *"a perfect class graph with ZERO verbs →
routing silently degrades to the generalist"*), shipped a hook to sequence around it, and the
hook did not save the deploy.

## The ordering constraint, and who the actors actually are

    ingest_ontology_job (Dagster)  ──populates──>  :OntologyClass nodes in Neo4j
                                                          │
                                                          │ MUST complete first
                                                          ▼
    engine boot ──POST manifest──> mesh-registrar ──Contract D check──> verb edge

`doc-tools` is not the registrant, and the sequencing is not about it. The ingest populates
the TTL-owned half (classes); engine self-registration writes the runtime-owned half (verb
edges); `agent_fleet/mesh_registrar/v2_substrate.py:82-84` `MATCH`es both endpoint classes
rather than `MERGE`ing them, so an edge write against an unpopulated graph cannot succeed.
That MATCH-not-MERGE is CORRECT — the registrar must not invent ontology classes — and it is
what makes the ordering load-bearing rather than incidental.

## Why the engine cannot heal itself, by design

`iagent-mesh-sdk/iagent_mesh/registration_transport.py:83-85` states the ruling
(ADR-0006 addendum):

> * `422` -> PERMANENT Contract D rejection. Return immediately; the ontology must be fixed
>   and retrying cannot help, so retrying would only delay the alarm.
> * `5xx` -> retry-safe (the saga compensated, so the substrate is clean). Bounded
>   exponential backoff.

The engine did exactly what it was told. It announced `UNREGISTERED` — the named alarm fired,
loudly, per verb — and stopped. **The alarm worked; the recovery did not exist.**

## The finding: 422 conflates two facts with opposite repairs

| what is true | is retrying useful? | today's status |
|---|---|---|
| the class graph is not populated **yet** (boot race) | **YES** — it becomes true on its own | 422 permanent ❌ |
| these classes will **never** exist (missing TTL in the manifest) | no — a human must fix the ontology | 422 permanent ✅ |

Both arrive as `missing: [...]`. The engine cannot distinguish them: from inside a single
rejection, "the graph is empty" and "my classes are absent from a populated graph" look
identical. So the ruling had to choose one, and it chose the safe-sounding one — which
converts a self-healing transient into a permanent outage that only a human notices.

We have a live instance of EACH, which is what makes the pair legible rather than theoretical:

- **Transient:** the nine catalog verbs, fixed by a restart against a populated graph — and
  engine-W's `mfg#WorkInstruction` too. That one LOOKED like a missing TTL and is not:
  `setup/ontologies/mfg_extension.ttl:30` declares it under the matching
  `http://edgy-solutions.com/ontology/mfg#` namespace, and the file is in the prime manifest.
  It was simply not ingested yet when engine-W registered. Same race, same repair.
- **Permanent:** `engine_a_propose_disposition` needs `mesh#DispositionReview`, and no TTL in
  the repo declared that class — not a manifest gap, a DECLARATION gap. It existed only
  because `scripts/seed_sandbox_predicates.py:243-244` MERGEs (not MATCHes) its endpoint
  classes into being as a side effect of seeding the predicate, so sandbox had the node and
  every fresh cluster did not. A restart cannot conjure a class no source declares. The input
  side was never implicated: `pcn:SustainmentNotice` is properly declared in
  `pcn_extension.ttl:16`. **Fixed 2026-08-14** by declaring `mesh:DispositionReview` in
  `setup/ontologies/mesh_system.ttl` (22 classes → 23), which is where its eleven sibling
  output classes already live.

## Repairs — three, and the third is the one to build

1. **Make the hook reliable.** Verify `primeSubstrate.reregisterEngines` actually runs; deploy
   with `--timeout 20m`. Necessary regardless, but it only SEQUENCES around the race — the
   ordering dependency survives, and any path that boots an engine outside the hook (a pod
   eviction, an HPA scale-up, a node drain) reopens it.
2. **Make the engine retry 422 with backoff.** Removes the ordering dependency, but the engine
   must then guess which of the two facts it is holding — and `DispositionReview` is the case
   that proves it cannot. It would retry forever against an ontology gap, converting a correct
   permanent alarm into a silent infinite loop. This is the option to REJECT.
3. **Discriminate at the registrar** — where both halves are visible. `_contract_d_check`
   (`agent_fleet/mesh_registrar/main.py:238-258`) asks only *"do these two URIs exist?"*. One
   more question — *"is the class graph populated at all?"* — separates the cases at the only
   point that can see both:

   - graph empty / the domain's classes absent → **the substrate is not ready** → return
     **5xx**, which the SDK's existing ladder ALREADY retries with bounded backoff.
   - graph populated, these URIs absent → **422**, unchanged, correct, still a named alarm.

   No new retry logic anywhere. No guessing on the engine side. The ruling stays intact for
   the case it was written for, and the boot race stops being a race.

   **BUILT 2026-08-14** — `_contract_d_check` now returns `substrate_ready` + `sentinel`, and
   `/v1/register` returns **503 `deferred`** when the substrate is not ready, **422 `rejected`**
   (unchanged) when it is. The sentinel probe runs ONLY when something is missing, so the happy
   path keeps its single query.

### "Populated" has three definitions and two of them are wrong

This is the part to defend, because the wrong answer looks simpler:

| definition | verdict |
|---|---|
| `count(:OntologyClass) > 0` | **WRONG.** True the instant the FIRST class lands, so it reports READY for the rest of the ingest. The race window narrows instead of closing, and anything registering mid-load gets a permanent 422 for a class that was seconds from existing. |
| "all expected classes present" | **Unknowable.** The registrar cannot enumerate what the manifest was supposed to produce — that set lives in `prime_databases.py` plus whatever domain TTLs a deployment adds. |
| a **sentinel** class | **RIGHT.** Presence means the ingest reached its TERMINAL state, not that it started. It is also the pattern already in use: the re-register hook waits on exactly this node for exactly this reason. |

Terminality is not provable from source, so what is PINNED instead is that the registrar's
default sentinel equals helm's `primeSubstrate.reregisterEngines.sentinelUri`. Those two answer
the same question, and a drift between them reopens the race in the window where the hook has
released the engines but the registrar does not yet call the substrate ready.

That pin was earned, not assumed. Mutation testing found the first version of it worthless: it
read the imported module's constant, which binds from an env var an earlier test had set, so
repointing the default at `mesh#Request` (an early-landing class — the `count>0` defect wearing
a different hat) left every test green. Reading the default from SOURCE catches it. Both
mutations are now caught: pre-fix-never-discriminates (3 pins fail) and non-terminal-sentinel
(1 pin fails).

**Failure mode if the sentinel never arrives** (a deployment with no idp layer): registrations
get 503, the SDK retries its bounded 5 attempts, and it ends at the same loud named
`UNREGISTERED` alarm — with a 5xx reason instead of a 422 one. Degraded to loud, never to
silent, and never an infinite loop. An empty `MESH_REGISTRAR_SUBSTRATE_SENTINEL` disables the
discrimination entirely and restores always-permanent behaviour, as an announced escape hatch.

This is the same move the codebase already makes twice: the realm-reconcile job's admin-token
failure DISCRIMINATES "no password reached this job" from "the password is wrong" because they
route to different repairs (`realm-reconcile-job.yaml:87-93`); the router separates
`domain_scope_excluded` from `no_compatible_verbs` for the same reason
(`dynamic_supervisor.py:648-661`). A status code that collapses two repairs into one is the
defect; naming the difference at the site that can see it is the fix.

## The read that closes the ordering half

Which of the three ways the hook fails to fire actually happened:

    kubectl get jobs -n <ns> | grep -i reregister      # did it render / run at all?
    kubectl logs job/<release>-engine-reregister -n <ns>

- absent → `primeSubstrate.enabled` or `reregisterEngines.enabled` is false in the work values
- present but truncated → helm's default 5m `--timeout` aborted it mid-wait (it waits up to
  900s for the sentinel)
- present and timed out on the sentinel → check `idp#Dataset` specifically exists in Neo4j;
  the sentinel is an idp class and the visible ingest in the work logs was the MESH TTL

## The counter-example is now closed, and it was worth chasing

`mesh#DispositionReview` is fixed at the source (declared in `mesh_system.ttl`), so the
permanent case no longer has a live instance. Keep it named here anyway: it is the ONLY reason
repair 2 is wrong. Without a case where the classes genuinely never arrive, "just retry the
422" looks obviously correct, and the next person will propose it.

It also lands a third instance of `[[bootstrap-state-debt]]` in a single week, and the sharpest
one yet — the others were state a script CREATED that the pipeline should have; this was a
class that existed in the running sandbox and in NO source at all, kept alive purely as a side
effect of a hand-run seeder's `MERGE`. The registrar's MATCH-not-MERGE is what made it
visible: an inventing registrar would have papered over a declaration gap forever.

**The sweep is done, and it is clean.** Because the seeder MERGEs endpoint classes for EVERY
predicate it seeds, any other verb whose class is declared only there carried the same latent
defect. Checked mechanically — all 10 distinct `input_uri`/`output_uri` values in
`scripts/seed_sandbox_predicates.py`, resolved through the script's own `_MESH`/`_IDP` prefix
constants, against the 56 `owl:Class` declarations across the 10 TTLs in `prime_databases.py`'s
manifest. With `DispositionReview` added: **0 undeclared**. `mesh:DispositionReview` was the
last one, so no further permanent-422 is queued for the next fresh cluster from this source.

(Method note, because a sweep is only as good as its resolver: a first pass reported
`mesh#Dataset` missing via `engine_da_data_analyst.input_uri`. That was the checking script
folding `_IDP + "Dataset"` with a hardcoded `mesh#` prefix — the seeder is correct and matches
`data_analyst/main.py:109`. Reading the prefix constants instead of assuming them is what
turned a false positive into the clean result above.)

---

## Sandbox witness, 2026-08-22 — the hook runs, BOTH arms, and it is NOT repair 1

Added by the planning-lane agent. **Scoped to SANDBOX (`edge`), not work.** Repair 1 asks which
of three ways the re-register hook failed to fire *at work*; the work cluster is out of reach
under the fence's clause 3, so nothing below answers that. What it does supply is the first
live characterisation of the hook's behaviour anywhere.

**Arm 1 — it REFUSES on a partial graph.** A helm-driven prime launched 15 ontology ingests;
dagster's `max_concurrent_runs` is 2, so five had not been reached when
`primeSubstrate.ingestTimeout` (1800s) expired. The prime printed
`Ingest: 10 ok, 0 failed, 5 unfinished` and then:

> `[ERROR] ontology ingest did not complete cleanly; refusing to report success. Downstream
> reregistration would run against a partial class graph.`

`reregister` never ran. No engine restarted against classes that did not exist. Under the
pre-`9e31ae8` behaviour this exact run reports "Prime complete" at the `[LAUNCHED]` lines
(~47s) and reproduces the 2026-08-21 zero-`rendersAs` defect verbatim.
(See [`prime-ingest-timeout-shorter-than-its-own-queue`](prime-ingest-timeout-shorter-than-its-own-queue.md)
— the timeout is ~two thirds of the queue it waits on; zero ingests ever actually failed.)

**Arm 2 — it OPENS on a full graph.** Once the queue drained on its own (all five late ingests
succeeded untouched), the reregister job was run standalone:

```
[ready] all 2 sentinels present
[restart] iagent-engine-a: OK      [restart] iagent-engine-w: OK
[restart] iagent-engine-d: OK      [restart] iagent-engine-f: OK
[restart] iagent-engine-e: OK      [restart] iagent-data-analyst: OK
```

No wait, six restarts, job SUCCEEDED. The two-sentinel population from `6f7f217`
(`idp#Dataset` + `mesh#ChartWidget`) is what makes this meaningful: the second sentinel comes
from the LAST-launched ingest, so passing it means the graph really was full.

**Why both arms matter.** A guard witnessed only refusing is half-characterised — it could be
one that never opens. Days apart, against the live cluster, this one has now done both. The
manual-path habit existed because the chain used to green in 47 seconds over nothing; on
sandbox that justification is now retired *on evidence*. Work remains repair 1's question.

## Two facts for the redeploy checklist

**1. `engine-f` reports Ready BEFORE its `lifespan` registration finishes.** Its presentation
capabilities register inside `lifespan`, and the pod passes its readiness probe first. So
`kubectl rollout status` completing does NOT mean registration completed.

**2. A single read of a system with in-flight writes samples a MOMENT, not a property.**
Measured the hard way: a Weaviate read taken immediately after that rollout showed **9 rows
without `registration_complete`** and was reported as possible debris. A re-read minutes later
showed **44/44 marked**, stable across a third confirming read. Those nine rows were
written-but-not-yet-marked — *precisely* the transient B's completeness marker exists to make
distinguishable, photographed mid-act. The marker was working; the reader was hasty.

**The pattern that costs nothing and fixes it: read → settle → re-read → confirm.** Any
post-rollout assertion about registration state needs it. "44/44 marked, verified stable across
three reads" is a property; the same sentence after one read is a guess wearing a number.
