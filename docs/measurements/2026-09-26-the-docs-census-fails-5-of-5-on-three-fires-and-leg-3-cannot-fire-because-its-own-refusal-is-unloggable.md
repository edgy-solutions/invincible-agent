# Lane 1, 2026-09-26 — the docs census: 5/5 FAIL on three fires, and LEG 3 cannot fire

**Status: the census is DETERMINISTIC RED and the attribution is exact.** Three fires, byte-identical
output. The four `DATA_ENGINEER` docs rows fail for one reason, localized to one line of wiring; the
fifth row (HAZ-1003) fails for an unrelated reason that is **not** Lane 1's.

The order was: run all three fires before calling Q1's generalist-fallback routing; if it holds on
3/3, attribute to the pool leg and read its own control first. It holds 3/3, the control is read, and
the attribution below is measured against the deployed bytes rather than inherited from this lane's
own earlier write-up.

**One premise in the order is false and it matters.** The census was queued as "the pool leg live for
the first time." The leg is **deployed and inert**: `bfb33b89` is an ancestor of the deployed
`b5eeb408` (`git merge-base --is-ancestor`), its Cypher is present in the live engine's
`cypher_executed`, and it still returns zero rows on every call by construction. It rolled; it cannot
fire.

## 1. The three fires

```
scripts/walk_census.py --only docs-how-do-i-add-an-engine --only docs-what-is-an-archetype \
  --only docs-how-do-i-add-a-canvas-template --only docs-how-do-i-roll-a-service-abstains \
  --only safety-haz-1003-risk-assessment
```

| | fire 1 | fire 2 | fire 3 |
|---|---|---|---|
| result | `0 pass, 5 fail, 0 blocked` | same | same |
| output | — | **byte-identical to fire 1** (`diff`, empty) | **byte-identical to fire 1** |

`repo=79a4e757`, `fleet=MIXED(b5eeb40,c000514)` on all three. The `MIXED` is the dagster-server pin
recorded in
`docs/measurements/2026-09-26-roll-3-fired-revision-150-and-the-dagster-server-tag-is-pinned-past-global-imagetag.md`
and is **not** in any path these rows exercise.

The runner has no repeat flag, so three fires is three runs. That is the point: a single red is a
sample, and `route_status='no_match'` is exactly the shape a flaky retrieval leg would also produce.

## 2. The four docs rows — one cause

All four report the same two lines:

```
route_status='no_match'
fell back: no_compatible_verbs
```

The producer side is healthy and was checked first, so the fallback is not a registration failure:
the registrar logged `Registered … (verb=mesh:explain)`, and `parameterised_by: mesh:explain wrote
1 edge(s), removed 1 stale`. The verb is in the graph with its required-slot edge.

**Direct probe of `/find_compatible_verbs` on the live engine.** `mesh:explain` enters the pool for
**exactly two subjects** out of seven probed:

| subject | `mesh:explain` in pool | `compatibility` | leg |
|---|---|---|---|
| `mesh#Thing` | yes | `referent` | LEG 2 |
| `mesh#DocPage` | yes | `subject` | LEG 1 |
| the other five (incl. `mesh#Archetype`, `docs#DocExplanation`) | **no** | — | — |
| any subject | — | **no `universal` value appeared, for any of the seven** | **LEG 3 never fired** |

`compatibility` is the discriminator: each leg stamps its own literal (`'subject'`, `'referent'`,
`'universal'`), so the label on a returned verb *names the leg that admitted it*. Zero `universal`
labels across seven subjects is a measurement that LEG 3 contributed nothing, not an inference.

No docs question's subject is `mesh#Thing` or `mesh#DocPage`, so the pool is empty for all four and
the supervisor falls back to a generalist card. **Q4's failure is the same defect, not a second
finding:** it reports `disposition 'drawn', row accepts ['slot_required']` because the fallback draws
a card, which is indistinguishable from "failed to abstain" at this layer. Q4 will only be a real
abstain test once the pool is non-empty.

## 3. Why LEG 3 returns nothing — the exact chain, against the deployed bytes

Both files are **byte-identical to the deployed sha** (`git diff --quiet b5eeb408 --` on
`agent_fleet/ontology_service/main.py` and `agent_fleet/ontology_service/mesh_ontology.py`), so this
is the deployed behaviour and not a working-tree reading.

