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

---

## Addendum 2026-09-05b — the untouched scenario disagreed with the baseline by $732,148.44

**Found by the architect opening the file.** Fourth consecutive round in which the human
open-it step found a defect no seal caught. Worth stating plainly: **every structural check
passed on this build.**

### The defect

With no rate edited and the slope at its default 0.92, lot 1 showed:

| | |
|---|---|
| Baseline price | 16,733,978.39 |
| Your scenario price | 16,001,829.95 |
| Difference | **−732,148.44** |

Two headline numbers disagreeing before the customer touches anything. As the architect put
it: *"the customer's first thought is 'which one is wrong,' and the package has just taught
them to distrust the verified number."*

### The cause: one number with two meanings

`dataset.learning_slope = "0.92"` was written as a **literal in the page builder**, meaning
*"what the slope field should default to"*. The page read it as *"the point at which a scenario
is identical to the baseline"*. Those are only the same number if the arithmetic agrees, and it
did not:

- The engine's hours already **are** `T1 · N^b`, `b = ln(0.92)/ln 2` — the curve is applied.
- `scenario_view` then multiplied touch **cost** by the slope directly: `touch_cost * 0.92`.

So the field labelled *"learning slope"* was a flat 8% haircut on touch labour, applied on top
of learning the engine had already applied. **The label was a lie and the default double-counted.**

### The fix — the model, not the default

`_touch_factor` re-runs the curve at the scenario's slope and takes the ratio against the
baseline's:  `N^b_scenario / N^b_baseline`. Identity is now the engine's own slope, and the
field means what it says.

| | before | after |
|---|---|---|
| reset state, all 5 lots | −$732k … −$1.1M | **0.00, exactly, every lot** |
| slope 0.88 (steeper), lot 5 | — | −1,008,288.93 |
| slope 0.96 (shallower), lot 5 | — | +1,095,448.91 |
| out-of-range / unparseable | fell back to **1** | falls back to the **baseline slope** |

The fallback mattered too: falling back to `1` reads as *"no adjustment"* and means *"no
learning at all"* — a silent divergence wearing the costume of a safe default.

Two supporting changes: `Lot` now carries `cumulative_units` (the curve is a function of it,
and a scenario cannot re-run the curve without it), and `learning_slope` comes from
`seed.LEARNING_SLOPE` rather than a literal.

### Why the seal missed it

`test_an_unedited_scenario_equals_the_baseline_exactly` **existed, and passed**, because it
asserted identity **at slope "1"** — a state the interface never opens in. The interface opens
at 0.92.

> **A seal that tests a state the interface never presents is not testing the interface.**

The replacement reads the identity point **from the package** — the same value the field and
the reset button take — so the seal cannot drift from the UI again.

### And a fabricated justification, retracted

`_touch_factor` short-circuits identity. I documented that as necessary, writing that `math.pow`
*"would return 0.9999999999999998"*. **I never ran it.** The bite-check refused to go red
without the short-circuit, and the measurement shows why: at identity both `pow` calls are the
same expression over the same inputs, so the ratio is `x/x` = exactly `1.0` (n = 12, 26, 42,
66, 90). The branch is kept as a property-of-this-function guarantee; the docstring now says it
is **not** load-bearing.

**This is the third time a plausible-sounding negative has entered my prose unmeasured.** The
bite-check caught it only because a mutation that *should* have gone red stayed green —
green-where-red-was-expected is the tell, and it is worth as much attention as a failure.

### Cosmetic, same pass

Two money formats on one screen: labour metrics grouped (`5,229,210.00`), the composition table
raw (`6307210.00`), because the renderer printed the manifest's strings directly in JS. Moved to
`page.composition_view` — formatting is presentation, this module owns the package's
presentation, and JS is outside every seal. Sealed both ways: one format across every rendered
figure, **and** formatting never changes a verified figure.

### Bite-checks

