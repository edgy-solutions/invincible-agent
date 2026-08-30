# Engine F — the full verb exercise, v1

**PRE-REGISTERED 2026-08-30, BEFORE THE PROBES RAN.** Expectations first, results appended
below, so the verification is a comparison rather than an impression. Where a result
contradicts an expectation, **the expectation is left standing and the delta is named** — an
expectation quietly edited to match its result is not a measurement.

**Target:** the DEPLOYED engine (`deploy/iagent-engine-fin`, sandbox, chart 0.3.51), reached
in-cluster. Not the local import — three probes had hit the deployment before this and
everything else about Engine F had been exercised in-process only.

**Scope note / fences.** Lane 1 owns the router, the filler, the supervisor, the corpus harness,
engine-o and engine-p. **Nothing here touches any of them.** That bounds what "end to end"
can honestly mean tonight, and §1c states the bound explicitly rather than letting a
verb-surface result read as a routing result.

---

## §1 — What is being measured, and what is NOT

| | measured tonight | why / why not |
|---|---|---|
| every declared slot on every verb, against the deployment | ✅ | this is the gap: 8 verbs registered, 3 probed |
| every enum value of every enum slot | ✅ | the values are declared from `Literal`s; nothing had exercised the non-default arms |
| payload conformance to the archetype contracts | ✅ | the two clean binding rows must actually satisfy `PERIOD_SERIES` / `SHORTFALL_GRID` |
| resolver behaviour across the whole finance name surface | ✅ | §3, the IPMDAR collision measurement |
| EAC refusal on **every** branch incl. bogus method | ✅ | the bogus-method branch has never been probed |
| the seed's invariant seals, by negative control | ✅ | a seal nobody has seen fail is a seal nobody has tested |
| **"routing lands on the right verb"** | ❌ **NOT MEASURED** | routing runs through Lane 1's surfaces. What §1c measures instead is the **routing SIGNAL** — my own registered descriptions/synonyms/anti-synonyms — which is the half Engine F owns and can be wrong on its own |

> **Stated plainly so no later reader over-reads this document:** a green result here means *the
> verbs are correct and their registration data is coherent*. It does **not** mean a spoken
> question reaches them. That claim needs the router and belongs to a joint run.

---

## §2 — Pre-registered expectations: the six verbs

Against the notional seed (`NP-MERIDIAN`, 6 reported periods FY26-01…FY26-06, 9 work packages,
5 control accounts, 3 funding lines).

### `fin_burn_rate` → `PERIOD_SERIES`
| probe | expected |
|---|---|
| default (program only) | **6 rows**, one per reported period |
| `window=["FY26-06"]` | **1 row** |
| every row | carries `period`, `burn`, `planned`, `scope_label`, `value_unit` |
| envelope | `value_unit="USD"`, `value_label` present |
| `runway_periods` | positive and **decreasing** across the series (budget is consumed) |

### `fin_performance_indices` → `PERIOD_SERIES`
| probe | expected |
|---|---|
| default | **6 rows**; `cum_cpi` **falls** 0.995→0.848, `cum_spi` **rises** 0.870→0.913 |
| `ca_id="3.1"` | narrows to that account; **fewer or equal** rows, different CPI |
| `ca_id="9.9"` | **422** `not_in_model`, naming the account |
| envelope | **NO `value_unit`** — the deliberate absence (accommodation A2) |
| every row | `amount_unit="USD"`, and **never** a key named `value_unit` |

### `fin_funding_status` → `SHORTFALL_GRID`
| probe | expected |
|---|---|
| default | **18 rows** (3 lines × 6 periods) |
| `window=["FY26-06"]` | **3 rows**, states exactly `{short, pledged-not-firm, met}` |
| every row | the ladder `expended ≤ obligated ≤ authorized` holds |
| every row | **both vocabularies**: `required/committed/secured` == `authorized/obligated/expended` |
| envelope + rows | `value_label`, `value_unit`, `scope_label` all present |

