---
status: HALF MEASURED — native side closed, browser side awaiting one reload
date: 2026-09-05
engine: engine-cost
---

# Slice 2 fidelity fork — DuckDB DECIMAL → Pyodide `decimal`

**Measured before anything was built on it**, per the dispatch's own ordering. The fork has
two halves and only one is answerable from Python.

## Half one — native DuckDB: CLOSED, exactly

63 real engine figures (every composition step and price across nine lots), written and read
back:

| variant | string-equal | python type returned |
|---|---|---|
| **`DECIMAL(20,2)`** | **63 / 63** | `Decimal` |
| `VARCHAR` + Python cast *(the dispatch's contingency)* | 63 / 63 | `str` |
| `DOUBLE` *(the leak being guarded against)* | **51 / 63** | — |

**The third row is the bite-check and it is the reason the first row means anything.** A probe
where every variant passes cannot tell a preserved decimal from a lucky one; here the DOUBLE
column corrupts 12 of 63 values, so the instrument demonstrably discriminates.

**String equality, not numeric.** `Decimal("1717367.65") == 1717367.65` can be False while the
floats compare equal — the manifest compares strings, so the probe does too.

**Consequence: the contingency is not needed on this half.** Native `DECIMAL` columns hold, so
the `.duckdb` is a typed store rather than "a container of typed text and Python casts".

## Half two — duckdb-wasm → Arrow → JavaScript: NOT YET MEASURED

**This is where a double is most likely to leak, because JavaScript has no decimal type.**
Arrow carries `Decimal128`, but what a JS consumer receives depends on how the binding
surfaces it — and a leaked double prints plausibly and compares wrong, which is the worst
available failure.

`dist/slice2-fidelity-probe.html` (1.7 MB) answers it: it reads the real `.duckdb` through
duckdb-wasm and string-compares all 75 result rows against the engine's own figures.

**The probe loads duckdb-wasm FROM A CDN, deliberately.** It is a measurement, not a shipped
artifact — the no-CDN rule governs what a recipient receives, and paying 35 MB of embedding to
answer a yes/no question spends the wrong budget. It says so on its own face so it cannot be
mistaken for a package.

## A SIZE FINDING THAT BELONGS IN FRONT OF THE BUILD

**duckdb-wasm is 34 MB** (`duckdb-eh.wasm`), plus a 0.7 MB worker.

| bundle | raw | as embedded base64 |
|---|---|---|
| slice 1 (Pyodide only) | 14 MB | **17.6 MB** — clears most mail gateways, none comfortably |
| slice 2 (Pyodide + duckdb-wasm) | ~49 MB | **~65 MB** — clears no mail gateway at all |

**This is a format decision, not an implementation detail**, and it is surfaced before the
build rather than discovered at the end of it. Three honest options:

1. **Accept ~65 MB.** The artifact stops being emailable and becomes a file-transfer
   deliverable. The double-click property survives; the "send it to them" property does not.
2. **Do not embed duckdb-wasm.** The dispatch's own constraint is *data layer only, no
   arithmetic in SQL* — so at READ time the browser is doing selection and grouping, which
   Pyodide can do over embedded rows. The `.duckdb` would remain the authoring and interchange
   format without being the runtime one. **Bundle stays ~18 MB.**
3. **Ship the `.duckdb` beside the HTML** rather than inside it. Two files, no embedding cost,
   but the single-artifact property — the thing that makes it survive being forwarded — is
   gone, and a recipient with only the HTML gets a broken page.

**Not chosen here.** Option 2 is the one that preserves both properties, but it declines an
explicit instruction ("read via duckdb-wasm, embedded"), so it is the architect's call rather
than the lane's.
