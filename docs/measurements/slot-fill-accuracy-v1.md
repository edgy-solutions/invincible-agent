---
id:         slot-fill-accuracy-v1
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  scripts/slot_fill_battery.py, docs/measurements/slot_corpus_v1.json, docs/measurements/slot-fill-battery-run2.json
summary:    THE FIRST MEASURED ACCURACY NUMBER. 48 human-authored cases, live filler. 40 CORRECT (83.3%), 5 WRONG (10.4%), 2 EXTRA (4.2%), 1 MISSED (2.1%). ALL FIVE WRONG FILLS ARE THE ENTITY-RESOLUTION GAP — excluding it, 43 cases, 40 correct (93.0%) and ZERO comprehension-driven wrong fills. THE THRESHOLD QUESTION IS ANSWERED AND IT IS THE HARD BRANCH: correct-filled confidence runs 0.93-1.00, wrong runs 0.90-0.96, and a genuine miss scored 0.96. No threshold separates them; confidence is not actionable in EITHER direction. Two other findings: declaring a closed vocabulary did not prevent coercion into it ("forwards" -> direction=downstream), and an unanchored period was passed through as the literal phrase ("this quarter" -> window=["this quarter"]).
---

# Slot-fill accuracy, v1 — the first honest number

**Corpus:** `docs/measurements/slot_corpus_v1.json`, 48 cases, authored by the architect against the live
`slots_for()` inventory, validated case-by-case against the declarations before running (no
case named an undeclared slot or an out-of-vocabulary value). **Runner:**
`scripts/slot_fill_battery.py`, which contains no phrasings — a test enforces that. Raw
per-case results: `slot-fill-battery-run2.json`.

## The headline, unblended

| class | n | share |
|---|---|---|
| **CORRECT** | 40 | 83.3% |
| **WRONG** | 5 | 10.4% |
| **EXTRA** (invention) | 2 | 4.2% |
| **MISSED** | 1 | 2.1% |

**All five WRONG fills are `referent_unresolved`** — the filler emitting a spoken entity NAME
where the slot takes an opaque id (`[[the-filler-has-no-entity-resolution]]`). Not one wrong
fill came from misreading a phrasing.

**Excluding that platform gap: 43 cases, 40 correct (93.0%), and ZERO wrong fills.** Those
are two different numbers answering two different questions, and both belong in any account
of "how reliable is this":

* *how often does a user get the right scope today* → **83.3%**
* *how well does the filler read a phrasing* → **93.0%, with no confident misreadings**

## The threshold question is answered, and it is the branch that matters

| class | n | min | median | max |
|---|---|---|---|---|
| CORRECT-**filled** | 26 | **0.93** | 0.99 | 1.00 |
| CORRECT-**empty** | 14 | 0.00 | 0.95 | 0.99 |
| WRONG | 5 | 0.90 | 0.92 | **0.96** |
| EXTRA | 2 | 0.85 | 0.88 | 0.90 |
| MISSED | 1 | 0.96 | 0.96 | 0.96 |

**Correct fills bottom out at 0.93; wrong fills reach 0.96. They overlap. No threshold
separates them.**

> **The population split was necessary to say this honestly.** The first run reported CORRECT
> as `min=0.00, median=0.97` and the low end was an artifact: a case that correctly fills
> NOTHING has no value to be confident about. Splitting CORRECT into *filled* and *empty*
> removes the artifact — **and the overlap survives it**. The finding is not a measurement
> error; it is the answer.

**And confidence is not actionable for misses either, which was the remaining hope.** `E04`
("what phases feed into P7") missed all three slots — every one of them present in the
phrasing — at **0.96**. Meanwhile four correct-empty cases scored **0.00** and `H06`, the
same structural situation, scored **0.95**.

The pattern that explains all of it: **confidence reports how sure the model is about the
values it DID produce, not whether it produced everything the question named.** It is
structurally incapable of flagging an omission, which is exactly what an `ask` disposition
needs. `[[a-missing-mandatory-slot-is-a-400-not-an-ask]]` must be built on a different
signal — the obvious candidate being the declarations themselves: a spoken-mandatory slot
absent after filling is a deterministic, model-free trigger.

