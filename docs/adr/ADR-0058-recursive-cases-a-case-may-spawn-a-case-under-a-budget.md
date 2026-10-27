# ADR-0058 — Recursive cases: a case may spawn a case, under its seals and a declared budget

**Status:** Draft, third revision. Written for the architect on the 10-23 order. Nothing is built.
The architect decided the five open questions of the second revision on 10-27. §Decisions of
2026-10-27 records them, and the budget numbers wait on Lane 74's census.
**Date:** 2026-10-22; revised 2026-10-27
**Deciders:** architect (decision); Chris (review); Lane 74 (draft)
**Related:**
  - [`ADR-0029`](ADR-0029-process-workflow-model-spo-steps-restate.md): the process model. A case
    is a `WorkflowDefinition` run on the Restate runner. This ADR adds one step kind to it.
  - [`ADR-0026`](ADR-0026-persona-entitlement-topaz-authorization.md): persona and entitlement
    authorization. Every level answers it again; no level inherits a decision.
  - [`ADR-0025`](ADR-0025-instance-plane-access-control-as-provenance.md): access control carried
    as provenance. A child's record carries its own provenance and never strips its parent's.
  - [`ADR-0027`](ADR-0027-composable-approval-policy.md): approval policy. A child's approvals are
    its own; same_actor is decided across levels (§3.4).
  - [`ADR-0035`](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md): two planes.
    The spawn is a process-plane act, and the record it returns is a data-plane artifact.

**Numbering.** 0058 is unallocated on master and on every other pushed ref. Re-scanned on
2026-10-27: 306 refs, and 0058 appears only on this draft's branch. The highest ADR on master
`4a4cf47c` is 0057. Two later numbers are held on unmerged branches: 0060 on `lane/01-adr-0060` and
0061 on `lane/74-socratic-workflow`. 0059 and 0062 appear on no ref.

## Context

The order names three primitives: **the harness is the unit**, **one spawning primitive**, and
**bounded context plus records**. They have no outside source; they are this ADR's own decisions
(architect, 10-27), §1 to §3 define them, and nothing outside this ADR defines them further.

What exists today. This was read from code at 360fbeb6 and re-read at master `4a4cf47c` on 10-27;
nothing below changed:

- **A case is one level deep.** `agent_fleet/restate_analyst/workflow_definition.py` declares
  eight step kinds: `human_await`, `spo_operation`, `direct_call`, `dispatch_fanout`, `render`,
  `signal_await`, `wait` and `emit`. None of them starts a case. `dispatch_fanout` fans one
  review's batch out to items on the exactly-once path. It does not create a child case with its
  own definition, terminal state or summary.
- **The model work inside a level is unbounded.** In one measured question (Q1), Engine O made 4
  model calls when resolve landed: `ExtractIntent`, `DecomposeQuery`, `ClassifyDomainIntent` and
  `ClassifyPredicate`. Then the specialist's agent loop ran. No caller passes `max_steps`, so the
  smolagents default of 20 applies. Under load on revision 199, a retried 30 s timeout repeated one
  prompt 4 and then 8 times, for 10–15 calls on one question. Item 1 (now on master) stopped that
  repeat. But no declaration anywhere says how many model calls a case may make. On master,
  `model_calls`, `model_call_budget`, `budget_exhausted`, `MAX_CASE_DEPTH`, `spawn_case` and
  `parent_case_key` have no hits in the tree.
- **The seals are per case.** Identity, grants, admission, approval and terminal summary are each
  sealed for a single case (§3 lists the files). None of them has an arm with a parent.

So recursion is not a feature to switch on. Every seal we have assumes a depth of one. Adding a
level without binding it to those seals would open a path no seal covers.

## Decision

### 1. The harness is the unit: a level is a whole case

A child is a **case**, a `WorkflowDefinition` run by the same runner as its parent. It has its own
minted case key, its own steps, its own terminal state and its own summary. Nothing smaller is
a level:

- an agent loop inside an `spo_operation` is a **leaf**, not a level;
- a `dispatch_fanout` item is a dispatched item, not a level;
- a recursive `DecomposeQuery` is a planner output, not a level.

**Why.** Each seal in §3 is written against a case: its key, its caller, its terminal state. Taking
the case as the unit lets every one of them apply to a child unchanged. Any smaller unit would need
its own copy of each seal, and §Alternatives explains why those copies would drift.