1. `_POOL_READ_INITIATOR = Initiator(subject="engine-o-find-compatible-verbs", kind="service")`
   (`main.py:4497`). Declared `service` **honestly** — `Initiator.kind` is
   `Literal["person","service"]`, so declaring `person` would fabricate the identity the check exists
   to prevent.
2. `_universal_referent_iris()` calls `_JENA_ONTOLOGY.construct(_POOL_READ_INITIATOR, …)`.
3. `construct` calls `initiator.require_person("construct")` first (`mesh_ontology.py:257`), and
   `require_person` **raises** `ServiceIdentityRefused` for `kind == "service"`
   (`iagent_mesh/interfaces.py:137-142`). It raises; it does not return a falsy result.
4. `_universal_referent_iris`'s `except Exception` sets `refusal_detail` and continues, so
   `confirmed == []` and **the function never raises** — as documented.
5. The route passes `universal_referents=[]`, and LEG 3's admission clause is
   `WHERE ref.uri IN $universal_referents` — which matches nothing against an empty list.

So LEG 3 contributes zero rows on **every** call, always, and will until
`/find_compatible_verbs` carries a real caller identity. Its request model is exactly
`{subject_uri, max_hops, entitled_domains}` (`main.py:4384`) — there is no caller field to thread one
through, which is why `main.py:4484-4488` flags the gap in a comment rather than filling it.

> **Superseded 2026-10-02 (`lane/74-explain-identity`).** The route now carries `user_email`, as
> `/resolve` does; `_universal_referent_iris` mints the caller as a person, and
> `_POOL_READ_INITIATOR` is only the refused fallback for a request that names nobody. The gateway's
> supervisor and direct paths both thread it. Sealed in
> `tests/routing/test_the_explain_leg_reads_as_the_caller.py`. Not yet measured live.

**The leg's own control already says all of this, and says it louder.**
`tests/routing/test_the_pool_reaches_the_universal_referent.py` (22 tests, all green, run at this
sha) contains `test_the_REAL_pool_initiator_is_refused_today`, whose docstring calls itself "THE
FINDING THIS FILE MOST WANTS SURFACED" and states the live consequence in as many words. The census
therefore **confirmed a prediction**; it did not discover a defect. This lane's own morning report
(`sessions/2026-09-26-report-to-chris-the-pool-leg-is-built-and-inert-and-roll-3-has-two-preconditions.md`)
said the same, and the value of running the census anyway is that the prediction is now measured on
the live fleet instead of read off the source.

## 4. The contradiction that had to be resolved first — a detector that could not fire

Before writing §3 as fact, one measurement contradicted it. `_universal_referent_iris` logs

```
LEG 3 universal-referent read produced nothing (%s) — pool degrades to LEGs 1+2
```

exactly when `not confirmed and refusal_detail` — i.e. **precisely the state §3 claims**. That line
appears **0 times** in engine-o's live log, across 4483 lines. If §3 were right the line should be
there, so §3 was held open until this was settled.

**It is settled: the line is unloggable in this process.** It is a bare `logging.info`, which goes to
the **root** logger. A census of every `LEVEL:name:` record in engine-o's whole log:

| logger | records | has its own stdout handler? |
|---|---|---|
| `iagent_mesh.transport_auth` | 111 | **yes** — `iagent_mesh` installs one on the package logger at INFO |
| `mesh_registration` | 1 | **yes** — via `agent_fleet/utils/uvicorn_safe_logging.py` |
| root | **0** | no |

The remaining lines are uvicorn's own (`INFO:     <ip>:<port> - …`), BAML's Rust-side writer
(`<ts> [BAML INFO] …`), and stdout prints. Engine-o's `main.py` performs exactly **one** handler
repair, on `iagent.routing.audit` with `propagate = False` (`main.py:118-125`). Every one of its nine
bare `logging.*` calls — and `iagent.slots`, which has no handler either — goes to root.

And for an **INFO** record on root, *both* possible root states drop it: with no handler,
`logging.lastResort` only emits at WARNING+; with uvicorn's configuration, root is not at INFO. So
the silence carries no information about LEG 3 either way, and the contradiction dissolves.

