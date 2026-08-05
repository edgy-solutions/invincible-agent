# Engine D durability — WITNESSED GREEN

One session, one service, one fix, one witness. Closed.

## The result

Identical manufacture, identical query, same pod-alive conditions. **The only variable is the code.**

| | BEFORE (unfixed) | AFTER (fixed) |
|---|---|---|
| agent executions (`DA_FUMBLE_METRIC`) | **2** | **1** |
| boundary spans (`SPAN::data analyst`) | **2** | **1** |
| replay actually manufactured (`DA_SEAL`) | 1 | 1 |
| wall clock, one invocation | 42.5s | 31.3s |
| trace | `b8f2df5b…` | `8cfa2942…` |

`DA_SEAL` = 1 on **both** sides is the positive control: the replay fired in the after-run too, so
the single execution is durability working, not the manufacture failing to trigger.

The span count is **1, not 0** — the boundary still emits. Distinguishing those two was necessary:
a silent fallback to the no-op telemetry stubs would also have produced "fewer spans" and read as
success. Checked in the running image before the witness:

```
mint_boundary_ids.__module__ = telemetry
mint_boundary_ids('probe-seed') = {'trace_id': 'b83a8046...', 'span_id': 'a80048e4...'}
```

A real 32-hex trace id, not the stub's `None`. Post-disarm, a normal invocation returns 200 in
31.0s — the fix is not load-bearing on the scaffolding.

## What the marker predicted, and what it got right

> D is a Restate handler that runs its agent work OUTSIDE any `ctx.run`, so replay re-executes the
> work for real and its boundary span count stays honest by accident: the doubling is absent only
> because the waste is genuine.

Confirmed exactly. Pre-fix, 2 spans for 2 executions — the count was honest *because* the waste was
real. Post-fix, 1 span for 1 execution, but now for a different reason: the boundary is
non-recording and journaled, so it *cannot* double. **The span count stopped being an execution
counter at the moment it stopped needing to be one** — which is why the witness instrument is
`DA_FUMBLE_METRIC` (stdout, emitted by the work itself), with spans corroborating.

## The methodological finding — a pod kill cannot measure this

The first manufacture attempted was the obvious one: delete the pod mid-handler. Restate does
retry — witnessed, a handler killed at t=5s returned 200 after 30.6s total. But the trace showed
**ONE span for TWO executions**, because the killed pod's OTel batch exporter never flushed.

> **The instrument shared a fate with the thing being killed.**

It undercounts in precisely the scenario it exists to measure, and it undercounts *silently*: one
span looks like one execution looks like healthy. Had the fix already been in place, that identical
reading would have been indistinguishable from success — **a false-green built into the method
rather than the code**. That is why the seal manufactures the replay by FAILING after the work
(`DA_SEAL_FAIL_AFTER_WORK`, env-gated, default off) instead of by killing: the process survives, so
stdout, the exporter and the journal all report honestly, and it is deterministic rather than a
timing race against a 12–42s LLM round-trip.

## The trap the fix had to avoid

`sources_collected`, `access_denials` and the fumble metric are produced as **side effects inside
the agent loop** and read **after** it. A `ctx.run` returns its memoized value and does not
re-execute the body — so wrapping `agent.run` alone would, on every replay, return the right answer
with an **empty provenance trail**, and an empty `access_denials` would turn a genuine 403 into a
reported success.

A correctness regression introduced *by* the durability fix, and a silent one. The step now RETURNS
its outputs and the handler re-hydrates from the return value. This is the concrete payoff of
running item 0 (read-only enumeration) before writing any code.

## Scope discipline

- **Engine A was NOT touched.** Its coarse `run-smolagent` wrap has a non-idempotent write inside
  the loop (Superset `publish` → `POST /dataset/` + `POST /chart/`) and per-tool wrapping is ruled
  out. Filed as `docs/plans/agent-loop-effect-idempotency-engine-a.md` — needs design, not a rider.
- **The scaffolding stays in the code**, env-gated and default-off, matching `dispatch_driver`'s
  `PCN_SEAL_PAUSE_AFTER_*` precedent. It is disarmed in sandbox (`DA_SEAL_FAIL_AFTER_WORK` unset).
- **Pre-existing residue, not mine:** a `DataAnalystService/analyze_data` invocation has been
  `paused` since **2026-06-01**. Untouched; flagged for whoever owns the Restate retry-policy item.

## Commits

- `afb8cc7` scaffolding — manufacture by failing, not by killing (with the measurement that ruled
  the pod-kill out)
- `e8bd08d` durable execution + replay-safe boundary, landed together per the marker
- this document — the witness
