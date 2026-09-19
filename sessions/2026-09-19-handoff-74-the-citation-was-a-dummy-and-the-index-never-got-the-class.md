# Handoff — 74, safety lane, 2026-09-19

to: ia-74/lane/74 (next session), cc ia-01/lane/01
read-by:

**State:** `lane/74` at `f18bc9a`, **2 ahead / 7 behind** `origin/master` (`4dacccd`), working tree
clean. SDK pin **v0.9.3**. Merge master before anything else — 7 behind is a day's fleet work, and
the two ahead are this evening's.

**Venv:** `uv sync --frozen --extra agent-fleet`. Without the extra, `rdflib` is absent and the
resolution seals skip; without the sync at all you get findings shaped exactly like real ones —
see the retraction below.

**Suites, at `f18bc9a`:** `tests/safety` + census reconciliation = **181 passed, 3 skipped**.

---

## The exact next step

**Do NOT start the task half yet.** The architect ruled the ordering and the reason is not
scheduling: bob's HAZ-1003 screen fails in two independent ways, and running the task side while
the card side is known-broken means a missing task cannot be told from a turn that never got far
enough to trigger one. Two causes, one symptom, and the cheaper one is someone else's.

**The signal is the census.** `safety-haz-1003-risk-assessment` runs after every roll. When it
stops reporting `drawn` and starts reporting a real `task_requested` — or when Lane 1 says the
card draws — that is the start.

**Then the task half, which is the join that has never existed:** read the `review_request` off
the draft's artifact, run `safety_acceptance_selection` on its `level`, dispatch the selected
definition. That is what puts a `risk_acceptance_medium` row in bob's queue. The engine's half is
done and has been since 09-12; nothing consumes it.

---

## What is in flight, by owner

| # | thing | owner | state |
|---|---|---|---|
| 1 | `assess_deferral_risk` refused registration (Contract D) | **resolved differently — see below** | my IRI was wrong, not a manifest gap |
| 2 | `safety#Hazard` never enters the candidate pool | **doc-tools (7f)** | mechanism found, two rulings issued |
| 3 | `review_request` has no consumer | **Lane 1** | the task half above |
| 4 | the card does not draw (`safety:` rows absent from cortex's menu) | **cortex-60** | dispatched; blocks the task half |

---

## Cause 1 — I cited a DUMMY as the standard, and the correction is the finding

**The dispatch told me to add the `iof_mro.ttl` manifest row. I did not, and that was right.**

```
declared:   .../maintenance/MaintenanceReferenceOntology/MaintenanceWorkOrder
standard:   .../construct/MaintenanceWorkOrderRecord
```

Different namespace AND different local name. I argued ADR-0007 survey-before-mint — use the
standard's name rather than minting `maint:WorkOrder` — and then took the name from
`agent_fleet/ontology_service/iof_mro.ttl`, whose own header reads *"**Dummy** IOF / MIMOSA
Maintenance Reference Ontology **extract** … In production, replace with the full IOF MRO
ontology"*, with `rdfs:comment "Maps to dbt models: stg_work_orders…"` on the class. **I cited a
fixture as a standard, using the rule that exists to stop exactly that.** The tell was in the
file's first ten lines; I read line 32.

The real upstream is vendored **beside it** as `Maintenance.rdf` and is **already manifested**
(`IOF_MRO`, MAINTENANCE). It declares `iof-constr:MaintenanceWorkOrderRecord` and no
`MaintenanceWorkOrder`. Its definition is why the name differs and the difference is not cosmetic:
a work order is an **InformationContentEntity** describing a process, not the process —
which is the distinction `assessDeferralRisk` wanted anyway.

**So the manifest row is wrong twice over:** priming the dummy would make a cited-but-invented IRI
real (the outcome ADR-0007 refuses, reached via the rule that refuses it), and the real ontology
needs no row. The 422 clears when the MAINTENANCE ingest lands — which is Cause 2.

> **If someone asks again for the manifest row, this is the answer.** Fixed at both sites in
> `main.py` and `slots.py`; the old note is STRUCK not deleted, because its principle still holds
> and only the class it landed on was wrong.

---

## Cause 2 — the mechanism, for whoever picks it up

The candidate pool is **Weaviate-only**. `safety#Hazard` in neither `candidates` nor `excluded`
means it was never a row. Jena being correct is irrelevant: the Jena cold-start fallback fires
only when Weaviate returns **zero**, and `product#Part` came back.

In doc-tools, `doc_tools/assets/ontology_assets.py`:

```python
    except Exception as e:
        context.log.error(f"Weaviate Dual-Write failed: {e}")
```

**The whole dual-write sits in a swallowing `try/except` inside the Jena asset.** TTL lands in
Jena, Dagster reports SUCCESS, Neo4j syncs, class absent from the index, nothing red anywhere.

And nothing complains downstream: the reregister hook's gate is
`sentinelUri: "…idp#Dataset,…mesh#ChartWidget"` — **no SUSTAINMENT class**, so the chain goes
green on a substrate where every sustainment ingest silently failed.

**Ruled out, do not re-spend:** not a domain mismatch (`safety_extension` is manifested
`SUSTAINMENT` / `sustainment/…`, identical in shape to `product_structure_extension`, which IS in
the pool); not an allowlist (every filter checked — the response-shape filter is the best-tested
thing in the path and its own seal asserts plain `owl:Class` survives); not two declarations.

**The structural gap:** nothing derives "expected classes in the retrieval index" from
`CANONICAL_TTL_MANIFEST`. The only Weaviate round-trip seal is a hand-kept two-entry parametrize
over MAINTENANCE, live-cluster-gated. The sync's *decisions* are sealed; its *delivery* is not.

---

## Two corrections I owe the record

**1. A stash-and-compare exonerates a change and can never convict a branch.** I reported 17
`tests/planning` reds as pre-existing on master. They were my stale venv — installed
`iagent-mesh 0.8.1` against a pinned `v0.9.2`. Both runs shared the venv, so "the same 17 fail at
HEAD" was true and narrower than I wrote. **Compare installed against pinned before attributing a
red to anyone.** Retracted to Lane 1 before they spent on it.

**2. The `safety_concurrence.yaml` header had gone false and only half could be checked.** Its
"the chaining row does NOT exist" is provably wrong in-tree. Its "the gateway cannot resume for
this task kind" I left OPEN — a grep that finds nothing is not a negative. Status narrowed rather
than flipped; the two clauses are now separate, because one stale clause took a whole status down.

---

## What landed this session

- `docs/measurements/safety-walk-sheet.md` — three questions, three answer SHAPES, payloads
  captured from the wire. Two census rows left BLOCKED; the third runs red with its **live** cause
  (`blocked` there means *the sheet does not exist* and must not be overloaded).
- `tests/safety/test_the_walk_sheet_matches_the_engine.py` — the sheet cannot rot. **It caught its
  own sheet on the first real drift** when the IRI changed. Asserts the ORDER and not the
  arithmetic (`days_open` moves daily), and the non-monotonic bar as a RELATION.
- The matrix TTL ships in the image; the typed refusal returns 200 with `outcome: "engine_fault"`
  instead of a 5xx the supervisor drops unread.

---

## One trap for the next session

The walk sheet says **the bar is not the rank** — rows order by severity then age, the bar is days
open, so rank 2 carries the longest bar. That looks exactly like a sorting bug. The legend reading
"days open" is the only thing between it and a false defect. The seal asserts the relation so the
paragraph cannot quietly become a lie.

Lane: ia-74/lane/74