This is the defect `agent_fleet/utils/uvicorn_safe_logging.py` exists to prevent, and its docstring
names the cost of the last instance: a retirement trigger whose condition was
`kubectl logs | grep "VIA GATEWAY"` — "a condition that could never be observed, and therefore not a
condition at all." The new LEG 3 line is the same shape.

**A stale claim in that docstring is what made the log look safe.** It lists

```
agent_fleet/ontology_service/main.py     -> logger "ontology_service"
```

among the two engines that hand-rolled a repair. **No logger named `ontology_service` exists in that
file** (`grep -n 'getLogger('` returns `iagent.routing.audit` and `iagent.slots`, and nothing else).
The claim was presumably true when written; it reads now as an assurance that engine-o's records
reach stdout, which is false for every record except the routing-audit JSON.

### 4b. The positive control for that census, stated

Two loggers **with** the documented repair appear, and root does not, **from the same process, the
same stdout, and the same uvicorn reconfiguration.** The control shares the subject's gate and
differs in exactly what the guard decides on — whether the logger carries its own handler.

**Its limit, stated rather than left to be inferred:** this shows root records do not *appear*; it
does not fire a root record on demand and watch it vanish. The two-root-states argument above is what
closes the gap, and it is an argument from the stdlib's behaviour, not a measurement.

## 5. HAZ-1003 — a different failure, and not Lane 1's

```
FAIL  safety-haz-1003-risk-assessment  SAFETY_ENGINEER
      disposition 'drawn', row accepts ['task_requested']
```

**No `route_status` or fallback line.** The verb matched and routing worked; the walk drew a card
where the row requires a task request. That is an engine/projector finding downstream of routing —
**owner 74**, per the census row's own note that `row_in_human_tasks` is "NOT CHECKED BY THIS
RUNNER — 74 owns it". It is recorded here because it was measured here, and it is not diagnosed
here.

## 6. Two smaller things measured on the way

- **`mesh:explain` appears in the pool under two spellings** for `mesh#DocPage`: `mesh:explain` and
  `http://invincible-agent/mesh#explain`, as two rows for one verb. Unresolved; it is a
  same-verb-twice hazard for any consumer that counts or dedupes by `verb_iri`.
- **A positive control of mine failed and was not read past.** The first pool probe passed
  `entitled_domains: ["MANUFACTURING","DOCS"]` and `cost#ProductionLot` returned **0** verbs, which
  would have made the docs result look docs-specific. Re-probed with `entitled_domains: []`, the same
  subject returned **7**. The confound was the domain filter, not the pool. A failing positive
  control is a finding about the probe.

## 7. What I did not verify

- **That threading a person through `/find_compatible_verbs` makes the four rows pass.** §3 proves
  LEG 3 contributes nothing; it does **not** prove LEG 3 is the *only* thing between these questions
  and a green row. The next unknown behind it is whether `docs#DocExplanation` and friends reach
  `mesh:explain` through LEG 3 once the list is non-empty — untested, because the list cannot be made
  non-empty today.
- **Whether Jena would confirm `mesh#Thing`.** The candidate never reaches Jena: the refusal is at
  the boundary, before a query exists. So "a candidate Jena does not confirm" remains an *unexercised*
  branch of `_universal_referent_iris` on the live fleet, and the two causes of an empty list are not
  distinguished by any live measurement — only by the code path in §3.
- **Q4 as an abstain test.** It is currently a restatement of §2 and carries no independent signal.
- **The four docs rows against a non-empty pool, in any form.** No workaround was attempted;
  threading a caller identity is a design decision for a person, which is what the code comment says.

## 8. Owed, arising from this

1. **A caller identity on `/find_compatible_verbs`** — now measured as the blocker for the whole docs
   feature, not one leg of it. Design decision; not Lane 1's to invent.
2. **The LEG 3 degradation line moved onto a logger that survives uvicorn** —
   `ensure_stdout_logger` exists for this. One line, and it makes the diagnosis in §3 observable next
   time instead of derivable only from source.
3. **The stale line in `uvicorn_safe_logging.py`'s docstring** (§4) — it asserts a repair engine-o
   does not have.
4. **The two spellings of `mesh:explain`** (§6).
5. **HAZ-1003 to 74** (§5).
