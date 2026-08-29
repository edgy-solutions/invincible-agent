---
id:         a-spoken-handle-can-forge-the-change-log
status:     open
owner:
blocked-on: human approval to touch engine-p (fenced for the night of 2026-08-28)
repo:       invincible-agent
code-site:  agent_fleet/planning_agent/main.py:360-361 (run_measure, plan_session_changes)
summary:    MEASURED on real bytes. `run_measure` injects route-supplied arguments into the SAME `params` dict a caller's values land in, and for `plan_session_changes` it uses `params.setdefault(...)` — so a CALLER-SUPPLIED value WINS. A spoken `ops: []` makes the change log report ZERO changes for a scenario that has one; a spoken `scenario_name` relabels the artifact anything the speaker likes. This is the DECISION-ARTIFACT verb (INV-4, "why did we move this?"), so the failure mode is forged provenance rather than a wrong number. Reachable today: cortex-bff's /plan/measure forwards `body.params` verbatim. Its two sibling injection sites use ASSIGNMENT and are safe — nobody chose the difference, it fell out of `=` vs `setdefault`. FIX IS ONE WORD, not applied: engine-p is fenced. The new carry path is already guarded (iagent_pure/slot_acceptance.py).
---

# A spoken handle can forge the change log

## Measured

Run against the real engine (`TestClient`, seeded store), scenario with exactly one op:

```
HONEST (no params)                       change_count=1  scenario_name='Probe Scenario'
SPOKEN ops=[]                            change_count=0  scenario_name='Probe Scenario'
SPOKEN scenario_name='Board-Approved…'   change_count=1  scenario_name='Board-Approved Plan'
```

A caller who names `ops` gets a change log that reports **no changes to a plan that
changed**. A caller who names `scenario_name` gets that log **filed under a different plan**.

> The first instrument I pointed at this read `len(response["rows"])` and returned **3 for
> both** the honest and the spoken call — it was counting the KEYS of the returned dict, a
> constant. Two identical values is the tell. The numbers above are from the re-probe, on
> `change_count` and `scenario_name`, which are the actual claim.

## Why this verb is the bad one to have it on

`plan_session_changes` is the change log — the verb whose own docstring says it takes ops
rather than reading a store *"so a decision artifact can be built from a recorded op list
long after the session that produced it, which is what makes INV-4's 'why did we move this?'
answerable later rather than only live."*

Purity is what makes it forgeable. Every other measure reads state the caller cannot reach;
this one is handed its evidence, and the wire is a place a caller can stand.

## Root cause — `=` versus `setdefault`, and nobody chose it

`run_measure` builds one `params` dict holding **two populations**: what the caller asked
for, and what the route resolved from the store. Three sites inject the second kind:

| site | line | how | outcome |
|---|---|---|---|
| `plan_diff` → `baseline_state` | 334 | `params[...] = STORE.resolve(vs)` | caller's value **overwritten** — safe |
| `plan_cost_curve` → `baseline_state` | 342 | `params[...] = STORE.resolve("baseline")` | **overwritten** — safe |
| `plan_schedule` → `touched_project_ids` | 351 | `params[...] = {…}` | **overwritten** — safe |
| `plan_session_changes` → `ops`, `scenario_name` | **360-361** | **`params.setdefault(...)`** | caller's value **WINS** |

Three assignments and one `setdefault`. The safety of the first three is a side effect of
statement order, not a decision — and the one that differs is the one holding the audit
trail. This is the shape worth naming: **an invariant that is enforced by accident in most
places is not enforced anywhere**, because nothing tells you when a new site breaks it.

## Reachability, today

`cortex-bff`'s `/plan/measure/{fn}` forwards `body.params` **verbatim** to the engine
(`gateway.py:1133`). So this is live behind auth right now, not a consequence of the carry.

**No production caller exists yet.** `cortex-ui` calls only `/plan/state_version`; the repo
has no other caller outside tests. That makes the window a good one — the seam is guarded
before its first consumer rather than after — and it is why this is filed rather than
hot-patched at 2am.

## The fix — one word

```python
# agent_fleet/planning_agent/main.py:360-361
-        params.setdefault("ops", list(sc.ops) if sc else [])
-        params.setdefault("scenario_name", sc.name if sc else None)
+        params["ops"] = list(sc.ops) if sc else []
+        params["scenario_name"] = sc.name if sc else None
```

Makes four injection sites agree, and makes the agreement deliberate. **NOT APPLIED**:
engine-p is fenced for the night, and this is exactly the kind of change that should be a
human's to land — see AGENTS.md clause 2.

`tests/planning/test_slot_carry.py::test_a_spoken_handle_cannot_forge_a_change_log` asserts
the forgery **as current behaviour**, with a message saying so: when the fix lands that
assertion goes red, and the test should be inverted into the seal rather than deleted.

## What is already guarded

The new carry path does **not** widen this. `iagent_pure/slot_acceptance.py` refuses any
spoken value for a slot declared `handle` or `ceremony`, and `ops` / `scenario_name` are
derived as `handle` straight from the signature. A drift seal reads `HANDLE_SLOTS` out of the
producer and fails if a route-injected argument is ever declared spoken — it was run against
two deliberately broken producers and failed on both before being trusted.

So the supervisor path is closed. The BFF path is open, because it filters nothing — it has
no declarations to filter against, which is the same missing projection
(`[[slots-are-extracted-then-dropped-at-dispatch]]`) that keeps the carry dark.

## The general shape, for the architect

Two populations sharing one dict, distinguished only by which line ran last. The type system
cannot help — `ops: list` and `window: list[str]` are both lists — which is precisely why the
declarations carry `kind`. **The durable fix is for the engine to stop merging the two
populations at all**: resolve route-supplied arguments into a separate mapping and splat it
*after* the caller's, so precedence is structural instead of positional. That is a larger
change than the one word above and should be weighed on its own.