| mutation | red |
|---|---|
| slope scales touch cost flat (**the original defect, reintroduced**) | 2 |
| out-of-range falls back to 1 | 1 |
| identity short-circuit removed | **0 — see the retraction above** |
| composition renders raw manifest strings | 1 |
| the formatter re-rounds | 1 |

### Still owed on the Labor tab

What shipped is the **selected-lot** half. The **across-lots** half — hours by lot × category
stacked, and the learning curve — is the next build, from the same `.duckdb`.

---

## Addendum 2026-09-05c — the across-lots half, and the defect that drawing a chart exposed

### The finding: the curve contradicted its own slope label

Preparing to plot touch hours per unit, before drawing anything:

| | |
|---|---|
| engine's per-unit hours | lot 1 **3,500.00** at cumulative 12; lot 5 **1,373.33** at cumulative 90 |
| observed ratio | 0.3924 |
| ratio a **0.92** curve implies over 7.5× cumulative | 0.7848 |
| **slope the points actually implied** | **0.7248** |

The seed computed a lot's touch hours as `T1 · (N/12)^b` — the LOT TOTAL scaled by cumulative
position. **A lot's hours therefore did not depend on its own quantity**, and lot 5 (24 units,
32,960 h) came out below lot 1 (12 units, 42,000 h): half the hours per unit for twice the work.

Nothing had caught it. The trend seals were satisfied — prices declined, metrics differed. It
surfaced only because a chart puts a number next to its own model where a reader can check it.

> **Publishing a picture of a number is a stronger check than publishing the number.**

This is the **third** wrong learning curve in this lane, each caught one step later than the
last: stepped-by-doublings (caught by a UI-staleness seal) → continuous but quantity-blind
(caught by preparing to plot) → integrated.

### The fix: Wright's law integrated

    unit n costs   U1 · n^b                b = ln(slope)/ln 2
    total(N)     = U1 · Σ n^b  ≈  U1 · N^(b+1)/(b+1)
    lot hours    = U1 · [ C(cum) − C(cum − qty) ]

`U1` is **derived** so lot 1 reproduces its historical total exactly — written as a literal it
would drift silently the moment the slope changed, and the drift would read as a data update.

| lot | qty | cum | touch hours | h/unit |
|---|---|---|---|---|
| 1 | 12 | 12 | 42,000 | 3,500.00 |
| 2 | 12 | 24 | 35,280 | 2,940.00 |
| 3 | 18 | 42 | 49,156 | 2,730.89 |
| 4 | 24 | 66 | 61,735 | 2,572.29 |
| 5 | 24 | 90 | 59,028 | 2,459.50 |

Hours now rise with lot size and fall with position — both, which is the point.

### Plotted at the algebraic lot midpoint

A lot's figure is an **average** over a range of units, so its honest x is the cumulative unit
whose own cost equals that average: `N* = (avg/U1)^(1/b)`. The arithmetic midpoint put the
points on a line implying **0.9120** beside a label reading **0.92** — small, wrong, and exactly
what a reader with a calculator finds first. At the algebraic midpoint the implied slope is
**0.920000**.

### And the seal for it was tautological

The first version read the plotted `x` and checked the points lay on the curve. **But `x` is
`(y/U1)^(1/b)` — derived from `y` through the very curve being tested**, so the points lie on it
by construction whatever the engine produced. It passed on the broken seed.

**The bite-check found it: the mutation restoring the broken seed left the seal green.** Second
time green-where-red-was-expected has been the tell today.

Rewritten against the axis the hours did **not** come from — each lot's cumulative range and its
own quantity — and a companion seal now pins the circularity so the tautological version cannot
return under the same name.

### One constructor for the dataset block

`learning_slope` and `unit1_hours` were assigned by the page builder *after* `build_dataset_package`
returned, so a package built the ordinary way lacked them and the test fixture had to hand-patch
the field. That is the same class as a seal testing a state the interface never opens in — one
level down. Both now come from the one constructor, and the fixture patches nothing.

