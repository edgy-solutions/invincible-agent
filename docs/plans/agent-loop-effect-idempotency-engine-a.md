---
id:         engine-a-loop-idempotency
status:     parked
owner:      human
blocked-on: design window (reserved)
closed-by:  
repo:       invincible-agent
summary:    Non-idempotent Superset write inside the agent loop. FILED NOT FIXED; the packet forbids attaching it to a durability session.
---

# LEDGER ITEM — agent-loop effect idempotency (Engine A)

_Status is in this packet's YAML header — the single authority (ADR-0040). The prose
status line that stood here was removed when the header landed: two declarations of one
status is the two-homes defect, and a generated board reading the header would have
silently disagreed with a reader trusting the prose._

**Provenance.** Found 2026-08-05 while enumerating effects for the Engine D durability fix, under a
packet that named the wrong service. The scope was contaminated; the enumeration was not. This is
the founding evidence, recorded before the finding decays into "we should look at Engine A sometime".

**Filing note.** The parent packet cites `sessions/2026-08-05-replay-double-fix.md`, which does not
exist on disk and has never been tracked in git (`git ls-files sessions/` is empty in every repo
under `~/git`). The authoritative record for the boundary contract is instead the **PLACEMENT
MARKER** comment block in `baml_shared/telemetry.py` (above `mint_boundary_ids`), which is in-code,
committed, and complete. Cite that.

---

## The finding

`analyze` (`agent_fleet/restate_analyst/main.py:535`) wraps its entire smolagent run in ONE journaled
step — `ctx.run("run-smolagent", ...)` at `main.py:1290`. Inside that step an LLM chooses tools; the
number, order and identity of the external calls are decided at runtime and vary per execution.

### Effect enumeration — Engine A `analyze` (verbatim, as measured)

| effect | where | idempotent? |
|---|---|---|
| `resolve_ontology` → Engine O | `ctx.run`, top level | yes (read) |
| `deterministic-trace-lineage` → Engine D | `ctx.run`, top level | yes (read) |
| `save-memory` → mem0 `m.add` | `ctx.run`, top level | **no** (appends) |
| `search_datahub` → D `/query_metadata` | **inside** `run-smolagent` | yes (read) |
| `fetch_user_memory` → mem0 `m.search` | **inside** | yes (read) |
| superset `preview` → `/sqllab/execute` | **inside** | depends on the SQL |
| superset `publish` → `POST /dataset/` **+** `POST /chart/` | **inside** | **no — creates two resources** |

Nothing at the top level runs unwrapped. `save-memory` survived the June work AND is wrapped
(`main.py:1369`). **The exposure is one level down.**

### Why step-wrapping is RULED OUT here

Restate memoizes *completed* steps. A step that dies mid-way re-runs **from the start** — so a crash
after the agent published a chart but before `run-smolagent` returns publishes a second one.

The obvious repair — wrap each tool call in its own `ctx.run` — is **ruled out**, and this is the
part that needs to be written down before someone tries it:

> The tool sequence is chosen by the LLM and is not stable across replays. Restate's journal assumes
> a deterministic step order. Per-tool `ctx.run` inside a non-deterministic loop converts replay
> divergence from a wasted call into a **correctness bug**.

So the primitive is **idempotency keys derived from journaled inputs**, not wrapping.

### The named anti-pattern

`agent_fleet/restate_analyst/main.py:879`:

```python
ds_payload = {"database": database_id, "table_name": f"tmp_{int(time.time())}", "sql": sql_query}
```

Non-deterministic **by construction**. Even a deliberate retry cannot dedupe against it, because
every attempt invents a new name. Any fix starts by making that name a function of journaled inputs.

### The design question this item exists to answer

**Plan-in-loop / execute-post-loop.** Two shapes, and the choice is architectural:

- **(a) Idempotency keys, effects stay in the loop.** Each non-idempotent tool derives a
  deterministic key from journaled inputs and the remote deduplicates. Smallest diff; requires every
  effectful endpoint to *support* an idempotency key (Superset's chart/dataset APIs do not, today).
- **(b) The agent PLANS, the handler EXECUTES.** The loop returns a *description* of the effects to
  perform; the handler performs them after the loop, each in its own `ctx.run`, in a now-deterministic
  order. Restores journal determinism by construction and makes the effects reviewable before they
  happen — which is also the shape the SPO/eligibility work already prefers. Costs a tool-contract
  change and a redesign of `superset_analytics_manager`'s `publish` action.

(b) is the better fit for this codebase's existing posture (*select from an authorized set*,
*emit-don't-only-detect*), but it is a real design change and is explicitly **not** to be decided by
whoever next touches durability.

### Blast radius — the shape has TWO homes

The coarse-`ctx.run`-around-an-LLM-loop is a class with two instances, not one:

| | Engine A | Engine E |
|---|---|---|
| coarse `run-smolagent` step | `restate_analyst/main.py:1290` | `neo4j_expert/service.py:935` |
| boundary ids / emit | 1275 / 1291 | 923 / 936 |
| `save-memory` | 1369 | 1035 |
| agent tools making external calls | 3 | 5 |

Matches the framing in `433281f` — *"the copy follows its source."* The **non-idempotent Superset
publish is Engine A only**; Engine E's five tools are graph-read-shaped but have **not** been
classified. Classify them before assuming E is safe.

### What is NOT wrong here

Engine A and E are *correctly* wrapped for the replay-double hazard the telemetry arc fixed — they
already use the three boundary primitives. This item is about **effect duplication inside the
step**, which is a different failure from **span duplication around it**. Do not conflate them: the
telemetry fix is done and correct; this one is not started.
