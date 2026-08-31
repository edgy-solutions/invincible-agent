---
id:         elicitation-accuracy-v1
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
code-site:  scripts/elicitation_battery.py, docs/measurements/elicitation_corpus_v1.json, src/iagent_pure/slot_disposition.py
summary:    THE FIRST MEASURED ANSWER TO "DOES THE SYSTEM HOLD A CONVERSATION." Run 1 — 14/15 against expectations committed BEFORE the run; run 2 (16 cases after amendment) — 16/16. THE ONE FAILURE WAS MY EXPECTATION, NOT THE SYSTEM: K09 asserted a mandatory slot was "spoken and resolvable" for `I1-P1`, which is not a project id (the seed holds P1..P14), and the resolver correctly answered `empty` -> ABSTAIN. Run 1 is reported as 14/15 and NOT re-scored. BOTH PATHS WALKED END TO END FOR THE FIRST TIME: BIND (menu -> validated pick -> the verb ANSWERS, 200) on process_id n=2 and tech_id n=5; RESPEAK (no menu -> the answer re-enters as WORDS -> the resolver turns "Wave 1 Cutover" into P5 and "Integration Platform" into C7, both `exact`). ALL FOUR ADVERSARIAL ANSWERS BEHAVED: a fabricated pick and a cross-slot pick REFUSED; a whole new question filled nothing; a real-but-wrong-class name came back `wrong_class` with the value REMOVED. THE CORPUS FOUND A DEFECT IN MY OWN CODE ON ITS FIRST RUN — `mixed` returned candidates [P3, P4, P3] and the menu offered P3 TWICE; deduped, sealed. AND ONE PREDICTION IS LEFT REFUTED: K15 ("the Rollout") came back `slot-unfilled` — the filler never attempted the slot — a third possibility I did not enumerate.

# Elicitation accuracy, v1 — the first time the system held a turn

**Corpus:** `elicitation_corpus_v1.json`, 15 cases at run 1 and 16 after amendment, authored
against live `slots_for()` declarations and the seed vocabularies read from `PlanStore`.
**Runner:** `scripts/elicitation_battery.py`, which contains no phrasings. **Raw:**
`elicitation-battery-run1.json`, `-run2.json`. Run live against sandbox `iagent-engine-o` and
`iagent-engine-p`.

**Expectations were committed before the run** (`e0e3f0c`-era commit of corpus + runner, prior
to any execution), so every grade below is against a prediction already in git.

## What this measures that the slot battery does not

The slot corpus asserts on `/fill_slots` output: **did the filler read the phrasing.** This runs
the whole turn and asserts the final disposition and answer:

```
phrase -> /fill_slots -> accept_slots -> decide_disposition
       -> ask_card -> [the corpus's scripted answer] -> resolve_ask
       -> BIND:    accept_slots(merged) -> POST the verb, assert it ANSWERS
       -> RESPEAK: re-issue with the answer, assert what it now FILLS
```

A disposition that produces a beautiful card nobody can answer has not been measured by
asserting on the card.

## Headline

| run | cases | pass | note |
|---|---|---|---|
| **1** | 15 | **14** | the one failure was **my expectation**, not the system |
| **2** | 16 | **16** | after amending K09 and adding K16 |

**Run 1 is reported as 14/15 and is not re-scored.** A case that passes after its expectation
was corrected did not pass in the run that measured it, and re-scoring a pre-registered run
against amended expectations is precisely the adjustment pre-registration exists to prevent.

### By trigger shape — never blended

| family | run 2 | what it proves |
|---|---|---|
| `bind-menu` | 2/2 | a real menu, a validated pick, **the verb answers** |
| `respeak-no-menu` | 2/2 | no menu; the answer re-enters as words and resolves |
| `must-not-ask` | 5/5 | the guardrail, including both hard negatives |
| `must-abstain` | 1/1 | `empty` → abstain, live rather than by fixture |
| `disambiguation` | 2/2 | newly reachable — and one is a refutation that passed *as* one |

A missed ask and a spurious ask are different failures with different fixes; one percentage
would hide which moved.

### By path — BIND and RESPEAK are different mechanisms

| path | run 2 |
|---|---|
| `bind` | 2/2 |
| `respeak` | 4/4 |
| `refused` | 2/2 |

## BOTH PATHS WALKED END TO END, FOR THE FIRST TIME

### BIND — the menu, the pick, and an answer

```
K01  "how has it evolved"          process_id absent, BusinessProcess n=2
     menu [BP1 Order to Cash, BP2 Plan to Produce] -> pick BP1
     accept_slots -> {"process_id": "BP1"} -> POST /measure/plan_process_evolution -> 200
K02  "what is the tech footprint"  tech_id absent, Technology n=5
     menu [T1..T5] -> pick T3 (from the MIDDLE, so a runner taking options[0] fails) -> 200
```

**These are the first questions in this system's history to go ask → menu → pick → answer.**
The probe that predicted they would work was run yesterday; this is the walk.

### RESPEAK — the answer re-enters as words and the resolver does its job

```
K03  "what does it depend on"      project_id absent, Project n=14 -> too_many
     answer "Wave 1 Cutover"
     re-issued: 'what does it depend on (project_id: Wave 1 Cutover)'  -> P5, outcome exact
K04  "what is the capability path"  capability_id absent, Capability n=9 -> too_many (bound 8)
     answer "Integration Platform"
     re-issued: '... (capability_id: Integration Platform)'            -> C7, outcome exact
```

