# Typed mutations: parsed, but unconsumed

> *"A silently-dropped op is the failure where the room believes it made a change, the diff
> shows nothing, and the decision artifact records something that never applied."*
> — `agent_fleet/planning_agent/main.py`, `_to_op` docstring

**Verified 2026-08-24.** A typed mutation — *"set the Q3 capex for [project] to 500k"* — has
**no end-to-end path.** Both ends are built and tested. Two middle links are absent.

The intents are **not** questions-only, which was the expected finding. `set_cost` and
`move_project` are declared, `family: mutation`, `mutation: true`, fully slotted, with example
phrasings. The gap is narrower and more specific than "unbuilt".

## The chain, link by link

| link | status | evidence |
|---|---|---|
| `set_cost` intent declared, 4 slots (project / kind / period / amount) | **built** | `intent_catalog.yaml` |
| BAML `SetCost` class, and it IS in `RouteIntent`'s return union | **built** | `planning_qa.baml:148`, `:277` |
| `SetCost` op class, handled by `apply_ops` | **built** | `state.py:92` |
| `OpRequest` wire shape + `_to_op` translation | **built** | `main.py:195-224` |
| `POST /scenario/{id}/op`, `POST /baseline/op` | **built + tested** | `test_engine_p_routes.py:166-231` |
| `plan_diff` → `mesh:EffectSet` renders the effect | **built** | `measures.py:47` |
| **a mutation VERB registered in the mesh** | **ABSENT** | all 13 Engine P verbs are read-only `/measure/{fn}` |
| **anything converting a parsed `SetCost` into an `OpRequest` POST** | **ABSENT** | the BAML class has **zero consumers** |

## Two independent breaks, and they fail differently

**1. Mutations are not in the verb graph.** The shipped funnel (B) routes
`resolve → compat-walk → classify_predicate` over REGISTERED VERBS. No mutation verb is
registered, so **B structurally cannot reach a mutation** regardless of parse quality. This is
not a tuning gap; there is nothing to nominate.

**2. The parse is declared-but-unwired at the funnel's mouth.** `RouteIntent` returns `SetCost`
as a union member, so funnel A *can* produce a parsed mutation object — and **nothing consumes
it.** No caller builds an `OpRequest`, no caller POSTs. The shape exists, is enforced by the
agreement check, and spends union token budget on every call, for a consumer that does not
exist.

> The two ends were built by people who each correctly assumed the other end was the hard part.

## THE DECISIVE FACT — mutation slot-filling has NEVER been measured

**Zero of 51 fixture cases are `set_cost` or `move_project`.** The fixture covers 11 distinct
intents; neither mutation appears.

Every number in this project's record — 94.1% routing, 3/3 refusals, nomination-miss 0 — is
**read-only routing**. There is no evidence, at any n, that the model can fill four slots
correctly, and one of those slots is a **money amount**.

**A wrong amount is strictly worse than a dropped op.** The docstring above warns about the
silent drop; the LLM failure mode is louder and worse — the diff RENDERS, looks authoritative,
and is wrong. A demo that writes an unmeasured parse into plan state is demoing the one path
with no pre-registered number behind it.

## Ruled 2026-08-24 (demo-eve)

* **D2 is cut.** The drag becomes the mutation beat: the same `MoveProject` op via a
  deterministic gesture, **no LLM in the write path**, and the `EffectSet` diff still lands the
  "the meeting is the data entry" point.
* **No mutation verb is registered this week.** Beyond the standing fence, it is right on the
  merits: how governed WRITES route through the mesh is a design decision — `/measure`'s
  sibling? what entitlement shape? refusing which callers? — and it deserves its own ruling,
  not a demo-eve improvisation.
* **The funnel-A adapter is declined too.** It is genuinely small, but it would hang the
  script's only write beat off the retired 53–59% router while every spoken beat runs the 94%
  funnel. Architecturally dishonest and strategically backwards.
* **The room gets one sentence of roadmap**, true and verifiable: *"you saw the drag enter
  schedule data; typed mutations ride the same op pipeline — the parse and the write path both
  exist, and wiring them is scheduled."*

## Work items, with their gates

**(a) The mutation-verb design ruling** — post-demo, human-owned. How do governed writes route
through the mesh? Entitlement shape, refusal semantics, and whether a write verb belongs in the
same graph the compat-walk reads at all. **Gate: a ruling, before any registration.**

**(b) The slot-filling fixture extension** — `set_cost` / `move_project` cases WITH money
amounts, across the same phrasing-variation discipline as the existing 51.
**Gate: PRE-REGISTERED BEFORE ANY WIRING SHIPS.** When typed mutations land, they land measured
or not at all. Slot accuracy on a money field is the number that decides whether this is
demoable, and it does not exist yet.

Note this compounds with the standing Gate 2 observation: `test_planning_eval.py` asserts on
`slots_ok`, and **funnel B does not measure slots at all**. The 94.1% is the ROUTING arm. Slot
scoring is unbuilt for read-only verbs too — so item (b) is the first instance of a measurement
the gate has always required and never had.

## Related

* `docs/principles/a-fallback-without-a-counter-becomes-the-architecture.md` — the same shape
  one layer down: a thing that exists, is correct, and has no consumer or counter
