# Slice 4 design — answer → workflow-step seeding (the Q&A → repeatable-workflow bridge)

Implements ADR-0028 **Use-3** and ADR-0029's Slice-4 rollout — the strategic center of the
workflow arc: turn a Q&A **answer** (an SPO operation that already ran) into a workflow **step**
(an SPO tuple), so a user who asked a good question can promote it into a repeatable workflow
without re-authoring it. This is native, not a translation: **an answer IS an SPO op that ran,
and a step IS an SPO tuple** — the seed just extracts the provenance the answer already carries.

## 0. The provenance an answer already carries (nothing new to capture)

`src/iagent/answer_artifact_writer.py::AnswerArtifactBundle.routing` (composed by the gateway,
`src/iagent/gateway.py`) is the SPO record of what ran:

```
routing = {
  "about":  {"uri": <subject_uri>,  "label": ..., "confidence": ..., "instance_resolved": ...},
  "action": {"iri": <verb_iri>,     "label": ..., "owner_persona": ...},
  "handled_by": {"engine_name": ..., "endpoint_url": ...},
  "route_status": ..., "fallback": <bool>, "candidates": [...],
}
```

So the seed reads `routing.about.uri` (subject) and `routing.action.iri` (verb) directly — the
same provenance ADR-0028 Decision 2 already threads onto every answer, previously used only for
the S·P headline and the decision-map. Slice 4 gives it a second consumer.

## 1. The mapping (native)

| Answer provenance | Workflow step (`SpoOperationStep`) |
|---|---|
| `routing.about.uri` | `subject` |
| `routing.action.iri` | `verb` |
| the verb's registered output type (ADR-0030 — fixed per verb) | `expected_output` |