### 2. One spawning primitive: the `spawn_case` step kind

One new step kind, and **no other way to start a case from inside a case**. No engine endpoint,
model tool, `direct_call` or `dispatch_fanout` may start one. A seal must assert that no other step
kind reaches the runner's case-start path (§3.10).

```yaml
- kind: spawn_case
  id: assess-each-open-hazard            # step id; the child's record links to it
  definition: safety.hazard_risk_review  # a RATIFIED definition id, never an inline definition
  subject_ref: "{steps.pick.output.hazard_id}"
  inputs:                                # declared bindings only; nothing else crosses
    hazard_id: "{steps.pick.output.hazard_id}"
  capability: mesh:spawnHazardReview     # REQUIRED; Topaz can_invoke, as dispatch_fanout
  budget:
    model_calls: 12                      # reserved from the parent's remainder (§4)
    wall_s: 600
  on_exhausted: escalate                 # escalate | refuse; no default
```

The step is **executor-owned**, as `dispatch_fanout` is. The YAML declares what is spawned. The
executor owns how:

1. assert `can_invoke` on `capability` for the **caller**, not for the service;
2. check the depth against `MAX_CASE_DEPTH`;
3. reserve the budget from the parent's remainder;
4. mint the child key;
5. start the child;
6. await one durable promise for the child's record.

The parent's step can only end in one of two ways: it holds a record, or it reaches the
`on_exhausted` path. **A spawn that never returns cannot be declared**, because the await is not
authored.

- **Depth is a declared constant, not a definition field.** `MAX_CASE_DEPTH = 4` (architect,
  10-27). The constant counts levels with the root as one, so 4 means a root and three levels of
  descendants; `depth` in the record runs 0 to 3. Spawning past it is a definition
  error at load time when the depth can be read statically. Otherwise it is a terminal `refused`
  at run time.
- **`definition` names a ratified definition id.** An inline child definition would be a definition
  that was never reviewed. The policy rail ratifies definitions, and a spawn may only call what it
  ratified.
- `_Declared` is `extra="forbid"`, so an unknown field on `spawn_case` is refused at load.
  `test_a_definition_field_the_runner_cannot_see_is_refused.py` gains this kind in its census.

### 3. Bounded context and records

**What goes down.** A child receives only:
- its declared `inputs`;
- its `subject_ref`;
- the caller's identity, unchanged;
- its budget;
- the parent's key and the spawn step id, for linkage only. The child cannot read the parent's
  state through them.

There is no shared scratchpad, transcript or model context between levels. If the child needs
something, the parent must bind it as an input, where review can see it.

**What comes back.** Exactly one record. The parent reads nothing else from the child.

| field | |
|---|---|
| `child_case_key` | the child's minted key |
| `parent_case_key`, `spawn_step_id`, `depth` | linkage; written by the executor, never by the child |
| `definition_id` | what ran |
| `outcome` | closed set: `completed`, `refused`, `escalated`, `budget_exhausted`, `timed_out` |
| `output` | typed by the child definition's declared output; absent unless `completed` |
| `provenance` | the child's own provenance floor (ADR-0025), intact |
| `model_calls_used`, `wall_s_used` | measured by the executor (§4) |

A child's terminal summary is written as for any case
(`test_a_terminal_case_writes_its_summary.py`), and the record is the parent's view of that
summary. It is not a second account of it.

### 3.1–3.10 Every level is bound to the seals we have

Each row is one invariant that holds today for a single case, the seal that holds it, and what it
must say at depth ≥ 1. **The acceptance gate is a level census:** every row's seal gains an arm that
runs the same assertion at depth 0 and at depth 1, and the census asserts that no row is missing a
depth-1 arm. With `MAX_CASE_DEPTH = 4`, a parent-to-child arm is not enough for the properties
that hold across a tree. 3.3 (a subset of a subset), 3.4 (same_actor across the tree) and the §4
reservation each also get an arm at depth 3, root to deepest. The depth limit gets an arm that
spawns from depth 3 and is refused.