## Two findings the corpus was built to catch, and caught

**1. Declaring a closed vocabulary did not prevent coercion into it.** `E06`, *"what does P3
depend on forwards"* → `direction: "downstream"` at 0.90. `forwards` is not in
`[upstream, downstream]`. The `Literal` fix made the vocabulary visible to the model, and the
model used it as a menu to snap to rather than a set to check membership against. **This is
counterintuitive and worth banking: declaring the vocabulary made a plausible wrong answer
MORE available, not less.** The guard cannot help — `downstream` is a permitted value, so it
passes acceptance cleanly. Only the corpus catches it.

**2. An unanchored period was passed through as the literal phrase.** `D05`, *"what does
spend look like this quarter"* → `window: ["this quarter"]` at 0.85. Not an invented period —
the raw words, which would reach the engine and 422. The author's ruling (unanchored →
MISSED) is vindicated in a stronger form than intended: the failure is not a reasonable guess
at the current quarter, it is a non-value shaped like one.

## Non-determinism, stated because a single run would hide it

Two runs of the same 48 cases: **CORRECT 41 → 40, EXTRA 1 → 2.** `D05` was correct in run 1
and EXTRA in run 2. Single-run figures carry roughly ±1 case of noise, so **83.3% should be
read as ~83% ± 2 points**, and a regression of one or two cases is not yet a signal.

## What the corpus did NOT measure

* **Routing.** Every case supplies the verb. This measures the filler given a correct route,
  not the route.
* **Arrival.** The battery asserts on `/fill_slots` output, not on delivery to the verb. The
  seven-hop carriage is proven separately (`test_slot_coverage_matrix.py`, 24/24), so the
  two halves compose — but no single case here walks the whole path.
* **`plan_funding_gap.window`** is exercised on other verbs, not this one; and
  `kind="project"` is never positively exercised because it is the DEFAULT, and exercising a
  default positively is the pass-by-coincidence trap.

## One grading tension, flagged rather than resolved

The envelope's `grading_note` says a slot filled but absent from `expect` is **EXTRA**;
`E06`'s own note calls coercion to `downstream` a **WRONG** fill. The runner followed the
envelope. Both classes rank above MISSED and the headline is unaffected, but if the author
intends near-miss coercion to grade WRONG, the case needs `expect: {"project_id": "P3",
"direction": <something>}` or the contract needs a per-flag override.


---

## UPDATE 2026-08-29 — fix (2), the coercion fix, measured

One prompt change, then the full 48 re-run **as a gate**, twice. Raw:
`slot-fill-battery-run3.json` (v1), `slot-fill-battery-run4.json` (v2).

| | CORRECT | WRONG | EXTRA | MISSED |
|---|---|---|---|---|
| before | 40 (83.3%) | 5 | 2 | 1 |
| v1 — *"fill only if what they said IS one of those values"* | 40 | 3 | **0** | 5 |
| **v2 — the test is on the THING NAMED, not the spelling** | **42 (87.5%)** | 5 | **0** | 1 |

**The gate caught a regression I introduced, which is what it is for.** v1 closed the coercion
trap and broke two cases that were passing: `"by organization"` and `"coloured by funding
risk"` stopped filling, because *organization* is not the string `org` and *funding risk* is
not `funding_risk`. I had collapsed **same thing spelled differently** into **different thing
that resembles one** and told the model to refuse both. Enum values are written for a machine
and nobody speaks them that way, so a string-identity test refuses every real phrasing.

v2 states both halves with the measured examples on each side. Every case in v2 is at least as
good as before, and the two traps stay closed:

* `D05` *"this quarter"* — **EXTRA → CORRECT**, no longer passes the raw words through
* `E06` *"forwards"* — **EXTRA → CORRECT**, no longer snaps to `downstream`
* `A05`, `B04` — recovered
* `C06`, `H04` — still WRONG, and correctly so: they are the entity-resolution gap, which is
  fix (1)'s territory and not a prompt's to solve