### `fin_variance_analysis` → `fin:VarianceDecomposition`
| probe | expected |
|---|---|
| default (`cost`, materiality 0.05, depth 3) | **1 root row**; root variance **−1,130,000**; **3 material contributors** (CA 1.1, 3.1, 5.1) |
| drill | each material CA has `contributors`; WP-3101 is the dominant leaf at **−1,100,000** |
| `variance_kind="schedule"` | root SV **−600,000**; a **different** contributor set |
| `materiality=0.5` | **fewer** contributors; a `residual` + `residual_note` appears |
| `max_depth=1` | root `stop_reason="depth"` on its children, tree truncated **and says so** |
| `materiality=0` and `=1` | **422** — outside the open interval |
| arithmetic | material contributors + `residual` == root variance, every level |

### `fin_variance_drivers` → ranked set (archetype is a cortex build)
| probe | expected |
|---|---|
| default (`cost`, `control_account`) | **3 rows**, ranked by \|contribution\|, ranks 1..3 |
| `level="work_package"` | **3 rows**: WP-3101 (−1.1M), WP-5101 (−150k), WP-1102 (**+120k, favourable**) |
| sum | contributions sum to the root variance, both levels |
| `variance_kind="schedule"`, `level="work_package"` | LOE package WP-4101 either absent (SV=0) or carries the `note` |
| `top_n=1` | 1 row, carrying `withheld_contributors` and `withheld_contribution` |
| `top_n=0` | **422** |

### `fin_eac_calculation` → single measure (archetype is a cortex build)
| probe | expected |
|---|---|
| no method | **422**, `needs_slots=["method"]`, question naming all three |
| `CPI` | **14,152,381** |
| `CPI_SPI` | **14,792,608** |
| `REMAINING_AT_BUDGET` | **13,130,000** |
| spread | max−min ≈ **1,662,608**, **>10% of BAC** |
| every row | `method` **and** `formula` present |

### Providers
| probe | expected |
|---|---|
| `resolve_instance("meridian")` | 1 candidate, `NP-MERIDIAN` |
| `resolve_instance("zzz")` | **empty list** — a first-class answer, not an error |
| `enumerate_instances(Program)` | `members`, count 1 |
| `enumerate_instances(WorkPackage)` | `too_many`, count 9, limit 8 |
| `enumerate_instances(FundingLine)` | `members`, count **3** — deduped from 18 period rows |
| `enumerate_instances(PMB)` | `unsupported`, with a reason naming what it does hold |

---

## §3 — Pre-registered expectations: the IPMDAR collision, live

**The question:** how much of Engine F's own name surface is ambiguous *to the resolver*, and
which verbs would become unroutable as a result.

**The mechanism under test.** `resolve_instance` scores exact match at 1.0 regardless of class.
`mesh:InstanceResolution`'s contract says the router abstains on **fuzzy-mixed-class** and that
*"only the class is used to set the routing subject"* — so **two classes tied at the top set no
subject**, and since the class picks the verb (`fin:ControlAccount` → `finVarianceDrivers`,
`fin:Program` → `finVarianceAnalysis`), the question's **verb** is undetermined.

**Pre-registered expectations:**

1. **Zero exact-match collisions in the current seed.** `check_consistency`'s duplicate-label
   guard forbids them, so this is really a test *of the guard*. A non-zero result means the
   guard is not doing what it claims.
2. **Non-zero *fuzzy* mixed-class candidate sets.** Contained-phrase scoring (0.75) and token
   overlap (0.4–0.6) are class-blind, so shared words across axes should produce mixed sets
   above the 0.5 floor even with all labels distinct. **This is the interesting number**, and
   it is the one that survives my seed fix — because it does not depend on duplicate labels.
3. **The unroutable set is the union of classes appearing in mixed sets**, mapped through
   `input_uri` to verbs.
4. **The abstain is NOT `not_specific`.** That value belongs to engine-o's
   `instance_resolution` vocabulary (`exact | fuzzy | mixed | not_specific | empty`). Engine F's
   provider does not classify — it returns scored candidates and the **router** classifies.
   Expected shape from Engine F: a candidate list whose classes differ. Recorded because the
   dispatch asked which it is, and the honest answer is *neither, at this layer*.

**Also measured:** what a real IPMDAR mapping would do — the collision my seed fix removed but
a faithful field-for-field read reintroduces (WBS `3 Integration and Test` alongside CA
`3.1 Integration and Test`). Probed by asking the resolver for names that collide *by
construction*, without mutating the deployed seed.

---

## §4 — Pre-registered expectations: the invariant seals, by negative control

**A seal nobody has watched fail is a seal nobody has tested.** Each is broken deliberately,
in memory, and must go red:

| seal | mutation | expected |
|---|---|---|
| the `$1.66M` spread | shrink ACWP so the three EAC methods converge | **fails**, naming the spread |
| roundness | set one `acwp` to `103_333.33` | **fails**, naming the row |
| duplicate label | rename WBS `3` back to "Integration and Test" | **fails**, naming both holders |
| funding ladder | set `expended > obligated` on one line | **fails**, naming the line |
| BAC roll-up | change one CA's BAC | **fails**, naming program vs sum |
| A2 (`amount_unit`) | already negative-controlled 2026-08-29 | **fails** — re-confirmed |

**The spread seal is the load-bearing one**: the mandatory-method refusal is only defensible
while the three formulas disagree materially. If someone tunes the notional data until they
converge, the refusal becomes ceremony — and the seal is what says so.

---

*Results appended below this line after execution. Nothing above is edited.*

---

# RESULTS — executed 2026-08-30 against the deployed engine

**Nothing above this line was edited after execution.**

## §2 results — the six verbs: **0 failing checks of ~75**

Every pre-registered expectation held, against `deploy/iagent-engine-fin` in sandbox. The
figures, the row counts, the trend directions, the arithmetic identities, the refusal codes
and the archetype contract fields all matched what was written down first.

Highlights worth keeping:

* **`fin_variance_analysis`** — root variance −1,130,000; exactly the 3 pre-registered material
  contributors (CA 1.1, 3.1, 5.1); WP-3101 the dominant leaf at −1,100,000; **children +
  residual == root at every level**. `max_depth=1` truncated *and said so* (`stop_reason:
  "depth"`), which is the whole point of that field. All four out-of-range `materiality`
  values refused.
* **`fin_variance_drivers`** — contributions sum to the root variance at **both** levels, and
  the favourable tail (WP-1102, +120k) **is ranked**. `top_n=1` declared its withheld tail.
* **`fin_performance_indices`** — cumulative CPI falls, cumulative SPI rises, in one payload.
  **Accommodation A2 verified on the deployment**: no `value_unit` at the envelope, no row
  naming that field, `amount_unit="USD"` throughout.
* **`fin_funding_status`** — 18 rows; all three states at FY26-06; the ladder holds on every
  row; **both vocabularies identical on every row**, which is the SHORTFALL_GRID reuse working.
* **`fin_burn_rate`** — runway strictly decreasing across the series.

### The EAC branches, including the seven never probed before tonight

| method | result |
|---|---|
| *(absent)* | 422 · `needs_slots=["method"]` · question names all three |
| `CPI` / `CPI_SPI` / `REMAINING_AT_BUDGET` | 200 · 14,152,381 / 14,792,608 / 13,130,000 · each carries `method` + `formula` |
| `'BANANA'`, `''`, `'cpi'`, `'CPI '`, `0`, `True`, `['CPI']` | **all 422** |

**Both gates exist and are distinguishable — the defence-in-depth is demonstrated, not asserted:**

| input | gate that fired | why it matters |
|---|---|---|
| method **absent** | **ROUTE** — built from `slots_for`, so the router sees the gap | this is what declaring slots from day one buys |
| method **present but invalid** | **VERB** — `MethodRequired` | ADR-0045: *"written into the verb, not left to the caller's discipline"* |

**Newly measured edge:** `'cpi'` and `'CPI '` are refused. Enum matching is case- and
whitespace-strict. Defensible — a router fills from the declaration's exact values — and the
refusal names the correct spellings, so it is self-correcting rather than a dead end. Recorded
because it was unmeasured, not because it is wrong.

## §3 results — the IPMDAR collision, live

**Name surface: 28 addressable entities across 6 classes.**

| measurement | pre-registered | result |
|---|---|---|
| exact-match collisions | 0 | **0** — the duplicate-label guard holds |
| fuzzy mixed-class sets (full names + ids) | non-zero | **21 of 56 lookups** |
| verbs unroutable *from full names* | expected some | **none** — every mixed set had a **unique top class** |

> ### MY OWN §3 ANALYSIS WAS WRONG, AND §5 OF THE SAME RUN CAUGHT IT
>
> Measuring only **full labels and ids** produced "nothing goes unroutable today." That is
> true and irrelevant: **nobody says "Integration and Test Control Account 3.1."** They say
> *"the test account"*, *"variance on software"*. Re-run over realistic **partial** phrasings —
> single tokens and two-word windows drawn from the labels — the picture inverts.