| # | invariant | seal today | at depth ≥ 1 |
|---|---|---|---|
| 3.1 | service identity is never a grant | `tests/security/test_service_identity_is_never_a_grant.py` | the runner's identity spawning a child grants the child nothing; the caller's identity is what the child is decided on |
| 3.2 | a delegate acts only for a declared principal | `tests/test_a_delegate_acts_on_behalf_of_a_declared_principal.py` | the principal is carried down unchanged; a child cannot widen it to another declared principal |
| 3.3 | grants are an intersection; deny by default | `tests/routing/test_eligibility_trace.py`, `tests/test_eligibility_declarations_reach_the_edge.py`, `tests/security/test_asset_sync_deny_before_permit_after.py` | a child's eligible set is a subset of its parent's, never a superset; a parent cannot pass a child what the parent could not see |
| 3.4 | a supervisor cannot approve the disposition they chose (same_actor) | `tests/test_a_supervisor_cannot_approve_the_disposition_they_chose.py` | **a new arm is owed.** The chooser and approver are compared across the whole case tree: choosing in the parent and approving in a child is the same actor |
| 3.5 | a class enters the pool only as a verb's input (admission) | `tests/routing/test_a_class_enters_the_pool_only_as_a_verbs_input.py` | a child's resolve runs the same admission rule; a parent's resolution is an input, not a pool |
| 3.6 | the act reaches the owning workflow | `tests/safety/test_the_act_reaches_the_owning_workflow.py` | a signal addressed to a child reaches the child's key, never the parent's |
| 3.7 | the card's case id is the minted key | `tests/safety/test_the_card_case_id_equals_the_minted_case_key.py` | each level mints its own key; a child card shows the child's key and links the parent's |
| 3.8 | a case runs from trigger to terminal, and writes its summary | `tests/test_a_case_runs_from_trigger_to_terminal.py`, `tests/test_a_terminal_case_writes_its_summary.py` | a parent is not terminal while a child is open; every child outcome, `budget_exhausted` included, is terminal and summarized |
| 3.9 | a timeout is terminal, not retried; retry follows the taxonomy | `tests/routing/test_a_timed_out_reresolve_refuses.py`, `tests/test_direct_call_retry_taxonomy.py`, `tests/routing/test_engine_o_joins_an_identical_call_in_flight.py` | the spawn's await is not retried on timeout; a timed-out child is `timed_out`, never re-spawned by Restate's retry |
| 3.10 | an unknown definition field is refused; the answer carries its provenance floor | `tests/test_a_definition_field_the_runner_cannot_see_is_refused.py`, `tests/test_the_answer_carries_its_provenance_floor.py` | `spawn_case` joins the field census; a parent's answer built on a child's record carries the child's floor; and **no step kind but `spawn_case` reaches the case-start path** (a new wiring arm) |

### 4. A declared per-level model-call budget

- **Declared per definition.** Each `WorkflowDefinition` declares `budget.model_calls` and
  `budget.wall_s`. A definition without a budget does not load. Today's definitions would get
  budgets from the measured unit below, never from a guess.
- **Reserved, not shared.** A `spawn_case` reserves its `budget` from the parent's remainder before
  the child starts. If the remainder is too small, the spawn is refused before any child exists,
  and the outcome is the step's `on_exhausted`. When the child is terminal, what it did not use is
  refunded to the parent. So the sum over a case tree can never exceed the root's declaration.
- **Every completion counts:**
  - each model completion an engine makes on the case's behalf;
  - retries;
  - each agent-loop step;
  - each BAML call.

  A completion coalesced onto an identical call already in flight (the item-1 dedupe) costs the
  joining case once, as if it had made the call (architect, 10-27). Two cases sharing one
  completion are each charged one call; a case is never charged zero for a completion it used.
- **An attempt counts, and a replay does not.** A retried `ctx.run` re-executes its closure, so a
  retried attempt's model calls really are spent and are counted. A replayed `ctx.run` returns its
  journaled result without calling anything, so it must count zero. The count is therefore written
  inside the journaled step that makes the call, never from the handler around it. That is the
  same replay-safe boundary ADR-0038 drew for observations (`restate_analyst/main.py:1439–1446`).
  A seal owes an arm that replays a step and asserts that the remainder is unchanged.
- **The agent loop is bounded by the budget.** An `spo_operation` passes
  `max_steps = min(definition cap, remaining model_calls − reserve)` to the agent it runs. The
  smolagents default of 20 is never the bound.
- **Exhaustion is an outcome, not an error.** At zero remaining, the next model call is refused, the
  level ends `budget_exhausted`, and the parent's `on_exhausted` decides: `escalate` hands the case
  to a human with the record so far, and `refuse` ends the parent `refused`. Neither is a default,
  so the author has to choose one.
