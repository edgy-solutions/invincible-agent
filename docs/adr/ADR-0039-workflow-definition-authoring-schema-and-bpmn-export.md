# ADR-0039 — Workflow definitions: YAML is authoritative, the schema is a committed artifact, BPMN is an export-only projection (extends ADR-0029)

**Status:** Proposed — decision recorded; the three deliverables (schema, scaffold, exporter) are consequences of it and land separately, each sealed.
**Date:** 2026-08-10
**Deciders:** Platform team
**Related:**
  - [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) — establishes the git-asserted `WorkflowDefinition` and the step kinds. This ADR decides **how it is authored and viewed**, and changes nothing about what it means.
  - [ADR-0034](ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md) — the admission/structure split, and the ruling that **a definition may not contain a mode branch**, which is the load-bearing constraint below.
  - [ADR-0036](ADR-0036-config-layering-seed-overlay-composition.md) — definitions are reviewed like grants; that property is what BPMN-as-source would destroy.

## Context

A workflow definition today is a git-asserted YAML in `policy/workflows/` with about eight keys, executed on Restate by a shared executor. Three exist: `grouped_review`, `autonomous_review`, `promote_answer_artifact`.

**The problem is not that the format is unfamiliar — it is that the schema exists only inside the executor.** There is no artifact that says what a valid definition is. Authoring means reading Python; validity is discovered at admission, at runtime, in a pod. That is the same class this project has spent a month eliminating everywhere else: *a claim whose only authority is code nobody reads.*

The format is BPMN-shaped without being BPMN, and the correspondence is close enough to be worth naming: `human_await` is a user task, `spo_operation`/`direct_call`/`dispatch_fanout` are service tasks, `participants` with roles are lanes, the ordered `steps` list is an implicit sequence flow. Anyone who has read a BPMN diagram reads the file correctly on sight.

**What is deliberately absent is the more interesting half:** no gateways, no branching, no events, no sub-processes, no boundary/timer/compensation events. That is not immaturity — it is ADR-0034's ruling. The moment definitions gain gateways they become programs, and the property that makes them reviewable *as policy* (a definition declares; the executor owns mechanism) dissolves.

**What is added beyond BPMN is where the value lives:** `audience` (a Topaz relation), `classification`/compartment, `promise_name` (a durable Restate promise), `completion.mode: grouped` selecting executor-owned batch semantics, `observable_state` tiers. In BPMN these are vendor extension elements — precisely the part no external tooling understands. Adopting BPMN as the source format would trade the governance for the diagram.

### The second plane — verified, and it is not what it looks like

The repo contains BPMN-flavoured machinery that is **a different plane, not a second spelling of this one**. Verified by read, 2026-08-10:

| | `policy/workflows/*.yaml` (this ADR) | `bpmn_catalog` + `src/iagent/defs/dynamic_factory.py` |
|---|---|---|
| executor | **Restate** (`_run_definition`) | **Dagster** (`GraphDefinition` → `@job`) |
| storage | git-asserted YAML, reviewed like grants | **Postgres table**, runtime-loaded, mutable |
| units | `human_await` / `spo_operation` / `direct_call` / `dispatch_fanout` | BPMN task nodes POSTing to agent endpoints |
| branching | **forbidden** (ADR-0034) | **supported** — the module resolves sequence flows *including through gateways* |
| purpose | governed HITL + dispatch, reviewable as policy | agent-endpoint orchestration with asset lineage |

**Recorded as fact, not adjudicated here:** `src/iagent/definitions.py:27` calls `dynamic_factory.build_dynamic_jobs()` unconditionally on every Dagster load, and `bpmn_catalog` was **reported empty** when read in sandbox on 2026-08-10 — a measurement that a later attempt could **not reproduce** (the sandbox Postgres refused a password-less connection), so it is carried as *reported-unconfirmed*, not as fact. The honest sentence, which belongs in the README too: *we have a Dagster-side BPMN loader that runs unconditionally* — and, on one unreproduced reading, *has never had a definition in it.* The stronger sentence is the interesting one and is exactly why it must not ride an unconfirmed measurement; the weaker one is verified. This ADR states the cost and does not schedule its fix — the Dagster plane's lifecycle is its owner's decision, made when they touch it. The one forward-looking clause below is the one that belongs to *this* decision's assumptions.