**The number, stopword-filtered: 12 of 74 realistic partial phrasings = 16.2% produce a
TIED-AT-TOP MIXED-CLASS candidate set** — the router's abstain case.

*(Raw was 15/81 = 18.5%; three probes — `'and'`, `'Test and'`, `'and Evaluation'` — were
tokenizer artifacts, not phrasings. Both reported, because a rate inflated by its own
instrument is the defect this repo keeps catching.)*

**Which verbs a tie leaves undecidable:**

| ties | verb |
|---|---|
| 11 | `finVarianceDrivers` |
| 6 | `finFundingStatus` |
| 1 | `finEacCalculation` |
| 1 | `finVarianceAnalysis` |

**Which classes participate:** `ControlAccount` 11 · `OBSElement` 10 · `WorkPackage` 6 ·
`FundingLine` 6. Examples: `'Test'` ties **four** classes at 0.75; `'Program'` ties **five**.

**Answering the dispatch's question — is the abstain `not_specific` or something else?**
**Neither, at this layer, and that is the finding.** Engine F does **not** classify. It returns
`{output_uri, query, candidates[], provider}` — scored candidates, nothing more. `not_specific`
belongs to engine-o's `instance_match` vocabulary, and the classification is the **router's**.
What Engine F contributes is the *shape*: a candidate list whose top scores tie across classes.
Whether that reads as `mixed` → abstain depends on whether the decision table inspects **the
top candidate** or **the whole set** — and that is Lane 1's code, not mine.

> **The precise handover for the fourth-consumer scoping:** the shape is **common** (≈1 in 6
> realistic phrasings), it is **structural** (IPMDAR names share tokens across axes by
> design), it concentrates on **`finVarianceDrivers`**, and it does **not** depend on duplicate
> labels — my seed fix removed those and the rate is unchanged. What is *not* known from here
> is whether today's decision table abstains on it, because a tie at 0.75 with no exact match
> may already fall through as `fuzzy`. **That one check is Lane 1's and it decides whether
> this is a live gap or a latent one.**

## §4 results — the seals, by negative control: **6 of 6 fire**

| seal | mutation | result |
|---|---|---|
| roundness | `acwp = 103,333.33` | **FIRES**, naming the row |
| duplicate label | WBS 3 renamed to CA 3.1's label | **FIRES**, naming both holders |
| funding ladder | `expended > obligated` | **FIRES**, naming the line |
| BAC roll-up | one CA inflated | **FIRES**, naming program vs sum |
| dangling ref | WP on unknown CA | **FIRES** |
| **the spread** | ACWP := BCWP (perfect cost performance) | **FIRES** — spread collapses 13.9% to **4.5%** |

The spread seal is the load-bearing one and it now has a witnessed failure: converge the data
and the three formulas land at 12,000,000 / 12,542,857 / 12,000,000. **The mandatory-method
refusal would become ceremony, and the seal is what says so.**

## A structural finding nobody was looking for

Measuring the resolver surfaced something the code review had not: **three classes resolve and
enumerate while no verb routes on them** — `OBSElement`, `WBSElement`, `WorkPackage`, **19
members between them.** A spoken name landing on one sets a routing subject nothing serves: the
resolver reports success, the router sets the subject, and the question dies a hop later with
nothing to blame.

**Here it is intentional** — a work package is a *drill-down referent* inside the variance
tree, addressable in an answer without being an opening question. **But it was intentional and
undeclared**, which is indistinguishable from an oversight.

`_unroutable_classes()` sealed the **forward** direction (a verb whose subject nothing can
find). The **reverse** direction was unsealed and invisible to it. Now:

* `_NO_VERB_BY_DESIGN` declares the three, with the reason;
* `_dead_end_classes()` raises at boot on any **undeclared** one;
* two seals, one of them a negative control proving the two directions are *different* checks
  rather than one written twice.

**28 seals green.**

## What this run does NOT establish

Stated so no later reader over-reads it: **routing was not tested.** A green result here means
the verbs are correct and their registration data is coherent. It does **not** mean a spoken
question reaches them — that needs the router, which is Lane 1's surface, and it is the one
thing Engine F still cannot prove alone.
