---
id:         cortex-client-file-vs-table-reads
status:     open
owner:      agent
blocked-on: A MEASUREMENT, not a ruling. The shape is decided (uniform lazy API + pushdown + a tables-only query() escape hatch + refuse-don't-materialize). What is unknown is the pushdown COVERAGE — what fraction of real notebook operations translate to SQL — which sizes the work and decides whether "1-lite" (filter/select/limit/simple aggs) is sufficient or the full translation layer is needed. Measure the residual before building for it.
closed-by:  
code-site:  dag_tools/cortex_data/client.py
repo:       dag-tools
summary:    ONE API HIDING A FIVE-ORDER-OF-MAGNITUDE CLIFF. get_dataframe() returns a LazyFrame for every asset, but file-backed assets get real pushdown while table-backed ones already ran SELECT * and wrapped the result in .lazy(). The same five lines are milliseconds against a 40GB parquet asset and an OOM against a large Postgres one. "The user does not have to care" is currently true only until it hurts. DECIDED SHAPE: keep the uniform API, make tables genuinely lazy via pushdown, add a tables-ONLY query() escape hatch, and refuse rather than silently materialize at the pushdown ceiling.
---

# `get_dataframe()` returns the same type for two very different costs

**Found 2026-08-27**, working out what notebook code becomes when it moves into an agent. The
distinction predates all of that work and is independent of it.

## The cliff

```python
lf = client.get_dataframe(URN)
df = lf.filter(...).select(...).head(20).collect()      # identical for both
```

| | file-backed | table-backed |
|---|---|---|
| how | `scan_parquet` → a real query plan | `read_database_uri` → `SELECT *` → `.lazy()` |
| when data moves | at `.collect()`, only what is needed | **before you ever see the LazyFrame** |
| cost scales with | what you asked for | **the whole table** |

`docs/cortex-data-client.md` already states it honestly — *"for the two database backends that
is a `.lazy()` wrapper around an already-materialized DataFrame"* — but the **type system says
they are the same thing**, and the type is what people code against.

**A uniform interface concealing a cliff is the failure this fleet keeps finding.** The user
"not having to care" today means "not knowing until it hurts," and the population about to
inherit this — dozens of analysts writing code meant to survive into production — is exactly
the one that walks off an unlabeled edge.

## Decision (shape agreed 2026-08-27)

**Keep one API. Make it true rather than cosmetic.**

```python
lf = client.get_dataframe(URN)          # every asset. pushdown does its best.
lf = client.query(URN, "SELECT ...")    # TABLES ONLY. the escape hatch.
```

**1. Uniform lazy interface, with real pushdown for tables.** Translate the LazyFrame's
operations into SQL — `.filter` → `WHERE`, `.select` → projection, `.head(n)` → `LIMIT n`,
simple aggregations → `GROUP BY`. The user genuinely never cares, because the semantics really
are uniform. This is the only option where "don't care" is a fact rather than a hope.

**2. A tables-only `query()` escape hatch.** Pushdown has an honest ceiling — window
functions, complex joins, dialect-specific expressions do not translate. Without an exit, a
user at the ceiling gets a refusal pointing nowhere, or silent full materialization. With it,
the refusal is *teachable*.

**`query()` exists only where the backend can execute it, and that restriction is the point.**
SQL against a table is native: it runs where the data lives, it *is* the pushdown, and the
database enforces whatever RLS and column grants the minted role carries. SQL against a
parquet file would mean the client spinning up DuckDB locally to fake it — a query engine
masquerading as an asset property, with entitlement narrowing back on the client side. A user
calling `query()` on a file-backed URN gets a refusal naming the reason, which teaches the
file/table distinction **once, at the moment it matters**, rather than in documentation nobody
reads.

### Three pins, so the flexibility does not rot into inconsistency

**Pin 1 — both paths go through the same ticket.** `query()` is not a side door: same broker,
same minted credential, same entitlements. On `mint-role` backends the database enforces the
narrowing regardless of what SQL the user writes, and **that is what makes a raw-SQL escape
hatch safe to offer at all.** [[broker-advertises-unminted-credential]] paying out — this
would have been unshippable while tickets carried the producer's writing credential.

**Pin 2 — the pushdown ceiling REFUSES; it does not silently materialize.** When a plan
contains an unpushable operation over a size bound, name the operation and point at `query()`.
A silent fallback to full materialization is the cliff returning, wearing the uniform API.

**Pin 3 — `query()` results are bounded too.** A hand-written `ARRAY_AGG(DISTINCT ...)` from a
notebook has the same failure mode as any other unbounded result. Same byte bound, same
refusal wording, same guidance toward a lower-cardinality aggregate.

## What is actually unknown

**Only the coverage.** Full translation is real engineering; "1-lite" —
filter/select/limit/simple aggregations — plausibly covers most notebook exploration. Whether
it does is **measurable**: instrument real notebook operations and count what fraction
translates.

Measure the residual before building for it. That number sizes the work and decides whether
the escape hatch is the rare exit or the common one.

## Alternatives rejected

- **Status quo, documented loudly.** The unacceptable resting state. The cliff stays; it just
  gets a label, and labels lose to types.
- **Different return types by backend.** Honest, and pushes the distinction into every notebook
  — the coupling the client exists to hide, and the thing that breaks the notebook→production
  path.
- **`query()` everywhere, DuckDB for files.** A query engine impersonating an asset property,
  and it moves entitlement narrowing back client-side.

## Acceptance

- A `.filter().head(20)` against a large table transfers a bounded result, not the table.
- An unpushable operation over the bound is **refused with the operation named and `query()`
  offered** — not silently materialized.
- `query()` on a file-backed URN is refused with the reason.
- `query()` results obey the same byte bound as `get_dataframe()`.
- On a `mint-role` backend, a user who writes hostile SQL through `query()` still sees only
  their entitled rows and columns.

## The ADR-shaped sentence underneath

> **A uniform interface must be uniform in COST, or it is a cliff with good manners. Where
> the costs genuinely differ, the interface either closes the gap or refuses in a way that
> teaches — never papers over it with a type.**
