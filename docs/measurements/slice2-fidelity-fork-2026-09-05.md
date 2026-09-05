---
status: CLOSED — both halves measured, fork ruled (option 2), and slice 2 built on the ruling
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

---

# HALF TWO MEASURED — and the leak is a SCALE ERROR, not precision loss

```
LEAK - 75 of 75 values did not survive as exact decimals
  js typeof=object  value=630721000    engine=6307210.00
  js typeof=object  value=22481834     engine=224818.34
  js typeof=object  value=167334720    engine=1673347.20
STRING-EQUAL: 0 / 75
```

**Every value is the engine's value × 100.** `630721000` against `6307210.00`; `22481834`
against `224818.34`. **The digits survive intact.** duckdb-wasm returns the `DECIMAL(20,2)` as
an **unscaled BigInt** and nothing applies the scale — `typeof` is `object`, which is the
BigInt tell.

**So this is a READER defect, not a numeric one, and it is recoverable** — divide by 10^scale,
or read the scale from the Arrow field metadata. Which is precisely what makes it dangerous.

**WHY IT IS THE SECOND REASON TO REFUSE duckdb-wasm, INDEPENDENT OF SIZE.** A value that is
wrong by exactly 100× is *close enough to look like a rounding problem*. Had the probe used a
numeric tolerance — or compared `float(js) ≈ float(engine)` — it would have read as noise near
the boundary and been "fixed" with a tolerance somewhere. **String equality returned 0/75,
which is an unmissable signal, and the uniformity of the failure is what makes it diagnosable
as a scale error in one glance rather than a precision mystery.**

*A uniform extreme result is usually the tell of a broken instrument. Here it was the tell of a
broken READER — and the same discipline applied.*

**The browser reader returns a representation the engine never produced.** Even at zero size
cost, that is a layer between the recipient and the pinned algorithm which must be got right,
and getting it right is work with no upside: the `.duckdb` exists to be a typed store and an
interchange format, not a runtime.

## RULED — option 2

- **The `.duckdb` IS the data package** — one file, typed, entitlement-filtered, hashed, and it
  **ships beside the HTML** as the deliverable that was asked for.
- **The HTML stays self-contained**, embedding the rows it needs as slice 1 did. The manifest
  records **both** the `.duckdb`'s content hash **and** the embedded rows' hash, asserting the
  two are the same tables. A recipient with only the HTML gets a working, verifying page; a
  recipient with both can prove the file they were handed is the data the page computed from.
- **duckdb-wasm does not embed.** Bundle stays ~18 MB rather than ~65 MB.

**The native half is the result that matters and it stands: 63/63 exact, with the DOUBLE
bite-check at 51/63.** The `.duckdb` is a typed store, and the notebook target — which reads it
natively in Python — is on the exact path.

---

## Addendum 2026-09-05 — three findings from building the Labor tab and the scenario amendment

Not pre-registered. Each was found by a seal or a bite-check, and each changed code.

### 1. The learning curve was a staircase, and a UI-staleness seal found it

**The seal:** *a lot change re-renders every metric* — implemented as "each metric takes a
distinct value on each of the 5 lots", because a metric that is constant across lots cannot
reveal a frozen selector.

**It failed on `touch_per_unit`:** lots 4 and 5 came out **identical to the cent** (1481.21).

**The cause was not the UI.** `_touch_hours` counted whole *doublings* of cumulative quantity, so
the curve was a staircase and any two lots inside one tread received identical hours. That is
wrong as a model, not merely inconvenient for a test: **Wright's law is continuous in cumulative
quantity**, and the doubling form is a shorthand for reading it off a chart. Replaced with
`T1 · N^b`, `b = ln(learning)/ln 2`.

| metric | before (lots 4, 5) | after (lots 4, 5) |
|---|---|---|
| `touch_per_unit` | 1481.21, **1481.21** | 1425.54, **1373.33** |
| all 4 metrics distinct across 5 lots | no | **yes** |

**The transferable part:** a seal written for a *rendering* concern found an *arithmetic* defect,
because both reduce to "these two things should not be equal". The tell was a value repeating
where the model says it should decline.

`support_touch_ratio` is 0.450 on every lot **by construction** (support is a fixed fraction of
touch in the seed). It is a correct figure and a useless staleness indicator, so it is excluded
from the seal — and a test now pins that exclusion so nobody "completes" the seal by adding it.

### 2. The `.duckdb` is not byte-reproducible; the row hash is

Three builds from identical inputs:

| | build 1 | build 2 | build 3 | size |
|---|---|---|---|---|
| `.duckdb` sha256 | `bf39e176…` | `5a07984f…` | `aad7dd02…` | 1,323,008 B (identical) |
| row content hash | `ea8f971d…` | `ea8f971d…` | `ea8f971d…` | — |

Same size, different bytes: DuckDB stamps per-database metadata into the container. **So the two
manifest hashes do not have the same powers**, and the manifest must not imply they do:

- `rows_sha256` — **data identity, reproducible.** Answers *"is this the same data"*. Recomputable
  from the engine at any time.
- `duckdb_sha256` — **file integrity of this build only.** Detects tampering with the file that
  was actually shipped (which is what the tamper seal needs) and **cannot** answer *"is this the
  same data as that other package"*. **A rebuild is not a corruption.**

Recorded in `export.py` at the field, and sealed — the seal fails if DuckDB ever *becomes*
reproducible, which is the point at which the restriction could be lifted.

### 3. A seal that could not see what it guarded

*"A scenario cannot relabel the rate vintage"* passed **with its fence removed**. The payload
compared did not carry the vintage at all, so the two calls were equal either way — the seal was
asserting on the neighbour, the fourth instance of my recorded defect.

**The fix was not a better assertion, it was making the fence load-bearing.** `scenario_view` now
returns `rate_vintage` and `rate_fiscal_year` from Python, the panel renders them, and the seal
asserts on the label itself. Removing the fence now turns it red.

**Generalisable:** if removing a guard changes nothing observable, the guard is decorative *or the
output is missing something it should have said*. Here it was the second, and asking which one it
was is what produced the improvement.

### Bite-check results (all four mutations, after the fixes)

| mutation | seals that turned red |
|---|---|
| `labor_view` ignores its lot argument (frozen selector) | 2 of 3 — the third guards caching, a different mutation |
| baseline follows the edit instead of reading the manifest | 2 |
| `EDITABLE_RATE_KEYS` fence removed | 1 (0 before finding 3) |
| `datasets_agree` returns `[]` unconditionally | 1 — the tamper seal; the agreement seal correctly stays green |
