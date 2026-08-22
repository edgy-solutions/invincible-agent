---
id:         engine-da-ooms-on-a-plausible-question
status:     closed
owner:      agent
blocked-on:
closed-by:  d06da52
code-site:  agent_fleet/data_analyst/main.py, helm/invincible-agent/values.yaml
repo:       invincible-agent
summary:    ✅ CLOSED 2026-08-22 by d06da52 — the `.collect()` is gone, the lazy frame reaches DuckDB, and a cell-count gate refuses an unfittable table by name instead of dying on it. The reproducer now returns a REAL ANSWER (a CHART_WIDGET of distinct cage codes per company) and the gate never fired, which proves `p_cage` was never too large: the OOM was ENTIRELY the discarded laziness, not an unfittable dataset. Restart count 0 across 12 minutes / 9 samples, against a predecessor that died 10 times. Was: ⚠️ DEMO BLOCKER, diagnosed 2026-08-22. Engine DA is OOMKilled (exit 137, `Reason: OOMKilled`, 2Gi limit) executing an ordinary analytical question — `SELECT company, ARRAY_AGG(DISTINCT cage_code) FROM dataset GROUP BY company` over a publog table. It crashed MID-STEP on a real user question and the pod has been in CrashLoopBackOff; the previous pod restarted 15 times in 173 minutes. THE FAILURE IS SILENT FROM THE UI: routing succeeds and reports high confidence, the answer card renders with its title, and the body is empty with "No citations yet" — because the engine died before returning anything. An error would be better; this looks like an answer.
---

# Engine DA dies on a question a room would actually ask

Found while a prime was running, by chasing a restart count nobody had looked at.

## The reproducer is a real question that was really asked

```
Q: give me the distinct cage codes per company from publog's p_cage
routing: analyze Dataset · Engine DA · high confidence
```

Engine DA's own log, from the container that died:

```
Executing parsed code:
  result = query_datahub_asset(
      urn="urn:li:dataset:(urn:li:dataPlatform:s3,iagent-minio.publog-lake/publog/p_cage,PROD)",
      sql_query="""
          SELECT company, ARRAY_AGG(DISTINCT cage_code) AS cage_codes
          FROM dataset GROUP BY company ORDER BY company;
      """)
  print(result)
```

…and the log ends there.

```
Last State: Terminated   Reason: OOMKilled   Exit Code: 137
Limits: cpu 1, memory 2Gi     Restart Count: 2 (and 15 on the pod it replaced)
```

## Why this outranks its size

**The UI cannot tell this from a thin answer.** Routing resolved, confidence was high, the card
rendered its title and headline, and `Sources & Evidence` said *"No citations yet. Evidence
appears as engines return matches."* — which is literally true and reads like patience rather
than death. In a room, that is a confident-looking blank, and the presenter has nothing to point
at. **An honest error would be strictly better than this.**

It also cost real diagnostic time in the wrong place: the blank card surfaced the same hour as a
presentation-registration failure, and was initially attributed to `select_presentation`
refusing an unregistered archetype. That was wrong — `analyze Dataset` routes to
`mesh:DatasetAnalysisReport` → `CHART_WIDGET`, which has been registered throughout. Two failures
surfacing together are not one failure.

## Cause

~~`ARRAY_AGG(DISTINCT …) GROUP BY …` over a wide publog table … 2Gi is not enough for a wide
aggregation over a large table.~~ **FALSIFIED 2026-08-22 by the fix.** That sentence implied the
DATA was too big. It was not: after `d06da52` the same question returns a real answer, and the
size gate **never fired** — `p_cage` was comfortably inside the ceiling all along.

**The cause was purely the discarded laziness**, exactly as the mechanism section below (added
later, after reading the code) states: the entire source table was materialised before the
`GROUP BY` that would have shrunk it. Nothing about the dataset was oversized; the code simply
refused to let Polars do what it was handed a LazyFrame to do.

This distinction is worth more than a corrected sentence: **raising the memory limit would also
have "worked"** — and would have permanently hidden the fact that the query never needed that
memory. Disposal 2 was ranked third for a reason, and this is the evidence that the ranking was
right rather than cautious.

Two aggravating facts found alongside:

- **The readiness probe is the same defect as the BFF** — `/health` with a 1s timeout, failing
  with `context deadline exceeded` — so a busy analyst also flaps out of the endpoint list. See
  [`bff-liveness-probe-kills-under-load`](bff-liveness-probe-kills-under-load.md); this is the
  second engine with it, which makes it a chart-wide default rather than one service's mistake.
- **Restarts were invisible.** The previous pod restarted 15 times in 173 minutes while the
  surface looked healthy, and nothing surfaced it until someone read a pod list by hand.

## The mechanism, read from the code (`main.py:417` `query_datahub_asset`)

```python
lazy_df = client.get_dataframe(urn)     # LAZY — the client hands back a LazyFrame
dataset = lazy_df.collect()             # (1) MATERIALISES THE WHOLE SOURCE TABLE
con.register("dataset", dataset)
result_df = con.execute(sql_query).pl()
return result_df.write_json()           # (2) serialises the WHOLE result into the LLM context
```

