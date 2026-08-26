# The drag beat has no write path — found while looking for `set_cost`

**Date:** 2026-08-26 · **Lane:** 1 · **Status:** FINDING, deferred by fence (not built)

## What I was sent to build, and what was already there

Dispatched to add a `set_cost` op because "MoveProject doesn't move money… what's missing is
anything that changes cost within a scenario."

**`set_cost` already exists, complete, end to end.** Enumerated rather than assumed:

| piece | state |
|---|---|
| `SetCost` dataclass, in the closed `PlanOp` union | exists (`state.py`) |
| `apply_ops` arm, with new-row-vs-edit distinction | exists — and it refuses to fold a new period into a neighbouring row, "silently moving money through time" |
| unknown-project refusal | exists — `UnknownTarget`, never a silent no-op |
| wire shape (`OpRequest`) and `_to_op` parsing | exists, `op: "set_cost"` |
| `POST /scenario/{id}/op` on engine-p | exists |
| `POST /baseline/op` (the costs-persist exception) | exists, funding ops only |

The same was true of `state_version`: six of eight pieces already built. **Two dispatches in a
row whose premise was "this is greenfield" and whose reality was "this is joined wrong at one
seam."** That is worth naming as a pattern, because it changes what the work IS — enumerate
before building, or you rebuild what exists and still ship the gap.

## The actual gap, and it is larger than `set_cost`

**cortex-bff has no route that applies an op. None.** After tonight's addition it has exactly
two `/plan/` routes:

```
POST /plan/measure/{fn}      read
GET  /plan/state_version     read   (added tonight)
```

There is no `/plan/scenario`, no `/plan/…/op`, no `/plan/…/commit`. Engine P's write surface —
fork, append op, baseline op, commit ceremony, reschedule — **is not reachable from a browser.**

And on the other side, `SemanticInterpreter.tsx` renders:

```tsx
<IntervalTimeline rows={…} scope_label={…} valid_as_of={…} state_version={…} />
```

`onMoveProject` is **not passed**. So the drag beat today is: bar drags → the component's
`update-task` intercept fires → it correctly refuses the local mutation → it calls
`moveRef.current?.(…)` → **undefined** → nothing happens. And had it been wired, there would be
nowhere to send it.

Both halves are built and neither is connected. **Third instance this week of the same shape**
(axis keys, the `state_version` pair, now this), and by far the most expensive, because it is
the demo's centerpiece rather than one card.

## Why this was NOT built tonight

The fence: *"cortex-bff is the eval agent's tonight — coordinate or defer."* That lane has
**uncommitted changes in `src/iagent/gateway.py` right now** (a `/seed/portfolio_canvas` route,
present in the working tree and in no commit). Adding routes to a file another lane has open
risks committing their work-in-progress out from under them — a hazard this repo has already
been bitten by once.

So: deferred, deliberately, with the design settled so it is a mechanical morning's work.

## The shape, pre-registered

Four proxy routes, each mirroring `/plan/measure`'s pattern (502 on unreachable, refusal
preserved across the hop, no archetype named, no BFF-side scoping):

```
POST /plan/scenario                  {scenario_id, name, base}  -> fork
GET  /plan/scenarios                                            -> list
POST /plan/scenario/{id}/op          OpRequest                  -> append, returns new version
POST /plan/scenario/{id}/commit      {rationale, …}             -> the ceremony
```

**Every one is MUTATING**, so each needs an `endpoint_gating_manifest.yaml` row before it will
pass `test_every_source_route_is_declared` — which caught tonight's read-only poll route within
seconds of it landing. The gate class for a write route is a real decision, not a copy of the
read row: `/plan/measure` is justified as "plan state is portfolio read-model, entitlement-scoped
where the verb runs." **A write cannot borrow that sentence.**

## Acceptance, when it is built

1. A drag reaches engine-p and bumps the scenario's version — observable via the poll added tonight.
2. The refusal path survives the hop: an op naming an unknown project is a 400, never a 200.
3. `onMoveProject` is wired in `SemanticInterpreter` (cortex's half).
4. Baseline is unwritable from a drag — `POST /baseline/op` takes funding ops only, and the
   engine already enforces it. The BFF must not soften that into a generic passthrough.