**Headline: 83.3% → 87.5%. The invention class is gone (EXTRA 2 → 0).** Excluding the
platform gap: **43 cases, 42 correct (97.7%), zero wrong fills.**

**Read with the noise band.** Run-to-run variance is ±1–2 cases, so +2 is at the edge of it —
but `EXTRA 2 → 0` held across BOTH v1 and v2, which is the part that is not noise. The
comprehension-side claim is that the coercion class was eliminated, not that the headline
moved 4.2 points.

**Not tuned.** Two versions, both principled, the second written against a mechanism the first
run NAMED. Neither was iterated toward green, and both runs stay in the record.

**One more confidence oddity, banked not chased:** `E06` now fills `project_id` correctly and
reports **0.00**. A correct fill at zero confidence, alongside a genuine miss at 0.96 in the
previous run. Every reading so far says the same thing — this signal is not measuring
correctness.


---

## UPDATE 2026-08-29 — fix (1), referent resolution, measured

Raw: `slot-fill-battery-run5.json`. Pre-registration: `fix-1-pre-registration.md`, committed
**before** the run.

| | CORRECT | WRONG | EXTRA | MISSED |
|---|---|---|---|---|
| baseline | 40 (83.3%) | 5 | 2 | 1 |
| after fix (2) | 42 (87.5%) | 5 | 0 | 1 |
| **after fix (1)** | **45 (93.8%)** | **0** | 0 | 3 |

### THE WRONG CLASS IS ELIMINATED

**Zero wrong fills, from five.** Every silent-wrong-answer case in the corpus is gone, and the
residue sits entirely in the recoverable class. That is the axis this whole arc has been
about: a missed fill degrades to a default or an ask; a wrong fill renders cleanly and lies.

### The pre-registration was 5 for 5

| id | predicted | actual |
|---|---|---|
| C05 "the Aurora site" | CORRECT | **CORRECT** — `site_id: S1`, outcome `fuzzy` |
| C06 "Brandon" | CORRECT | **CORRECT** — `site_id: S2` |
| D04 "ERP Modernization" | CORRECT | **CORRECT** — `scope_initiative_id: I1`, `exact` |
| H04 "Order to Cash" | CORRECT | **CORRECT** — `process_id: BP1`, `exact` |
| **E05** "the ERP Modernization **project**" | **MISSED** | **MISSED** — `wrong_class`, slot removed |

E05 resolved to `I1`, an `Initiative`, against a slot declaring `#Project`. Refused,
**removed from `slots` rather than passed through**, reported with its outcome and its
candidate. The corpus expectation (`project_id: P1`) remains unsatisfiable by any correct
resolver — no project bears that name — and is flagged as a probable authoring error.

**The refutation I pre-registered did NOT occur.** I predicted the fleet-wide fan-out would
produce `mixed` from another provider matching the same name in a different class. It did
not: outcomes came back `exact` and `fuzzy` cleanly. Domain-scoped fan-out is therefore not
needed yet — but the reasoning stands for the day another provider learns these names.

### One deviation, investigated rather than absorbed

`C04` *"how loaded is site S1 in FY26-Q2"* went **CORRECT → MISSED**, which I had not
predicted. Re-probed three times against the same deployment: **3/3 correct**, returning
`{"site_id": "S1", "window": ["FY26-Q2"]}` with `outcome: exact`. It is the known
non-determinism, not a regression from this fix.

**The reported number stays 45.** A case that passes on re-probe does not retroactively pass
in the run that measured it, and upgrading the headline on the strength of a follow-up would
be exactly the kind of adjustment the pre-registration exists to prevent. The underlying
value is probably 46; the measurement says 45.

### Where the residue is now

Three MISSED, all recoverable, none silent:

* `E05` — resolved to the wrong kind of thing. **The disambiguation ask has a menu**
  (the candidate is retained) — see `[[elicitation-ask-disposition]]`.
* `E04` *"what phases feed into P7"* — fills `project_id` and `kind`, misses `direction`
  (*"feed into"* as a paraphrase for upstream). A fair miss, per its own corpus note.
* `C04` — the flaky one above.
