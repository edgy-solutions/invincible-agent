# `state_version` — the refresh loop's server half, pre-registered

**Date:** 2026-08-26 · **Lane:** 1 (engine-p + contracts) · **Status:** shapes declared before emitting

Cortex built the client half tonight against a contract that did not exist. `client.ts` says so
in as many words — *"when the server half lands the change is here and nowhere else"* — and calls:

```ts
const { data } = await api.get<{ state_version: number }>("/plan/state_version");
```

## What already existed, and what did not

The finding that shapes this packet: **most of the server half was already built.** Enumerated
rather than assumed, because the dispatch described this as greenfield:

| piece | state |
|---|---|
| `Scenario.version`, monotonic | **exists** — `state.py`, bumped in `append_op` |
| bump on every applied op | **exists** — `append_op` validates by applying, then `sc.version += 1` |
| `STORE.version_of(state_ref)` | **exists**, baseline included |
| `GET /state/{ref}/version` on engine-p | **exists** — "the cheap poll behind ADR-0042 OQ1" |
| `state_version` on the measure envelope | **exists**, and tests pin scenario `1` vs baseline `0` |
| `GET /plan/state_version` on the **gateway** | **MISSING — 404.** The whole gap. |
| `state_version` on the projected **component** | **MISSING.** Dropped at the projection seam. |

So this is not a build, it is **two joins** — and both are at seams, which is where every
defect this week has lived.

## THE SECOND GAP IS THE DANGEROUS ONE

`SemanticInterpreter.tsx` already reads `comp.state_version` and passes it to six components.
It is `undefined` for every planning card, because `_project_planning_archetype` builds the
component from a per-archetype passthrough list and `state_version` is on none of them.

That is the **same seam** that swallowed the axis keys today: the producer emits the field, the
projector does not carry it, and the component renders without it while looking correct.

## Sample payloads — declared before emitting

### 1. `GET /plan/state_version` (baseline, the default)

```json
{ "state_ref": "baseline", "state_version": 0 }
```

### 2. `GET /plan/state_version?state_ref=SC-DEMO`

```json
{ "state_ref": "SC-DEMO", "state_version": 3 }
```

**THE RESPONSE ECHOES `state_ref`, AND THAT IS NOT DECORATION.** The client's current signature
takes no argument, so it will poll `baseline` — whose version *never bumps*, because ops apply
to scenarios. A refresh loop polling baseline looks like it works and never fires. Echoing the
ref is what lets the client notice it asked about the wrong plan; without it the failure is
silent, which is the failure mode this repo keeps paying for.

> **Owed to cortex:** `fetchPlanStateVersion()` must take the `state_ref` its card was
> evaluated against. The component now carries it (below). Defaulting to baseline is correct
> ONLY for baseline-evaluated cards.

### 3. The projected component gains two keys

```json
{
  "archetype": "INTERVAL_TIMELINE",
  "source_persona": "PORTFOLIO_LEAD",
  "subject_concept": null,
  "rows": [ "...verbatim..." ],
  "group_kind": "capability",
  "scope_label": "Path to Predictive Maintenance",
  "milestones": [ "..." ],
  "state_ref": "SC-DEMO",
  "state_version": 3
}
```

`state_ref` rides ALONGSIDE `state_version` deliberately. The version alone answers "has it
moved?" only if you already know *what* moved; the pair is what makes the poll addressable.

## What is NOT claimed

`valid_as_of` is **not** added to the component. Engine P does not produce one — the artifact
carries it (`gateway.py` stamps it, `InterpretationStrip` reads `artifact.valid_as_of`), and
`comp.valid_as_of` is undefined by construction. Synthesising one in the projector would stamp
PROJECTION time onto a field whose contract says EVALUATION time, and the two differ by exactly
the interval this refresh loop exists to detect. Flagged to cortex rather than faked.

## Acceptance

1. `GET /plan/state_version` returns 200 with the shape above; unknown ref → 404, not 200-with-0.
2. Every projected planning component carries `state_ref` and `state_version`.
3. Applying an op bumps what the endpoint returns for that scenario, and leaves baseline at 0.
4. The projector carries the pair for **every** archetype in `_PLANNING_ARCHETYPES`, enumerated
   from that table — not from the ones I remembered. That mistake is 12 hours old.