## Decision

1. **YAML remains the authoritative source.** Definitions are policy artifacts: diffable, greppable, reviewed like grants.

2. **The schema becomes a committed artifact, generated from the executor's own models.** `model_json_schema()` from the Pydantic models in `workflow_definition.py`, committed to the repo, with a drift test asserting the committed schema still matches the model — generated, never hand-written, so schema and executor cannot disagree. Validation runs in the rails alongside `validate_policy`, so an invalid definition fails **at merge**, not at admission.

3. **BPMN export is a generated projection.** Definition → BPMN XML, mechanical and deterministic: user task, service task, lanes, sequence flows, with the governance attributes carried into `extensionElements` so they survive the trip visibly. Open it in Camunda Modeler, review it with a process person, paste it into a design doc. The YAML stays authoritative.

4. **BPMN import is rejected.** See below — this is the clause most likely to be reopened, so it carries its reasoning.

5. **Step kinds are renamed to BPMN's conventional words** — `human_await` → `user_task`, `spo_operation` → `service_task`. Zero semantic change. This is a **safety** measure, not ergonomics; see the naming-collision clause.

### Why import is rejected

A permissive import that ignores unsupported elements means **the process a human drew is not the process that runs** — a definition that looks approved and behaves differently. That is the worst failure class in this system's vocabulary, and logging the drop does not fix it, because logs are not read at authoring time.

If import is ever revisited, the condition is recorded now: **refuse loudly, never ignore.** Parse the BPMN, validate against a named documented profile of the elements the executor honors, and reject anything outside it by element id and reason — *"gateway `Gateway_0x9f` is not expressible: definitions may not branch."* Same shape as the unbound-placeholder refusal already enforced at admission.

Import is also unnecessary: schema-plus-scaffold gives internal authors what they need, and external authors get the schema. Drawing, if it ever matters, is an **input method** — draw, compile through a strict front end, commit the YAML it produces — never a storage format.

### The naming-collision clause

The two planes are **both legitimate and genuinely distinct**. The hazard is that they share a vocabulary while holding opposite rules about branching, and are currently discriminated only by **which directory a file is in**.

**Stated failure mode:** a reader learns from `dynamic_factory` that "BPMN workflows here support gateways", authors a `policy/workflows/*.yaml` with a gateway, and gets a definition that looks approved and does not do what it appears to.

**Mitigation, three parts:**
- the rename (5 above), which makes this plane's kinds visibly *not* the catalog's node types — a structural discriminator rather than a documented one;
- each plane's files state which executor they target and whether branching is expressible there;
- the exported BPMN's header states that it projects a **Restate policy definition, not a Dagster catalog job**.

This follows the marker-at-the-site discipline used throughout: the person must **trip over** the difference, not be trusted to have read about it.

**The one forward-looking clause, and it belongs to this ADR's own assumptions:** the analysis above rests on the catalog being empty. **If `bpmn_catalog` stops being empty, the vocabulary collision becomes live and the naming clause becomes mandatory rather than advisory.**

## Alternatives considered

**Fold the two planes together — rejected, and this is the clearest statement of why either exists.** One is a git-asserted policy artifact whose entire value is that it *cannot* branch; the other is a mutable runtime table whose value is that it *can*. Two planes with opposite virtues; merging them destroys whichever virtue loses.

**BPMN as the source format — rejected.** BPMN XML carries diagram-interchange layout, so every box someone nudged appears in the diff. That degrades the review-definitions-like-grants property this design depends on. It also hands authors exactly the gateway constructs ADR-0034 refuses.