### What shipped

- **Stacked columns**, hours by lot × category, all lots, selected lot solid.
- **Learning curve**, h/unit vs cumulative quantity, with the scenario slope overlaid dashed —
  computed through the **same** `_touch_factor` as the scenario panel, so the picture and the
  number cannot disagree. At the engine's slope the overlay coincides and the legend says so.
- **The baseline states its own curve**: slope, factor, and cumulative units through the lot.
  At lot 1 the factor is exactly 1 with *"no effect at this lot — it is the curve's reference
  point"*, because **a curve present with nil effect is not the same statement as no curve**.

### Bite-checks

| mutation | red |
|---|---|
| the quantity-blind seed restored | 2 (**0 before the tautology was fixed**) |
| plot at the arithmetic midpoint | 2 |
| overlay uses its own flat-scale model | 2 |
| renderer supplies its own chart scale | 1 |
| baseline reports "no curve" at the reference lot | 1 |

**82 seals green.**

---

## Addendum 2026-09-05d — the Algorithm panel, and a false claim caught before it shipped

### The dispatch said "restate the header's algorithm hash beside the source". The header has no such hash.

The header reads `algorithm 939dd0… · as of 2026-09-05 · sha256:1ce97ca8…`. Those are the **git
commit** that produced the figures and the **content hash of the package body** (manifest, lots,
dataset). **Neither covers the text of `pricing.py`.** Restating the locator beside the source as
though it verified the source would have been a false claim on the face of the artifact — and a
convincing one, since the digits would have matched the header exactly.

Until now the manifest genuinely did not pin the source bytes. A recipient without the repository
could not check that the module embedded in their file is the module the commit names.

**Added `manifest.modules`** — `{"pricing.py": "sha256:21e61050…"}` — and a seal that the locator
is *not* it.

### The trap inside the fix: file bytes ≠ embedded bytes

`pricing.py` is stored **CRLF** in this tree. The builder embeds it with `read_text(encoding="utf-8")`,
which normalises to **LF**:

| | |
|---|---|
| file on disk | `sha256:1e50cb93…` |
| text actually embedded | `sha256:21e61050…` |

A manifest hashing the **file** prints a number the recipient cannot reproduce from what they are
shown or download — and it would **agree on an LF checkout and disagree on a CRLF one**. A
verification result that depends on the reader's line endings does not read as a platform
difference; it reads as tampering.

The hash is taken over exactly the string that reaches the page. The seal asserts the two differ
**while this tree has CRLF**, so it cannot go vacuous quietly.

### What the panel does

- **The source is read back from the interpreter's own filesystem** — `open("pricing.py")`, the
  same path `import pricing` resolved. Not the `<script>` tag, not a copy passed in from JS. A
  panel rendering a copy could show text the interpreter never ran and every check would still
  agree with itself.
- **The hash is computed on open**, over that same text, and compared to `manifest.modules`. The
  number beside the source is a *measurement* of the source.
- **Download** hands over `ALGO.source` — the original string, not the highlighted DOM — so the
  bytes an analyst runs are the bytes that were hashed. Highlighting is applied to an escaped
  copy for exactly this reason.
- **Composition rows link into the source**, and the panel is honest about what it can point at:
  the steps are **data**, one evaluator applies all of them, so a row points at its step's
  **declaration** and the panel names `_fold_price` as the shared arithmetic. Claiming a line
  "computes Overhead" would misdescribe the design in the panel built to make it readable.
- **Built only after verification passes** — the one place the artifact could otherwise offer
  something it had not checked.

### The linker failed loudly, by design

The first version matched `name="Overhead"` and resolved **nothing**: the declarations are
positional, `StepSpec("Overhead", …)`. It surfaced immediately only because `step_lines` returns
an `unresolved` list. A linker that silently produced no links would have shipped a panel whose
rows quietly did nothing — visibly fine, functionally dead.

