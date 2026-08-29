---
id:         slot-fill-accuracy-v1
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  scripts/slot_fill_battery.py, slot_corpus_v1.json, docs/measurements/slot-fill-battery-run2.json
summary:    THE FIRST MEASURED ACCURACY NUMBER. 48 human-authored cases, live filler. 40 CORRECT (83.3%), 5 WRONG (10.4%), 2 EXTRA (4.2%), 1 MISSED (2.1%). ALL FIVE WRONG FILLS ARE THE ENTITY-RESOLUTION GAP — excluding it, 43 cases, 40 correct (93.0%) and ZERO comprehension-driven wrong fills. THE THRESHOLD QUESTION IS ANSWERED AND IT IS THE HARD BRANCH: correct-filled confidence runs 0.93-1.00, wrong runs 0.90-0.96, and a genuine miss scored 0.96. No threshold separates them; confidence is not actionable in EITHER direction. Two other findings: declaring a closed vocabulary did not prevent coercion into it ("forwards" -> direction=downstream), and an unanchored period was passed through as the literal phrase ("this quarter" -> window=["this quarter"]).
---

# Slot-fill accuracy, v1 — the first honest number

**Corpus:** `slot_corpus_v1.json`, 48 cases, authored by the architect against the live
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