**Status quo, executor-as-schema — rejected.** The format's only authority is code. Authoring requires reading the runner, validity is discovered at runtime, and error messages arrive at admission rather than at the offending key. This is the class the project is eliminating.

**Permissive BPMN import — rejected**, as above: it imports a lie.

**Rename step kinds for familiarity alone — insufficient.** It was the original motivation and it is real, but familiarity would not justify touching a live vocabulary. The collision finding upgrades it to a safety fix, which does.

## Consequences

- External authors work from a schema instead of from inference; editors validate while typing.
- Invalid definitions fail at merge, with the offending key named.
- BPMN opens in standard tooling for review, with governance attributes visible rather than vanished.
- Someone opening the export sees a **straight line**. That is the design, not a lossy exporter: branching is not expressible, escalation is executor-owned semantics. Say so in the header and the README, or the next reader will file a bug against the exporter.
- The rename touches the three existing definitions and every consumer of the kind strings — an expand/contract question for the executor's discriminated union, to be settled when it lands.

- **The rename is NOT the free edit its predecessor was, and whoever lands it must read this first.** `direct_call` → `dispatch_fanout` went in as an edit rather than a migration for one specific reason: *every prior `AutonomousReview` instance was terminal*, so no live journal held the old kind string. **`human_await` has no such luxury.** Read 2026-08-10: **ten `GroupedReview` invocations are suspended right now**, each holding `human_await` step state in a durable Restate journal, and a suspended workflow's journal is exactly the surface `AGENTS.md`'s "code renames orphan JOURNALS, not just keys" is about. The rename is therefore expand/contract **with a drain question**: either the executor accepts both spellings for the duration, or the suspended reviews settle first. Choosing wrong strands ten reviews that are visible and unresolvable.

  *Where the old strings do and do not live, verified rather than assumed:* decision records do **not** carry step kinds — `dr-08a9c7e7a8c04e00` has eleven predicates and none of them is a step kind — so the audit corpus is **not** at risk and the rename must not be scoped as a corpus migration. The durable holders are Restate journals (`step_results` carrying `kind`), which are immutable by design. **Historical journals keep the old name; that is correct and must not be rewritten.** The constraint is on live suspended instances, not on history.

## Acceptance — the seals this ADR commits to

- **schema-matches-model drift test** — the committed schema regenerates identically from the models.
- **every repo definition validates against the committed schema in CI.**
- **export preserves every governance attribute** (`audience`, `classification`, `promise_name`, `completion.mode`) into `extensionElements` — broken-on-purpose to prove the seal bites, since an exporter drifts silently the first time a step kind is added.
- **round-trip is out of scope while import is rejected.** A `yaml → bpmn → yaml` identity test was considered; it cannot be written without an importer, and building one solely to seal the exporter would create the very artifact this ADR rejects. The attribute-preservation seal above carries the load instead. *Recorded so the absence reads as a decision rather than an omission.*
- **generated BPMN carries a header** stating the YAML is authoritative, edits there do not run, and the file projects a Restate policy definition rather than a Dagster catalog job.

## Riders (not decisions — work this ADR names for owners)

- **README correction.** The README's line about dynamic BPMN workflows currently supports the inference "we have BPMN workflows", which is true only of the Dagster plane and only of an empty loader. Correct it with the honest sentence, and state that `policy/workflows/*.yaml` is a restricted subset of BPMN's task/lane vocabulary — extended with entitlement and durability attributes, with branching deliberately not expressible.
- **Board item, with an owner, not an ADR clause:** `definitions.py:27` calls `build_dynamic_jobs()` unconditionally on every Dagster load against an empty catalog. Small standing cost; larger standing confusion, since it is the mechanism by which "we have BPMN workflows" keeps sounding true.

## Verification note

