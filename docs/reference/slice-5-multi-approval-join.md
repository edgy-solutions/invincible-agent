# Slice 5 design — multi-approval joins (N human-awaits jointly gating one step)

Implements ADR-0029's Slice-5 rollout, coupled to [[ADR-0027]] (composable approval). N
`human_await` steps jointly gate one step/grant; the **join** is complete only when the required
approvals arrive. The load-bearing property is not the join arithmetic — it is the **lifecycle
discipline** ([[feedback_hitl_suspend_vs_fail_ruling]]): a join that can *still* complete
**suspends** (a designed await); a join that can *never* complete **terminates** (fail-and-release,
never parks). Parking on an unsatisfiable join is the DoS surface wearing a join's clothes.

## 0. Two decisions, two owners — don't conflate them

- **The authz decision** — *is this join satisfied, and may this human approve at all?* — is
  decided **on Topaz rego** against the git-asserted approval policy (ADR-0027), NOT in app code
  and NOT by a parallel approval orchestrator. The single decider owns "who counts."
- **The lifecycle decision** — *given the approval facts so far, does the workflow suspend,
  proceed, or terminate?* — is the **runner's**, and it is what this slice's pure core computes.
  It consumes the per-approval decisions (from Topaz) + the join requirement (from the policy)
  and returns the lifecycle state. It never re-decides authz.

Keeping these separate is why the core takes decisions as INPUT (like every other Slice core):
the enforceable innovation here is the **suspend-vs-fail state machine**, not the authz.

## 1. The three join states (and their lifecycle mapping)

Given a set of approvals — each `granted` / `denied` / `pending` — and a `threshold` (how many
grants the join requires; `all_of` is `threshold = len(required)`, `n_of` is `threshold = n`):

| State | Condition | Runner action |
|---|---|---|
| **COMPLETE** | `granted >= threshold` | the gated step **proceeds** |
| **PENDING** | not complete, but `granted + pending >= threshold` (still **satisfiable**) | **suspend** — a designed await on the outstanding approvers (Situation B). Safe: it can still complete. |
| **UNSATISFIABLE** | `granted + pending < threshold` (too many denials; the join can NEVER reach the threshold) | **terminate** — fail-and-release (Situation C / TerminalError). NEVER park. |

`all_of` falls out for free: with `threshold = len(required)`, a single `denied` makes
`granted + pending < threshold` → UNSATISFIABLE. A required approver's denial kills the join
immediately, rather than the workflow suspending forever awaiting an approval that will never come.

## 2. Why UNSATISFIABLE must terminate, not park (the DoS discipline)

This is the whole point, restated from the HITL ruling for joins. A suspended workflow holds
durable state. A join that *can still complete* holds it legitimately (a designed await on an
authorized human). A join that *can never complete* — a required approver already denied — that
holds state for no reason and awaiting nothing reachable. Left suspended, it is exactly the
resource-exhaustion surface the suspend-vs-fail ruling closes: an unbounded held execution keyed
on an impossible condition. So the core distinguishes PENDING (satisfiable → suspend) from
UNSATISFIABLE (→ terminate) as its central job, and the driver maps UNSATISFIABLE to a
`restate.TerminalError` (release), never a retry/park. The lifecycle-state observable
([[feedback_lifecycle_state_observable]]) is the receipt: an unsatisfiable join must land in a
terminal state, not a suspended/backing-off one.

## 2.1 The time dimension — the oracle is only as good as its MOMENT (cross-seam with the entitlement flip)

`evaluate_join` is **stateless**: it judges the approval facts *as they are now*. But entitlements
change **underneath parked joins** — a grant lands late; an approver loses `can_view` when
`ENABLE_AGENTIC_AUTH` flips (item F / `[[project_terminal_flip_runway]]`). So the SAME join
re-evaluates to a DIFFERENT verdict as its inputs move, in **both** directions:

- **PENDING → UNSATISFIABLE** (a required approver loses entitlement post-flip): if the driver
  cached the creation-time PENDING, the join parks **forever** on a now-impossible condition —
  precisely the resource surface this slice exists to kill, re-introduced through the back door of
  a stale verdict. The flip's first symptom would be a mysteriously stuck approval — the same
  class of rider as "my subjects disappeared."
- **UNSATISFIABLE → COMPLETE** (a grant lands late): a verdict computed one moment too early would
  have **terminated a workflow a late grant would have completed**. The terminate must be taken at
  the right moment (on wake, after approvals settle), not eagerly at creation.

**Driver rule (deploy-gated):** re-run `evaluate_join` on **every join wake/heartbeat**, never
cache the creation-time verdict. **ADR-0025 flip-checklist rider:** add *post-flip join
re-evaluation* alongside the existing menu-contents check — when the flip changes `can_view`, every
suspended join keyed on an approver whose clearance changed must be re-evaluated so a newly
unsatisfiable join terminates (fail-release) rather than sitting parked. This is proven in the core
tests (the two `test_reevaluation_flips_*` cases) as the semantics the driver must honor.

## 3. The pure core (this slice) — `workflow_join.py`

Pure, unit-testable, no Topaz — the analogue of the other Slice cores. `evaluate_join(approvals,
threshold) -> JoinStatus` returns one of `COMPLETE | PENDING | UNSATISFIABLE`, plus the counts
for observability. Deny-of-a-required-approver → UNSATISFIABLE by construction (no special-case).
A `threshold` above the number of approvers is UNSATISFIABLE from the start (a misconfigured join
fails loud, it does not park forever).

## 4. Driver + seal (spec — deploy-gated)

`_run_definition` treats a group of `human_await` steps carrying the same `join` id as one join:
register all their HumanTasks, suspend while the core says PENDING, proceed on COMPLETE, raise
`TerminalError` on UNSATISFIABLE. The join requirement + who-counts come from a git-asserted
join policy decided on Topaz rego (ADR-0027). Composed-path seal (the DoS proof, red-first): a
join with a required denial must FAIL-AND-RELEASE — observed on the invocation lifecycle state
(terminal, not backing-off), exactly like the Slice-1b Situation-C seal, never assumed.