### The source-map reference

Pyodide ships `//# sourceMappingURL=pyodide.js.map`, which is not embedded; the browser resolves
it against the page and issues a fetch that fails. **The no-CDN seal matches on `https?://` and
never saw it.** Stripped at both embed points — the loader text and the base64'd
`pyodide.asm.js` — with a seal that decodes the embedded runtime and checks there too.

Not a CDN call and it costs nothing. But a package whose claim is *"everything it needs is
inside it"* should not emit a request for something that is not.

### Bite-checks

| mutation | red |
|---|---|
| manifest hashes the FILE bytes (the CRLF trap) | 2 |
| the panel shows a copy instead of the executed file | 4 |
| the hash is carried rather than measured on open | 1 |
| the linker silently resolves nothing | 1 |

**90 seals green.**

---

## Addendum 2026-09-05e — the page was dead on open, and 90 seals said it was fine

`Uncaught SyntaxError: '' string literal contains an unescaped line break`, line 330. Blank
page. Reported by the architect on reload.

### The failure mode that defeats every other seal at once

A JS syntax error takes the **whole page** down — no verification banner, no refusal, no
figures. Nothing in the suite could see it: **the seals test Python, and the page's Python was
fine.** Every structural check passed, 90 seals passed, and the artifact did not run.

### The cause: an escape that collapses twice

`scripts/labor_tab_template.py` is **itself a Python triple-quoted string**. A JS escape written
into it is interpreted when the builder *imports the module*, not when it formats the template.
So `split('\n')` became `split('` + a real newline + `')` — a real newline inside a JS string
literal.

Replaced with `String.fromCharCode(10)`. **Sidestepping escapes is cheaper than getting
double-escaping right twice** — and this file has now cost me that mistake three times.

### The comment explaining the fix was broken by the same bug

The fix carried a comment describing the collapse. **Its escape collapsed too**, splitting the
comment across two lines and leaving a lone backtick running as code — which opened a template
literal that swallowed the next 120 lines and surfaced as
`SyntaxError: Unexpected identifier 'pricing'` at a completely unrelated place.

The comment now **names the character instead of writing it**.

### The gate: node parses every inline script, and the build REFUSES

`check_javascript()` runs `node --check` over each untyped `<script>` and raises before
`write_text`. A page that does not parse is never written.

Two defects in the checker itself, both worth recording because both were **wrong in the
permissive direction**:

1. Its script filter used a word-boundary escape that reached the file as a literal
   **backspace byte (0x08)**, so the negative lookahead never fired and it fed **17 MB of
   base64 to node as JavaScript** — then reported three failures that were entirely its own.
   Replaced with a plain `if "type=" in attrs: continue`.