Every claim about current behaviour in this ADR was read on 2026-08-10: the step kinds and definition set from `workflow_definition.py` and `policy/workflows/`; the two-plane table from `dynamic_factory.py`'s module docstring and `sql/create_bpmn_catalog.sql`; the loader wiring from `src/iagent/definitions.py:27`; the row count from sandbox Postgres. **Unverified:** whether `bpmn_catalog` is non-empty in any other environment — the count was taken once, in sandbox, and the collision-activation clause is written to hold regardless.

---

## AMENDMENT 2026-09-12 — choice lives in DECISION TABLES at trigger and termination

**RULED by the architect, from ADR-0051's safety-acceptance flow.** This amendment does not relax
the no-branching rule; it names where the branching that real processes need actually belongs, so
that the rule stops reading as "this rail cannot express a process with a choice in it."

**THE PROBLEM THE ORIGINAL RULING LEFT OPEN.** ADR-0034 forbids a mode branch and this ADR forbids
gateways, for a reason that holds: *the moment definitions gain gateways they become programs, and
the property that makes them reviewable as policy dissolves.* But almost no real process — a
maintenance disposition, a safety acceptance, an escalation — can be described without a choice.
Read narrowly, the ruling said such processes cannot live on this rail at all, which pushed the
choice back into ENGINE CODE. That is where ADR-0051 first put it (`_CONCURRENCE_LEVELS` and a
gate function in `safety_agent`), and it is strictly worse: the choice became untailorable AND
unreviewable, which is both halves of what the rule was protecting.

### The three layers, each with one job and one kind of artefact

| layer | job | artefact |
|---|---|---|
| **engines** | COMPUTE FACTS. A verb measures something and emits an attribute — `risk_level: Serious`, `part_condition: repairable`, `deadline_missed: true`. **An engine never chooses what happens next.** | code |
| **decision tables** | CHOOSE. Rows mapping declared attributes to a definition id. | ratified data, `policy/decisions/` |
| **definitions** | SEQUENCE. Linear, no branch, exactly as ruled above. `human_await` suspends until disposed, which IS the structural "before". | ratified data, `policy/workflows/` |

**This is the DMN half of BPMN, and it is what ADR-0034 was protecting all along.** A table is
exhaustive, stateless and reviewable as policy in a way an inline condition never is. The rule was
never "processes may not branch" — it was "a definition may not be a program".

### Choice lives in exactly two places, both outside the definition and both data

**SELECTION AT TRIGGER** — which definition opens for this event:

    (event=risk_assessment_drafted, level=High)      -> safety_acceptance_with_concurrence
    (event=risk_assessment_drafted, level=Medium)    -> safety_acceptance_direct

**CHAINING AT TERMINATION** — a definition ends with an observable outcome; the same table says
what opens next:

    (definition=safety_acceptance_with_concurrence, outcome=not_concurred) -> safety_redraft

**A "route back to the drafter" is NOT a branch.** It is one definition ending `not_concurred` and
a table row opening another. **Every instance is a record**, which is better for audit than a loop
inside one — the question "who sent this back, and on what basis" has an answer with a task id
rather than a journal entry.

### What this buys, and the boundary that stays

- **Loops** are new instances.
- **Escalation** is a `human_await` with a declared deadline terminating `timed_out`, and a table
  row opening the escalation definition — a DISPOSITION, not an event, so it stays inside the
  rulings.
- **Parallel work** is `dispatch_fanout`, which already exists.
- **Sub-processes** are chaining.
- **What cannot be expressed is a condition on something no engine has measured** — and that is
  the boundary working, not a gap. The fix is a verb that measures it, never a formula in a table.

### THE GUARD THAT KEEPS TABLES FROM BECOMING CODE

**Rows match declared attributes by EQUALITY or MEMBERSHIP only.** No expressions, no arithmetic,
no reading state. If a choice needs computation, the computation is a verb.

Two seals, and the first is ADR-0051's generalised:

- **TOTALITY** — every attribute value an engine can emit has a row. This is exactly seal
  "every level the matrix can yield has a granted audience", widened from one attribute domain to
  any. A value with no row opens NOTHING, which must be visible rather than silent.
