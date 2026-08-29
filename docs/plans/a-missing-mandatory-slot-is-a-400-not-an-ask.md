---
id:         a-missing-mandatory-slot-is-a-400-not-an-ask
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/planning_agent/main.py (run_measure), src/iagent/defs/dynamic_supervisor.py (execute_subtask), agent_fleet/ontology_service/main.py (/fill_slots)
summary:    MEASURED on the live filler. Four of eleven planning verbs declare a spoken-MANDATORY slot (capability_id, project_id, process_id, tech_id). If the filler does not produce it, `func(state, **params)` raises TypeError and the caller gets `400 bad params ... missing 1 required keyword-only argument: 'project_id'` — a Python signature error shown to a person who asked a question. The right behaviour is ADR-0033's ASK. Found by a live case where the model filled BOTH enums correctly (direction=upstream, kind=phase) and dropped the mandatory id, reporting confidence 0.0 — a signal nothing currently reads. The positive half of the same finding: those four verbs could ONLY ever 400 before the filler existed, because nothing supplied a mandatory parameter at all.
---

# A missing mandatory slot is a 400, not an ask

## Measured

Live, against the deployed filler. The question was chosen to exercise two newly-declared
enums; the result is what makes it a finding.

```
question   : "what phases does I1-P1 depend on upstream"
verb       : mesh:planDependencyNeighborhood
filled     : {"direction": "upstream", "kind": "phase"}
refused    : []
confidence : 0.0
```

Both enums correct. **`project_id` — spoken-MANDATORY — was not filled**, and the id was
sitting in the question text.

The consequence, measured against the real engine:

```
params without project_id -> 400 {"detail": "bad params for plan_dependency_neighborhood:
                                   plan_dependency_neighborhood() missing 1 required
                                   keyword-only argument: 'project_id'"}
params with it            -> 200
```

**A Python signature error, rendered to a person who asked a question about phases.**

## The positive half, which is the larger one

Four of eleven verbs declare a spoken-mandatory slot:

| verb | mandatory slot |
|---|---|
| `plan_capability_path` | `capability_id` |
| `plan_dependency_neighborhood` | `project_id` |
| `plan_process_evolution` | `process_id` |
| `plan_tech_footprint` | `tech_id` |

Before the filler existed, **nothing ever supplied a spoken parameter**, so every one of these
verbs could only ever return that 400. They were unroutable in practice. The filler is what
makes them answerable at all — this finding is the residue of a capability that did not exist
last week, not a regression.

## Two gaps, and they are separable

**1. A missing mandatory slot should ASK, not 400.** ADR-0033 already rules the shape —
`route | ask | abstain`, *"ask from the phone-book"*. The declarations now carry exactly what
an ask needs: the slot's name, type, and whether it is required. Nothing reads them for that
purpose yet. The supervisor is the right place, because it holds both the declarations and
the dispatch it is about to make: if a spoken-mandatory slot is absent after filling, ask
instead of dispatching.

**2. `confidence` is discarded.** The filler returned **0.0** on this case — an accurate
self-report that it was guessing — and nothing anywhere reads the field. A confidence
threshold is the cheap version of gap (1): below it, ask. The value is already on the wire
(`FillSlotsResponse.confidence`) and already logged by the supervisor; only the decision is
missing.

> Worth stating plainly: **0.0 was the honest answer.** The model did fill two slots
> correctly and knew the result was incomplete. The defect is that the system had no way to
> act on being told.

## What is NOT claimed

**One sample.** This is an existence proof of the failure mode, not a rate. How often a
mandatory slot goes unfilled is a question for the accuracy corpus (half two of the battery),
which needs phrasings nobody designed and a human's fairness judgment on them. What is
established here is that the failure mode EXISTS, that its user-visible form is a Python
error, and that the signal needed to prevent it is already being computed and thrown away.

## Not done here

No behaviour changed. Both gaps are decisions with a blast radius — an ask interrupts a flow
that currently completes, and a confidence threshold has a number in it that should be chosen
against measured data rather than invented. Both wait on the accuracy corpus.
