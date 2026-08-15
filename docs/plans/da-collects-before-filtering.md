---
id:         da-collects-before-filtering
status:     open
owner:      agent
blocked-on: nothing — the defect is two lines and the repair is a design choice about WHERE the query executes.
closed-by:
code-site:  agent_fleet/data_analyst/main.py:432
repo:       invincible-agent
summary:    `SELECT ... LIMIT 2` reads the ENTIRE table into RAM. `get_dataframe` returns a LazyFrame so scans can push down projections and limits, and `.collect()` discards that one line later — so memory is a function of the DATASET, never of the query. OOM-killed Engine DA at work 2026-08-14 on a two-row read.
---

# Asking for two rows required more RAM

```python
lazy_df = client.get_dataframe(urn)   # a LazyFrame — pushdown is the whole point
dataset = lazy_df.collect()           # ← the entire table, every row, every column
con.register("dataset", dataset)
result_df = con.execute(sql_query).pl()   # only NOW does LIMIT 2 apply
```

`data_analyst/main.py:432-442`. `CortexDataClient.get_dataframe` returns `pl.LazyFrame`
precisely so `scan_parquet` can push projections and limits into the read. Collecting it
immediately throws that away and hands DuckDB a fully-materialized frame to filter.

**Witnessed at work 2026-08-14 20:12.** `SELECT cage_code FROM dataset LIMIT 2` OOM-killed the
DA pod. The supervisor saw `RemoteDisconnected` after 28s — with 1800s timeouts on both hops,
so nothing timed out; the process died. Raising DA's memory made that query work.

## Why raising RAM is not the fix

Memory required is set by the table, not the question. The next larger dataset OOMs again at
any limit, and the failure arrives as a dropped connection rather than an error — see
[[ui-renders-honest-failure-as-answer]], where a crashed subtask skips `generate_ui_payload`
entirely and the user gets a blank card. So the symptom is maximally confusing and maximally
far from the cause.

It also makes the whole data path's cost unpredictable in the one dimension a user controls:
a careful `LIMIT 2` and a reckless `SELECT *` cost exactly the same.

## The repair is a choice about where the query runs

1. **Let DuckDB read the parquet directly.** It can scan S3 with the ticket's credentials, so
   the whole query — projection, filter, limit — executes in the engine that was given SQL,
   and nothing is materialized in polars first. Most direct; needs the ticket's credentials
   wired into a DuckDB S3 secret.
2. **Keep it lazy in polars.** `pl.SQLContext` over the LazyFrame, collect only the RESULT.
   Smaller change, keeps one engine, and preserves pushdown.
3. **Bound it** — a mandatory `LIMIT` ceiling and a projection derived from the query. A
   mitigation, not a fix: it caps the blast radius while memory still scales with the table.

(1) or (2) are real fixes. Worth checking whether the access-denial handling around
`get_dataframe` still behaves under either, since `_is_access_denied` currently keys off the
exception raised at collect time — a lazier path may move where that surfaces.

## Related

- [[ui-renders-honest-failure-as-answer]] — why this presented as an empty card rather than an
  error, and why the user spent an evening looking for lost values that had never been
  computed.
- [[da-schema-affordance]] — the same tool, the other missing affordance: the agent has no
  schema, so it also cannot write a well-projected query even when pushdown works.