`expected_output` is NOT taken from the answer's `rendered_output` (that's this run's *content*);
it is the verb's **fixed output type**, looked up the same way the interview derives it
(`/find_compatible_verbs`'s `output_uri`). ADR-0030: a verb's output is a fixed type; the answer's
rendered content is a projection of it, not the type.

## 2. What is NOT seedable (fail honestly, don't fabricate a step)

An answer only seeds a step if it was a **grounded, non-fallback SPO op**:

- `routing.fallback == true` → the pipeline fell back to the generalist; there is no grounded
  `(subject, verb)` — **not seedable** (return a reason, never a fabricated step).
- `routing.about.uri` is `UNKNOWN`/empty → subject not grounded → not seedable.
- `routing.action.iri` is `UNKNOWN`/empty → verb not grounded → not seedable.

Seeding a step from a fallback answer would bake a non-routable tuple into a durable workflow —
the workflow equivalent of the optimistic-default trap. Refuse it at the seam.

## 2.1 What is also NOT seedable — WEAK PROVENANCE (the cross-seam with the recall-override guard)

Fallback/UNKNOWN is not the only degraded path. An answer can be **grounded and plausible yet
weak**: engine-o's recall-override guard (`agent_fleet/ontology_service/recall_guard.py`) fires
when the classifier overrode a *strong* vector-recall winner with **no phone-book confirmation**
— a confidently-wrong classification that reads like a normal one (the motivating case: "tables
used in the `<named>` dashboard" resolving subject=`Table` over `Dashboard`). The guard flags it
(`provenance.recall_override=True`) and caps the reported confidence at **0.50**.

**Provenance includes HOW the answer resolved, and weak provenance shouldn't seed.** A wrong
answer is transient — the user sees it and moves on. A wrong answer *seeded into a repeatable
workflow* is the error made **durable and re-executable**: the one place a silently-degraded
answer can do compounding damage. So the seed refuses the weak path too. The rule falls straight
out of the slice's own principle ("an answer is provenance, not authority") — it just reads one
more field of the provenance.

**Two discriminators, deliberately both — and one is not yet wired (verified, not assumed):**

- `routing.about.recall_override` — the PRECISE flag. **But it is currently DISCARDED before it
  reaches routing.** engine-o emits `provenance.recall_override`, yet the supervisor's
  `_resolve_subject` (`src/iagent/defs/dynamic_supervisor.py`) pulls only `confidence_score`,
  `abstention_reason`, `instance_label` from that provenance and drops the rest — a textbook
  `[[resolution-discard-pattern]]` instance, sitting *beside two sibling fields whose own comments
  name the pattern*. So gating on this flag ALONE would be a **dormant gate**
  (`[[feedback_presence_in_repo_is_not_presence_in_running_system]]`). The core's flag branch is
  therefore explicitly DORMANT-UNTIL-WIRED.
- `routing.about.confidence <= 0.50` — the LIVE proxy today. The 0.50 cap **does** propagate
  (`confidence_score` → `subject_confidence` → `routing.about.confidence`), so the weak path is
  observable now via the capped confidence even while the flag is dropped. A genuinely
  low-confidence answer failing this too is correct: a shaky answer shouldn't seed a durable
  workflow regardless of the mechanism.

## 3.1 Producer-side prep (lands with the S4 driver) — invert the discard boundary, don't patch it a third time

**Do NOT thread `recall_override` through as one more named field.** That is the third one-line
patch to the same bug, and the bug's shape is *allowlist-by-hand at a boundary that keeps growing*:
`_resolve_subject` (`src/iagent/defs/dynamic_supervisor.py`) pulls named fields from the resolution
provenance and silently drops the rest — its own comments already name two prior instances, and
`recall_override` is the third. Every future provenance field (`resolved_via` below, whatever the
ADR-0031 ladder grows next) re-runs the identical failure: producer emits, boundary drops, consumer
gates on a phantom.

**Invert it.** When the driver work opens that file anyway, pass provenance through **as a block** —
`routing.about.provenance = resolution_provenance` (or a spread with an explicit *deny*list for the
genuinely-internal fields) — so the boundary defaults **transparent** and the next field arrives
free. Same producer/consumer lesson as the graph names (`[[project_phase5_prophecy_resolved]]`):
stop making the consumer enumerate what the producer knows. The gateway `about` projection then
surfaces the block alongside `confidence`; Slice 4's flag branch reads `about.provenance.recall_override`
and goes live.

**While in there, emit `resolved_via` at the resolver — it's the flag that SURVIVES.** The dual
gate's live half (`confidence <= 0.50`) is semantically overloaded: a capped weak-path answer and a
genuinely-uncertain strong-path answer read identically at 0.50. `resolved_via` (`exact | containment
| reduced-query | llm-alone | urn-direct` — the ladder-rung-as-confidence-semantics from ADR-0031)
subsumes `recall_override` (which is just `resolved_via == llm-alone` plus an override bit). Emitting
it is one field at the resolver, and once provenance passes as a block it costs nothing downstream —
so Slice 4's gate can eventually refuse on the **honest** signal (weak *rung*) instead of inferring
weakness from a capped number. **Sequence:** one visit to `_resolve_subject` retires three debts —
provenance-as-block + `resolved_via` emission + the `resolveInstance` `_TEMPORARY` convergence
(`[[project_resolve_instance_provider_gap]]`) — all *before* the S4 driver seals, so the dormant half
of the dual gate goes live before anything seals against it. S3/S5 drivers don't consume resolution
and go first.

## 3. Seeding inherits enforcement — it is a SOURCE, not a bypass

The most important property. A seeded step is authored on behalf of a **seeder** (the user
promoting the answer), and it must be **eligible for that seeder** exactly like a hand-authored
step — the same `select-from-authorized-set` / verb-eligibility Slice 2 enforces:

```
seed_and_validate_step(answer_routing, *, authorized_subjects, authorized_verbs, ...)
  -> extract (subject, verb) from routing
  -> validate_pick(subject, authorized_subjects)   # the seeded subject must be in the seeder's set
  -> validate_pick(verb, authorized_verbs)          # the seeded verb must be eligible for the subject
  -> SpoOperationStep
```

This closes the obvious escape hatch: *"I got an answer once, so I can seed a step even if I'm
no longer entitled."* No — the answer is provenance, not authority. The seed re-checks against the
seeder's CURRENT grants (Slice-2's authorized_operation_subjects ∩ authorized_verbs). An answer
whose subject you can no longer see, or whose verb you're no longer eligible for, does not seed —
`PickRefused`, same as authoring it by hand. (A `derived_from_artifact_id` provenance link on the
resulting step is a natural follow-up so the definition records which answer it came from.)

## 4. The pure core (this slice) — `answer_step_seeding.py`

Pure, unit-testable, no network — the analogue of the Slice-2 funnel:

- `seed_step_from_answer(routing, *, verb_output_uri=None, step_id=None) -> (step | None, reason | None)`
  — the native extraction + the not-seedable guards. Returns the reason instead of raising, so a
  UI can say *why* an answer can't become a step.
- `seed_and_validate_step(routing, *, authorized_subjects, authorized_verbs, ...)` — seed then
  ENFORCE against the seeder's authorized sets (reuses `spo_interview.validate_pick`), raising
  `PickRefused` when the seeded tuple isn't eligible for the seeder. This is the "inherits
  enforcement" guarantee made executable.

## 5. Driver + seal (spec — deploy-gated, not this slice)

The canvas / cortex-bff hands the answer's `routing` (+ the seeder's identity) to a seed handler,
which computes the seeder's authorized sets (Slice-2's `authorized_operation_subjects` +
`authorized_verbs` for the subject), calls `seed_and_validate_step`, and appends the step to a
draft `WorkflowDefinition` the human then commits (Decision C — the human asserts). Composed-path
seal: a grounded answer whose (subject, verb) the seeder is entitled to → a valid `spo_operation`
step that round-trips through `load_workflow_definition`; a fallback answer → refused; a
weak-provenance (recall-override / capped-confidence) answer → refused; an answer whose subject
the seeder can no longer view → `PickRefused`.

**Sequencing (driver-time, not core-time).** The S4 driver consumes *routing subject quality*, so
two upstream items must land before it seals, or it seals against a pre-convergence resolution
path and re-seals after: (1) the `recall_override` thread-through (§3.1); (2) the
`resolveInstance` convergence — the retire-`_TEMPORARY` thread (`[[project_resolve_instance_provider_gap]]`,
ADR-0031). S3 and S5 drivers do NOT consume resolution and can go first. That ordering also gives
the `recall_override` telemetry more soak time before seeding starts trusting its absence.