- **UNIQUENESS** — no two rows match one input. Without it a table is order-dependent, which is an
  expression wearing a table's clothes.

### DO NOT BUILD A FOURTH COMPOSER — this is the same pattern a third time

The task-kind work established the shape and the graph-manifest rows repeat it: a row is data in
`policy/`, seed plus overlay compose **by key**, a consumer reads the composed set and never a
hardcoded table, an undeclared thing gets NOTHING rather than a default, and the seal asserts both
directions.

| task kinds (built) | decision tables (this amendment) |
|---|---|
| one row per species, `accepts` / `reason_required` | one row per case, `(event, attributes) -> definition_id` |
| `policy/task_kinds/` + overlay | `policy/decisions/` + overlay, **same composer** |
| gate composes; refuses on absence from the composed set | trigger composes; opens nothing on absence |
| cutover seal: code table equals rows, both directions | totality + uniqueness |

**MEASURED 2026-09-12, so the reuse is sized rather than assumed:** `iagent_mesh.task_kinds.compose`
is already generic except for **one hardcoded key field** (`raw.get("kind")` in `_read_rows`) and
**one builder call** (`_build` → `TaskKind`). The seed+overlay walk, full-replacement-by-key and the
tombstone-for-an-unseeded-key error are all reusable as they stand. So reuse is a small SDK
parameterisation — `compose(seed, overlays, *, key_field, builder)` — and **a fourth copy of the
composer is refused by name.** The risk here is not deviation; it is that the pattern is familiar
enough to be re-implemented rather than reused.

**IT RIDES v0.8.1, NOT v0.8.0, AND THE REASON IS WORTH RECORDING.** A dispatch asked the SDK lane
to *hold* v0.8.0 until the parameterisation was in. That was not possible: **v0.8.0 was already
cut, pinned across sixteen sites, merged, and serving the fleet.** A pushed tag is never rewritten
— holding one that exists is not a scheduling decision, it is a request to rewrite history. So the
parameterised composer is **v0.8.1**, and `policy/decisions/` is built against the SDK's composer
from its first commit rather than against a copy that gets replaced later. **"Hold the tag" and
"the tag is not yet cut" are different states, and only one of them is holdable.**

### Consequences for ADR-0051 (the first author on this rail)

`_CONCURRENCE_LEVELS` and `acceptance_request_after_concurrence` leave `safety_agent`. Two linear
definitions replace them, plus selection and chaining rows. The seal — *a High cannot reach
`accepted` without `concurred` in its lineage* — moves to the composed table plus definitions, same
mutation, different subject.

### RULE — engine code stays until `policy/decisions/` composes

**Stated as a rule, not a caution, and deliberately.** A caution reads as advice and is skipped by a
lane that does not know why it is there; a rule with its consequence named is not.

> **Engine code stays until `policy/decisions/` composes. Removing it first turns every Serious and
> High acceptance into a DIRECT one, silently — the fix producing the failure it exists to
> prevent.**

**Why it must be written rather than left to judgement.** Deletion looks like the obvious first
step: the amendment says the choice does not belong in an engine, so a lane reads that and removes
`_CONCURRENCE_LEVELS`. **Nothing then fails.** The suite stays green, the queue keeps working, every
card renders — and the user representative's concurrence, which MIL-STD-882E §4.3.7 requires
**before** every Serious and High acceptance, simply stops happening. The defect is invisible on
every surface that would normally report one, because the remaining path is a *valid* path. It is
just the wrong one, and the thing it drops is the second signature.

**So the order is fixed:** the table exists and composes → the rows are written → **then** the
engine code comes out → **then** the seal moves, with its mutation re-run against the new subject.
*A seal that moves and is not re-proven has only been relocated.*

**And the order matters most to whoever is least likely to know it.** The lane that eventually
deletes those two symbols may be doing routine cleanup months from now, prompted by a comment
saying the logic belongs elsewhere — which it will, and which will be true. This sentence is that
lane's only protection.