- **`wall_s` is enforced by each step, and Restate's timeout is the backstop** (architect, 10-27).
  - Each step bounds its own work and ends as an outcome (`timed_out`) before the framework could
    abort it, as `DA_AGENT_TIMEOUT_S` already does for one engine (`data_analyst/main.py:64`).
  - Restate's inactivity and abort timeouts are never the bound.
  - No Restate timeout is configured in the tree today, so the server defaults are what backs the
    bound up.
- **A retry seal comes first** (architect, 10-27). Three steps raise *so that* Restate retries
  (§Consequences). No budget touches them until a seal pins Restate's retry behaviour, in two
  halves:
  - **SDK:** what a bare `ctx.run` does when its closure raises. This can be sealed offline, against
    the pinned restate-sdk.
  - **Server:** whether a long `ctx.run` is aborted and re-executed from scratch. This is
    `docs/proposals/bounding-the-answer-not-just-the-source.md` §4, still a hypothesis. It can only
    be measured live, and until it is, the seal records it as unconfirmed rather than asserting
    either answer.
- **The measured unit.** Q1 cost 4 Engine O calls plus the agent loop. The loop is unbounded today
  (default 20, and 10–15 calls were observed on one question under the 199 repeat). A first
  per-level budget is therefore about 4 plus the loop cap. The number is the architect's to set.
  It comes from a census over the walk sheet, not from Q1 alone. Lane 74 runs that census, counting
  from engine logs (architect, 10-27).
  - A log count covers only what each engine chooses to log. So the census also records, per
    engine, which call sites it could count and which it could not.
  - A number from it is a floor, not a measurement of what a budget would count.

## Consequences

- **Engines have to report model calls per case.** This is the main cost. The executor cannot
  count what it cannot see. Engine O, Engine A, `neo4j_expert`, `weaviate_expert` and
  `data_analyst` each make model calls inside their own process. Each needs to report
  `model_calls` against the case key, and to refuse a call when the remainder it was handed is
  zero. Nothing reports this today. Until it does, a budget is a declaration no seal can test.
- **The census of timeout-retrying steps comes due.** My 10-20 report listed eight Restate steps
  that wrap a model call and would still retry a timeout. On master `4a4cf47c` there are still
  eight, and each is a bare `await ctx.run("<name>", fn)`: no `RunOptions`, no `max_attempts`, no
  `TerminalError`.

  | step | where | model call inside |
  |---|---|---|
  | `run-smolagent` | `agent_fleet/neo4j_expert/service.py:951` | the smolagents loop |
  | `format-baml` | `agent_fleet/neo4j_expert/service.py:1013` | `FormatGraphResponse` (:984) |
  | `run-smolagent` | `agent_fleet/restate_analyst/main.py:1460` | the smolagents loop |
  | `baml_interview` | `agent_fleet/restate_analyst/main.py:3116` | `IterateBPMNGraph` (:3107) |
  | `baml_turn` | `agent_fleet/restate_analyst/main.py:3272` | `InterviewSPOWorkflow` (:3262) |
  | `run-smolagent` | `agent_fleet/weaviate_expert/service.py:761` | the smolagents loop |
  | `format-baml` | `agent_fleet/weaviate_expert/service.py:776` | `FormatKnowledgeResponse` (:773) |
  | `run-agent` | `agent_fleet/data_analyst/main.py:832` | a smolagents `CodeAgent` (:746) |

  Three of the engines say in comments that they raise `RuntimeError` *so that* Restate retries:
  `neo4j_expert/service.py:169`, `restate_analyst/main.py:100` and `data_analyst/main.py:236`.
  The retry is intended there, so moving these steps onto a budget is a change of intent, not
  only a fix.

  **A ninth step calls a model.** `deterministic-trace-lineage` (`restate_analyst/main.py:1420`) is
  also a bare `ctx.run`, and inside it `ExtractPlatformScope` (:1314) is a BAML call. That call's
  own failure is caught and degrades to "no platform filter", so it does not retry on a model
  error. It still spends a call, and Restate retries the step if anything else in it raises. The
  10-20 list missed it because it does not retry on a model error.

  Under a budget, every hidden retry consumes the allowance, so these nine steps need an owner
  before this ADR can be accepted.
- **`same_actor` becomes a tree query.** Comparing the chooser and approver across levels needs the
  case tree indexed by `parent_case_key`, which does not exist yet.
- **Cards gain a parent link.** The UI shows a child's card under its parent. That is cortex-ui
  work, and it is not designed here.
