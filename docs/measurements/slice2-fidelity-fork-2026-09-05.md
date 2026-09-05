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