**Two materialisation points, and the first is the bigger one.** `get_dataframe` returns a
LAZY frame — exactly the shape that would let a `GROUP BY` be pushed down and never hold the
source table whole — and the next line collapses it with `.collect()`. The laziness is
acquired and immediately discarded, so peak memory is the SOURCE TABLE, not the result. A
question whose *answer* is a few hundred rows still pays for every row of `p_cage`.

The second point matters for a different reason: `write_json()` puts the entire result set into
the agent's context, so a large-but-fitting result becomes a token problem after it stops being
a memory problem.

**This is why "raise the limit" only moves the cliff:** the memory needed is a property of the
source table, not of the question, so the next wider table finds the new limit too.

## Disposal

0. **Stop discarding the laziness** (`main.py:463`). Cheapest real improvement: count rows
   first (`lazy_df.select(pl.len()).collect()` is cheap), refuse above a threshold with a named
   reason, and let DuckDB read the lazy frame so an aggregation is pushed down rather than
   materialised. This is where the 2Gi actually goes.
1. **Bound the result set in the engine.** The other half. An analytical engine should refuse or
   page a query whose result will not fit, and say so — the honest-degradation path this
   codebase already has for undrawable payloads, applied to unfittable ones. A `LIMIT`-injection
   or row-count precheck turns an OOM into an answer.
2. **Raise the memory limit.** Cheap, buys headroom, and moves the cliff rather than removing
   it — the next wider table finds it again.
3. **Fix the probe defaults** (shared with the BFF packet) so a busy engine is not also an
   unready one.

**Do 0, then 1.** 0 is where the 2Gi actually goes and is the smaller change; 1 stops a
large-but-fitting result becoming a token problem instead. Do 2 as well if the demo is close —
and say out loud that it is a mitigation, because it moves the cliff rather than removing it.

## Acceptance

The reproducer question above returns either an answer or an explicit refusal naming the size
limit — never an empty card. Restart count on the deployment stable, read twice with a gap.

---

# CLOSED 2026-08-22 — `d06da52`

## What the fix was

`main.py` acquired a LAZY frame and discarded it one line later:

```python
lazy_df = client.get_dataframe(urn)   # pl.scan_parquet — lazy
dataset  = lazy_df.collect()          # the ENTIRE source table, in memory
con.register("dataset", dataset)      # only NOW does the GROUP BY run
```

The `.collect()` is gone. DuckDB is handed the LazyFrame directly (verified
duckdb 1.5.5 / polars 1.43, with a test arm so a future version dropping support
goes red in CI rather than in a pod), and a size gate runs BEFORE the query.

**The gate counts CELLS, not rows** — this packet's own argument applied to its
own fix. Memory is a property of the table's SHAPE, not of the question, so a
row-only cap leaves the next WIDER table finding the same cliff, which is the
same reason option 2 (raise the limit) only moves it. A 1,000-row ×
1,000,000-column table is the case a row cap misses entirely; it has an arm.
Both numbers are cheap — row count pushes down to parquet metadata, the schema
IS metadata — so the guard does not cost what it prevents.

`SOURCE_TOO_LARGE` names the shape, the limit, and the remedy, and forbids retry:
an agent that retries an oversized query just OOMs again. A precheck that cannot
run is LOUD (`DA_SIZE_PRECHECK_FAILED … UNGATED`) rather than a silent bypass.

## The finding the fix produced

**The gate never fired, and the question returned a real answer.**

That is worth more than the repair. It proves `p_cage` was never too large: the
OOM was ENTIRELY the discarded laziness, not an unfittable dataset. Option 2
(raise the memory limit) would also have "worked" — and would have buried that,
leaving a mitigation in place of a fix and the real cause undiscovered until a
table that genuinely does not fit arrived.

## Acceptance — met, measured

| criterion | result |
|---|---|
| reproducer returns an answer or explicit refusal, never an empty card | ✅ **an answer** — CHART_WIDGET, distinct cage codes per company, with a source citation |
| restart count stable, read twice with a gap | ✅ `restarts=0` across 12 minutes, 9 samples (predecessor died 10×) |
| suite | ✅ 1674 passed, zero failures |

Confirmed alongside, unplanned: the answer card rendered as a **CHART_WIDGET**,
which is the graph-backed presentation path selecting
`DatasetAnalysisReport → CHART_WIDGET` from a registered menu. Two arcs witnessed
in one frame.

## NOT done — deliberately, and still open

* **Bound the RESULT set** (disposal step 1). This fix bounds the SOURCE. A
  large-but-fitting result still becomes a token problem after it stops being a
  memory problem.
* **Raise the memory limit** (step 2). Not taken. It moves the cliff, and the
  finding above shows it would have hidden the cause. Take it for headroom if a
  demo is close — and say out loud that it is a mitigation.
* **The readiness probe** (step 3, shared with
  [`bff-liveness-probe-kills-under-load`](bff-liveness-probe-kills-under-load.md)).
  Untouched. `/health` with a 1s timeout on BOTH engines makes it a chart-wide
  default rather than one service's mistake, so it should be fixed as a default.