- **What does not change:** every existing definition runs unchanged at depth 0 once it declares a
  budget, and no existing step kind gains spawning.

## Alternatives considered (rejected)

1. **Recursion inside the agent loop**, where an agent tool starts a sub-agent. Rejected: the
   sub-agent would have no case key, no terminal state, no summary and no seal. It is exactly the
   unsealed path §Context warns about.
2. **Inline child definitions in the parent's YAML.** Rejected: the child would never be reviewed
   on its own, and the policy rail ratifies definitions, not fragments.
3. **Extend `dispatch_fanout` to start cases.** Rejected for the same reason `dispatch_fanout`
   stopped being a `direct_call`: a step that means one thing and is used for another is a costume.
   Its semantics (a server-authored batch, exactly-once items, escalation of the whole notice) are
   not a child case's.
4. **Recursive `DecomposeQuery`**, where the planner nests sub-questions. Rejected as a level: a
   planner output is data, not a harness. It can feed `spawn_case` inputs, but it cannot be one.
5. **A shared budget pool across levels, with no reservation.** Rejected: under concurrency, one
   child could starve its siblings, and the parent could not know before spawning whether the
   spawn would be funded.

## Decisions of 2026-10-27 (architect)

The five open questions of the second revision, as decided, and where each landed:

1. **RAH is this ADR's own term, and the acronym is dropped.** §Context now states the three
   primitives as this ADR's own decisions.
   - The ruling also said to define RAH in §2 as the per-case model-call budget. That part is
     not applied.
   - In this ADR, RAH only ever named the *source* of the three primitives, in §Context and in
     the old question 1. It never named the budget.
   - The budget is defined in §4, not §2.
   - Defining RAH as the budget would make §Context say the primitives came from the budget.
     With the acronym gone, there is nothing left to define.
   - If you want a named term for the budget, say which section it goes in.
2. **`MAX_CASE_DEPTH = 4`** (§2): a root and three levels of descendants. Because a tree is now
   deeper than parent and child, the level census gains depth-3 arms for the properties that hold
   across a tree, plus a depth-limit arm (§3.1–3.10).
3. **Coalesced calls cost the case once** (§4).
4. **Lane 74 runs the census, from engine logs** (§4). Its number is a floor, and it states which
   call sites it could not see.
5. **A seal pinning Restate's retry behaviour comes before any budget touches the three
   raise-to-retry steps.** Each step enforces `wall_s` itself, with Restate's timeout as the
   backstop. Both are in §4.

## Still open

- **The budget numbers:** from Lane 74's census.
- **Who builds per-case `model_calls` reporting** in the five engines (§Consequences).
- **Who builds the retry seal** (§4). It is not assigned.
- **Who owns the nine model-calling steps** (§Consequences). They are not assigned.

## Second revision (2026-10-27)

No packet said what this revision should change. So it re-measures every factual claim in the
first draft against master `4a4cf47c`, and it narrows the open questions that the tree can narrow.
The decision sections (§1 to §4) are unchanged, except for one added bullet in §4.

- **Unchanged on master:**
  - the eight step kinds;
  - `extra="forbid"`;
  - no model-call reporting anywhere;
  - 0058 unallocated.
- **Corrected:** §3.3 named `tests/test_asset_sync_deny_before_permit_after.py`. The seal lives at
  `tests/security/`, and the top-level path never existed. The other 15 seal paths in §3 exist on
  master.
- **Added:**
  - the timeout census, with file and line for each step;
  - a ninth model-calling step, `deterministic-trace-lineage`;
  - the rule that an attempt counts and a replay does not (§4).
- **Narrowed:**
  - open question 4: the freeze is lifted;
  - open question 5: no Restate timeout is configured in the tree, and a proposal for which bound
    wins.
- **Still the architect's:** open questions 1, 2 and 3, and what is left of 4 and 5. All five were decided the same day (§Decisions of 2026-10-27).

## Indicators for revisiting

- A walk-sheet case that needs a fifth level, or a tree that reaches depth 3 in practice.
- A child that must read parent state not bound as an input. That would be evidence the bounded
  context is too tight, or that the definition is wrong.
- Model-call reporting turns out to need a process-wide counter instead of a per-case one, for
  example when two engines share a client across cases.
- A `budget_exhausted` rate on the walk sheet that is not near zero. That would mean the budgets
  are guesses.