**Nothing was bound un-resolved.** The names never touched the slot directly; they went back
through the filler and the resolver like any question, which is the property the whole tri-state
contract exists to protect.

> **K04 is the bound case and it met the DEPLOYED bound, not the ruled one.** `Capability` holds
> 9; the correction to 10 is committed and **not rolled**, so the live engine still answers
> `too_many` at 8. The corpus carries `expect_at_ruled_bound` for this case, so the redeploy has
> a pre-registered prediction waiting rather than being graded after the fact.

## All four adversarial answers behaved

| case | answer | outcome |
|---|---|---|
| K10 | `BP99` — fabricated | **refused** |
| K11 | `T3` — real, but from a *different slot's* menu | **refused** |
| K12 | *"actually, what does spend look like"* — a whole new question | respeak; filled **nothing** |
| K13 | `ERP Modernization` — real, wrong **class** | respeak; `wrong_class`, value **removed** |

**K11 is the one worth pausing on.** `T3` is a valid id and a correct answer to K02 — it is
simply not on *this* menu. Refusing it is the difference between validating against a
*vocabulary* and validating against **what was offered**, and only the second is menu integrity.

**K13 is E05 arriving through the answer path instead of the question path**, and it behaves
identically: reported, not bound.

## ⛔ THE CORPUS FOUND A DEFECT IN MY OWN CODE ON ITS FIRST RUN

`K14` — *"what does the Module Build depend on"* — resolved `mixed` with candidates
**`[P3, P4, P3]`**, and the menu offered **P3 twice**.

Every option routed, so menu integrity in its narrow reading held — and a person reading
*"Finance Module Build"* twice is looking at a broken menu. The resolver may legitimately return
one instance more than once (several providers, or one provider matching on two fields);
**making the menu unique is the consumer's job, not the phone book's.**

Deduped **first-occurrence-wins**, because candidates arrive ranked and dropping the earlier copy
would silently demote one the resolver scored higher. Sealed by
`test_a_menu_never_offers_the_same_option_TWICE`. Run 2: `['P3', 'P4']`.

> This is what the corpus was for. Thirty-seven unit tests did not catch it, because every
> fixture I wrote had distinct candidates — I invented the inputs, and I invented them tidy.

## THE DISAMBIGUATION PATH IS LIVE — and one prediction is LEFT REFUTED

**`K14` fired `mixed` with `option_source: resolution`.** That is the direct payoff of the
specificity ruling (`257f9dd`): before it, this phrase died in the gate and returned
`not_specific` before tie-breaking ever ran. **The ADR-0033 disambiguation consumer now fires on
real data**, which it never had.

**`K15` — *"what does the Rollout depend on"* — refuted my prediction, and the refutation is
kept.** I pre-registered two possibilities: candidates from the resolver, or `not_specific`. The
actual outcome was **neither**: `reason: slot-unfilled`, `option_source: none`. **The filler never
attempted `project_id` at all** — there was no resolution to be specific or vague about.

> **Left refuted rather than rewritten.** P8 *"Site B Rollout"* and P9 *"Site C Rollout"* both
> contain the word, and I assumed a bare *"the Rollout"* would be extracted as a referent. It was
> not. That is a fact about the **filler's** extraction, not the resolver's specificity, and it
> means K15 tests a different seam than I thought I was testing. Rewriting the prediction to
> match the result would have destroyed the measurement; the case stays, correctly marked, as
> the one that tells us the boundary is upstream of where I looked.

## The one failure, and it was mine

`K09` — *"what does I1-P1 depend on upstream"* — expected `route`, got **`abstain`**.

**My expectation was wrong.** The case note asserted *"the mandatory slot IS spoken and
resolvable"* and I never checked: the seed's projects are `P1..P14` and **there is no `I1-P1`**.
The resolver answered `empty` — the phone book knows the class and there is no such thing — and
`empty → abstain` is the ruled behaviour, correctly refusing to offer a menu with nothing on it.

So the case is **re-registered as the must-abstain case**, which no other case covered and which
had only ever been exercised by fixture, and **K16** (*"what does P7 depend on upstream"*, a real
project) was added for the shape K09 was meant to test. The original expectation is preserved in
`superseded_expect`, because a corrected prediction that erases what it predicted is not a
corrected prediction.

## What this does NOT establish

**No user has walked this.** Every answer in the corpus is scripted by the case. The corpus
proves the *mechanism* end to end — menu, validation, re-route, answer — and says nothing about
whether a person finds the question intelligible. The surface is still deferred and jointly
designed; the prose fallback (`ask_card`'s `message`) is what a user would see today.

**The router is not measured.** Every case supplies its verb, exactly as the slot corpus does.
This measures the disposition given a correct route.

**Two of the four mandatory slots still have no live corpus case in the SLOT battery.**
`process_id` and `tech_id` are exercised here and only here; a redeploy at the ruled bound adds
`capability_id` to the BIND population.

## Owed

* **A redeploy at bound 10**, after which `K04` should flip RESPEAK → BIND. The prediction is
  already written.
* **A re-run after any filler prompt change** — `K15` in particular is an extraction-side case
  now, and would move if the filler's referent handling changed.
