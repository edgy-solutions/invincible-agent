# Engine D durability — item 0: effect enumeration (READ-ONLY)

**Verdict: step-wrapping HANDLES this topology. No stop-and-report. Proceed to the fix.**

That verdict is the whole point of running item 0, and it lands the OPPOSITE way from the same
enumeration on Engine A. The difference is one fact, and it is worth stating before the table:
**D's only in-loop external effect is an idempotent READ.**

## Identity confirmed

`agent_fleet/data_analyst/main.py` — `Service("DataAnalystService")`, handler `analyze_data`
(line 150). **Zero `ctx.run` in the source** (`grep` hits are all vendored `.venv`). That is the
identifying fact from the placement marker, and it holds.

The marker (`baml_shared/telemetry.py`, above `mint_boundary_ids`) named this service by path and
predicted its state exactly:

> D is a Restate handler that runs its agent work OUTSIDE any `ctx.run`, so replay re-executes the
> work for real and its boundary span count stays honest by accident: the doubling is absent only
> because the waste is genuine.

## The enumeration

| # | effect | leaves the pod? | idempotent? | notes |
|---|---|---|---|---|
| 1 | `observed_trace(...)` (`main.py:436`) | yes — Langfuse ingest | **no** — RECORDING span, fresh id per entry | the replay-double hazard, currently masked |
| 2 | `agent.run(...)` LLM round-trips (`main.py:442`) | yes — LiteLLM → model host | **no** (cost-bearing) | the expensive one; the external counter |
| 3 | `query_datahub_asset` → `CortexDataClient.get_dataframe(urn)` (`main.py:350`) | yes — `CENTRAL_GATEWAY_URL` | **YES — pure read** | the fact that makes D wrappable |
| 4 | `duckdb` register + execute (`main.py:372-377`) | **no** — in-process | n/a | local, dies with the pod |
| 5 | `print()` fumble/config metrics | **no** — stdout | n/a | log only |
| 6 | `sources_collected` / `access_denials` mutation | **no** — in-memory | n/a | **see the replay trap below** |

**There is no mem0 write in D.** The parent packet's witness criterion ("one mem0 write not two")
is an Engine A fact that rode along with the contaminated scope; struck. D's witness instrument is
the **LLM call count** (#2), with the gateway read count (#3) as a corroborating second signal.

## Why D is wrappable and A was not

Engine A's loop contains a **non-idempotent write** (Superset `publish` → `POST /dataset/` +
`POST /chart/`), so re-running a partially-completed step duplicates real resources — and per-tool
wrapping is ruled out because the tool order is LLM-chosen. D's loop contains exactly one tool, and
it is a **read**. Re-running it mid-step costs a duplicate query and nothing else.

So the coarse single `ctx.run` around `agent.run` — the shape that is a liability in A — is
**correct** in D. Same structure, opposite verdict, because the verdict is a property of the
EFFECTS, not of the shape.

## The replay trap the wrap must not create

`sources_collected` and `access_denials` are populated **as a side effect of the tool**, inside the
agent loop, and are read AFTER it (`main.py:452, 470, 476`) to build the response.

A `ctx.run` returns its **memoized value** on replay and does **not** re-execute the body. So
wrapping `agent.run` alone would, on every replay, produce:

- `agent_result` — correct (from the journal)
- `sources_collected` — **empty**, because the tool never ran again to append to it
- `access_denials` — **empty**, so a genuine 403 would silently become a success response

That is a correctness regression *introduced by the durability fix* — the response would lose its
provenance trail and, worse, an access denial would stop being surfaced. **The wrapped body must
RETURN these, not mutate them through a closure.** Same class as `_emit_fumble_metric`
(`main.py:408`), which reads `agent.memory.steps` and would report `steps=0` on a replayed run.

This is the specific thing to get right in item 2, and it is why the enumeration was worth doing
before the wrap rather than after.

## Fix shape (item 2), per the marker's convention

The marker states the rule:

> * a **LEAF** span (parents nothing) goes INSIDE `ctx.run`;
> * a **PARENTING BOUNDARY** uses these primitives — journaled ids, non-recording ambient parent,
>   boundary emitted from its own `ctx.run`.

D's `observed_trace` **parents** the agent's generations, so it is a BOUNDARY. The fix is the shape
Engines A and E already carry (`restate_analyst/main.py:1275-1295`,
`neo4j_expert/service.py:923-936`):

```
_ids   = await ctx.run("mint-analyst-boundary-ids", lambda: mint_boundary_ids(trace_id))
_vals  = build_trace_values(...)
with boundary_parent(_ids) as _timing:
    payload = await ctx.run("run-agent", run_agent)      # returns result + sources + denials
await ctx.run("emit-analyst-boundary",
              lambda: emit_boundary(MAPPING, _vals, ids=_ids, name="data analyst", timing=_timing))
```

Two effects land together and must not be separated: the **work becomes durable** (it stops
re-running) and the **boundary stops double-emitting** (non-recording ambient parent). The marker's
warning is that whoever adds the first inherits the second's hazard at the same moment — so both
arrive in one commit.
