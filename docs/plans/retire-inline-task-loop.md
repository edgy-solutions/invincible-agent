---
id:         retire-inline-task-loop
status:     open
owner:      unassigned
blocked-on: 
closed-by:  
code-site:  agent_fleet/restate_analyst/main.py
repo:       invincible-agent
summary:    CLEANUP-GRADE (security read done 2026-08-10, outcome: not a fix). BPMNWorkflowRunner accepts a client-supplied definition, but WorkflowStartRequest drops the field and the ingress is ClusterIP — in-cluster only. ADR-0029's retirement condition is met; residual in-cluster risk folded into undeclared-routes.
---

# Retire the inline task loop — its condition is now met

**Verified live 2026-08-10**, `agent_fleet/restate_analyst/main.py:2009`, inside
`@bpmn_workflow.main()`:

```python
# ADR-0029 Slice 1 (ADDITIVE): a git-asserted SPO-native WorkflowDefinition
# drives the run when `definition` is present. The sealed inline-task loop
# below is UNTOUCHED — it retires only after the definition path seals.
if request.get("definition"):
    return await _run_definition(ctx, workflow_id, request["definition"], request)
tasks = request.get("tasks", [])
```

## Why this is filed now rather than as a cleanup

**The retirement was conditional, and the condition has been satisfied.** ADR-0029 Slice 1 landed the
definition path additively and stated plainly that the inline loop "retires only after the definition
path seals." That path has now sealed — `dispatch_fanout`, escalation, the placeholder binder, the
retry taxonomy, and the ceremony's completion witness all ran through `_run_definition` against
git-asserted definitions.

So this is not a new proposal. It is a **decided retirement whose trigger fired and which nobody
re-read the decision to notice.** That is exactly the class ADR-0040's migration names as its most
expensive: rules already decided and never indexed get re-derived from scratch, sometimes to a
different answer.

## What is actually at stake

`request["definition"]` accepts a **client-supplied process**. The review workflows do not use it —
`GroupedReview` and `AutonomousReview` both load from the runtime registry, and
`autonomous_review_workflow.py` says why in load-bearing prose:

> *A client-supplied process is exactly the laundering the stage-2 verifier exists to prevent — and
> on THIS path it would be worse than on workflow 1's, because here there is no human step between
> the request and the effect.*

**Scope, stated precisely rather than alarmingly:** the accepting handler is `BPMNWorkflowRunner`, a
different service from the review workflows, and this read did **not** establish who can invoke it or
under what gate. That is the first question of the work, not a conclusion of the filing. What is
established is that the seam the docstring calls laundering-shaped is still open on one runner, and
that its documented retirement condition is met.

## SECURITY READ — asked and answered, 2026-08-10 (outcome: cleanup, not a fix)

Recorded so the next reader does not re-derive it. **`request["definition"]` is not externally
reachable, and the one externally-adjacent route structurally cannot carry it.**

| path to `BPMNWorkflowRunner.run` | can it carry `definition`? |
|---|---|
| engine-a `POST /workflow/start` | **No** — the body is built explicitly (`workflow_id`, `tasks`, `user_jwt`) and `WorkflowStartRequest` declares no `definition` field, so Pydantic drops it before the route sees it. |
| direct POST to the Restate ingress | **Yes**, but the ingress is `ClusterIP` with no Ingress object. |

`iagent-restate` and `iagent-engine-a` are both `ClusterIP`; the cluster's six Ingress objects are
`datahub`, `cortex-bff`, `cortex-ui`, `dagster`, `keycloak`, `minio` — neither is among them.

**So this stays cleanup-grade.** The residual risk is the already-ratified-nowhere posture that *any
in-cluster pod can call it* — the same question `undeclared-routes` holds, and this is one more row
that inherits whatever it decides.

## The work

1. ~~Read who can reach `BPMNWorkflowRunner.run` and under what capability.~~ **DONE 2026-08-10 —
   see the security read above. Outcome: cleanup-grade, in-cluster only.**
2. Enumerate live callers passing `definition`. Partially done: no in-repo caller constructs it —
   `/workflow/start` builds its body explicitly and cannot, and the review workflows load from the
   registry by design. A direct Restate-ingress caller remains possible in-cluster.
3. Remove the branch, or — if a caller genuinely needs it — gate it and record why, in the
   expand/contract shape rather than as an edit.
4. Seal it: a request carrying `definition` must be **refused**, not silently honoured.

## Related

- ADR-0029 — the additive landing and the stated retirement condition.
- ADR-0039 — the definition schema; a retired inline path removes the second way to express a process,
  which is the same one-home argument the schema decision rests on.