2. Its error extractor took *"the last stderr line"* (node's version banner) and then
   *"any line containing Error"* — which matched `except ImportError:` inside the echoed
   source and printed **52 KB of Python as the JavaScript diagnostic**. Now anchored:
   `^\w*Error: .*$`, capped at 180 characters.

> **A checker that is wrong in the permissive direction does not look wrong — it looks like a
> finding.** Both of these produced confident, specific, entirely fictional failures.

### Bite-check

An unterminated string in the template → `REFUSING TO WRITE: … SyntaxError: Invalid or
unexpected token`, and no file produced. Sealed both ways: the shipped page parses, and the gate
fires on a broken one without firing on the typed script tags that carry base64 and JSON.

**92 seals green.**

---

## Addendum 2026-09-05f — the remaining tab surfaces, and three columns that could not answer

SEPM monthly hours with its average, material unit price applied-versus-estimating, and
supplier concentration. Building them found that **the data could not support two of the three
questions**, in ways nothing had flagged.

### 1. `estimating` was a constant column

`lots.estimating` was `False` on every row ever produced. A column that never varies answers
nothing and reads, to anyone joining on it, **like a distinction the data supports**. It could
not support one: the estimating rate set was never exported at all, so applied-versus-estimating
was unanswerable from the package no matter what the flag said.

Replaced with `applied_vintage` and `estimating_vintage`, and both rate sets are now exported
(rates: 30 → 48 rows). Sealed: no column in `lots` may be constant across every lot.

### 2. The rate revision never reached material

Material is burdened by **G&A, cost of money, profit and escalation** — *not* by fringe or
overhead. The seed's later vintage revised **only fringe and overhead**, so
applied-versus-estimating on any purchased figure was **zero by construction on every lot**.

The view would have rendered a column of `0.00` reading as *"the estimate was exactly right"*.

It is also not how a rate revision behaves: an indirect-rate update that never touches G&A or
the escalation assumption is not a revision. Now `+0.003·j` on G&A and `+0.008·j` on escalation:

| lot | per unit (applied) | per unit (estimating) | difference |
|---|---|---|---|
| 1 | 71,880.27 | 72,651.14 | −770.87 |
| 2 | 75,286.23 | 76,078.52 | −792.29 |
| 3 | 78,776.11 | 79,590.07 | −813.96 |
| 4 | 82,350.31 | n/a | n/a — one rate vintage this year |
| 5 | 86,009.21 | n/a | n/a |

**Lots 4 and 5 report "no separate estimate", not a zero.** A zero reads as agreement; the truth
is there is nothing to compare against — the same error as reporting an absent ratio as 0.000.

> **A comparison that cannot come out different is not a comparison.** The seal asserts every
> comparable lot actually moves.

### 3. There was no monthly dimension at all

`period` was the fiscal year. SEPM is a **level of effort** — staffed by month, not consumed per
unit — so a per-lot total answers *"how much"* and hides the shape entirely. `Lot` now carries
`sepm_monthly`, and the remainder goes in the last month **so the series sums to the annual
figure exactly**. The page states the reconciliation rather than assuming it: two statements
about one quantity, and a reader should not have to trust that they agree.

The shape is deliberately not flat — a flat series makes the average line meaningless and the
seal over it vacuous. Sealed: >4 distinct monthly values, and `0 < months_above_average < 12`.

### The agreement check had a latent defect the moment ties existed

`datasets_agree` keyed on `(lot, category, sub_config)`, which **stopped identifying a row** once
a category held more than one row per sub_config. Twelve monthly SEPM rows share all three; the
two sides ordered their ties differently and it reported six "differences" that were the same
values in another order. It had been correct only by the accident that no category had ties.

Keyed on period now, **and hours are compared** — they never were, so a file with wrong hours and
right prices passed.

### A bite-check that could not be constructed, said so

Removing period from the key does **not** turn the tamper seal red: the reordering misaligns the
rows and the prices disagree anyway. Two different properties —

- **no false positives on tied rows** ← what period-in-the-key buys, proven by the agreement
  test passing at all (it failed with six spurious differences the moment ties existed)
- **a period change is detected** ← proven by tampering with the shipped file

— and no single mutation covers both. Rather than invent one, the seal's docstring records which
part proves what. **A bite-check that cannot be constructed is a fact about the property, not a
licence to skip saying so.**

### Also on the page

Supplier concentration renders in the browser with an editable bound; the bound travels with the
verdict and says whether the reader chose it. Sealed against the engine verb directly: the
browser and `cost_supplier_concentration` must agree on ranking, shares and the count above the
bound, lot by lot — the page must not compute a different answer than the engine to the same
question.

### Bite-checks

| mutation | red |
|---|---|
| the rate revision stops reaching material (the original defect) | 1 |
| a single-vintage lot reports 0.00 instead of n/a | 1 |
| the monthly series is flattened | 1 |
| the monthly remainder is dropped | 1 |
| the threshold stops changing the verdict | 1 |
| period dropped from the agreement key | **0 — see above, and it is recorded rather than forced** |

**118 seals green.**
