# The a-surviving-mutation-means-you-cannot-tell-yet law

> **A red-proof that survives is not evidence the code is wrong. It is evidence you cannot tell
> yet.**

Break-on-purpose is this repo's standard move: before trusting a guard's green, reintroduce the
defect and watch it go red. When the guard fails to notice, the instinct is to reach for the
code. That instinct is wrong, and the correction changes what the whole discipline is *for*.

## The measurement, across two lanes on 2026-08-26

Every mutation that caught something caught an **ABSENT GUARD**, not bad code:

| lane | mutation | what it found |
|---|---|---|
| eval | truthy `{"default": []}` counted as a vector | the counter had no content test |
| eval | bare component instead of the `components` envelope | no envelope assertion existed |
| eval | `json.dumps(rows)` instead of an array | no encoding assertion existed |
| eval | compacting a partial seed instead of refusing | no ruling was pinned |
| cortex | `toMarkers` mutation survived | that function had **no tests at all** |
| cortex | history case survived | the test asserted the **wrong thing** |

**Not one of them found wrong code.** The code was fine and unguarded — which is precisely the
state that is indistinguishable from guarded until something changes.

## So the technique's real product is a MAP OF WHAT IS UNGUARDED

Not a bug finder. A coverage detector with teeth: it answers *"if a future edit broke this,
would anything notice?"* — which no green suite can answer about itself, because a suite that
never exercises a property passes exactly as loudly as one that guards it.

That reframing has a practical consequence. When a mutation survives, the next step is **not**
"fix the code." It is:

> **Weak guard, or void mutation — prove which.**

* **Void mutation** — the change was a no-op, or the code path is unreachable, or the mutation
  produced an equivalent program. Nothing is wrong and nothing is missing. Discard it.
* **Weak guard** — the behaviour is real, a future edit could break it, and nothing would say
  so. Write the guard. The code stays as it is.

Collapsing those two into "the code must be wrong" is how a survived mutation turns into an
unnecessary edit to working code — the failure mode this law exists to prevent.

## Why the distinction is easy to lose

A surviving mutation *feels* like a positive result, and positive results invite action. But the
signal is about the TEST SUITE, not the implementation. The implementation was never the subject
of the experiment: the experiment asked whether the guard discriminates, and "no" says nothing
about which side of the guard is correct.

## A THIRD reading: the mutant may be EQUIVALENT on this data

**RULED 2026-09-11**, from invincible-agent-91's Decimal conversion of `fin_eac_comparison`.

Two mutations that should have gone red did not: **reverting the spread to float subtraction**,
and **computing the indices by float division**. Neither is a missing seal and neither is a
defect. **Quantizing to cents absorbs the difference**, so float and Decimal agree to the cent
on every figure that seed produces. **On that data the Decimal path is unfalsifiable.**

So the readings are three, not two:

| the mutation survived because… | what to do |
|---|---|
| the guard does not discriminate | fix the guard |
| the mutated line is not load-bearing | delete the line, or the seal |
| **the mutant is EQUIVALENT on this fixture** | **narrow the claim; do not weaken the seal** |

**THE TEST THAT SEPARATES THEM IS WHETHER A DIFFERENT FIXTURE MAKES IT BITE.** A seed landing
near a half-cent boundary would diverge, and the mutations would start failing. That is what
makes it equivalence rather than blindness — the guard is fine, the *data* cannot express the
difference.

**The correct response is 91's, and it is neither of the obvious two.** They did not weaken the
seal, and they did not claim a result they had not earned:

* they asserted exactness **where it can be asserted** — on the arithmetic itself, with values
  chosen to break the coincidence;
* they recorded that when someone finds a seed producing a cent-level disagreement, those two
  mutations start biting and **that narrower seal becomes redundant**;
* and they said plainly what they were **not** claiming — that the conversion fixed a wrong
  number. It did not, on that seed. *"Decimal landed in finance"* would have stood as a
  correctness result it had not earned.

**Verifying the premise first is what made the bound honest.** Before converting, they measured
that all 108 money facts in the seed satisfy `Decimal(v) == Decimal(str(v))` — converting at a
verb boundary is only meaningful while its inputs are exact, and a seal keeps that true. The
remedy if it fails is Decimal in the **seed**, not more conversion at the boundary: **exactness
painted over drifted inputs looks compliant and is not.**

Related: [[a-green-check-proves-only-its-scope]] — a green check proves only what it exercised,
and a mutation that survives is that same blindness measured from the other direction.
[[naming-a-class-is-not-a-guard]] — the guard has to assert the behaviour, not describe it.
[[a-population-hardened-against-the-failure-cannot-measure-it]] — the sibling case, where the
data cannot express the failure because someone repaired it rather than because the arithmetic
absorbs it.

## THE INVERSE, AND IT IS THE MORE DANGEROUS DIRECTION: a survey over a RED baseline reads as a perfect sweep

**RULED 2026-09-12**, from `cortex-ui-60`'s own report against itself.

Everything above concerns a mutation that SURVIVES — the signal you have to interpret. This is
the other failure, and it produces no signal to interpret at all: **eleven mutations, eleven
deaths, and the survey was worthless.**

One newly-added test carried a regex that escaped down to **a bare end-of-string anchor**, so the
baseline was **already failing**. Every mutation then "died" trivially — they did not die *because
of the mutation*, they died because the suite was red before anyone touched it. **A survey over a
red baseline cannot distinguish a guard that discriminates from a guard that is broken, and it
reports the result as 11/11.**

| | what you see | what it means |
|---|---|---|
| mutation SURVIVES | a signal to interpret | weak guard · void mutation · equivalent mutant |
| mutation DIES on a RED baseline | **a perfect sweep** | **nothing was measured** |

**Why this direction is worse.** A surviving mutation is uncomfortable and gets investigated. A
clean sweep is the outcome you were hoping for, arrives as confirmation, and **nobody audits a
result that agrees with them** — which is
[[a-justification-invented-downstream-fits-by-construction]] arriving through an instrument
instead of through prose.

**THE FIX IS ONE LINE AND IT IS NOT "BE CAREFUL": A MUTATION SURVEY MUST ASSERT ITS OWN
BASELINE.** Run the suite unmutated first and require GREEN before any mutation is applied. A
survey that cannot state its baseline colour has not measured anything, whatever its score.

**And the same hunt found a DEAD SEAL in an unrelated file** — a regex carrying literal backspace
bytes, so it could only ever match a class name containing control characters and **could not
fail**. Found only because the author had made the identical typo an hour earlier and went
looking for siblings. That is the searching move worth copying: *a defect you just made in one
place is a query to run against every other place*, and it is how a guard that never fires gets
found at all, since by construction it never asks for attention.

Related: [[a-guard-that-cannot-fire]] — the dead seal is that law's regex-shaped instance;
[[reachability-is-a-property-of-a-path]] — born dead, orphaned, shadowed, and premise-true-purpose-defeated.

## A THIRD WAY THE HARNESS LIES: a mutation aimed at AN occurrence rather than THE occurrence

**RULED 2026-09-12**, from `invincible-agent-22`, who caught their own harness before filing the
finding it would have produced.

Proving a registration-payload test bites, they mutated `"slots": [s.model_dump(...)]` — a line
that appears **twice**, in `manifest_ref` and in `registration_payload` — with a
`replace(..., 1)` that took **the first**. Six tests passed, and they were one keystroke from
recording *"the seal does not bite."*

**The mutation landed in a function the test does not exercise.** So the green said nothing about
either site: not about the one that was mutated, and not about the one the test covers.

| the harness is wrong because… | what a green means |
|---|---|
| the baseline was already RED | every mutation "died" trivially — nothing measured |
| the mutation hit **an** occurrence, not **the** one | the subject was never perturbed at all |

**This is the sample-is-not-the-population defect living inside the instrument** — the same shape
as a scan that greps `docs/` and reports on the repo, except here the sample is *one textual
occurrence of a line* standing in for *the site under test*. The technique: **locate the enclosing
`def` first, then mutate within it.** Aim at the subject, not at a string that appears in it.

### And the mis-aim found a real gap, which is the part worth copying

Re-aimed correctly, both payload tests went red — and the detour surfaced something no test had
said: **dropping `referent` from `manifest_ref`'s hash basis passes all 15 SDK tests.** So the ref
does not demonstrably cover the referent, and a row could change a slot's referent while keeping
the same ref — making *"which version of this contract is registered?"* answerable **wrongly**.

The seal that should have caught it, `test_ref_covers_the_contract_and_ignores_cosmetics`, varies
`required` and `arity` and **never** `referent`. **It asserts the property for two fields and is
read as asserting it for the contract** — which is
[[a-green-seal-can-be-green-for-the-wrong-reason]] arriving through a partial population, and the
remedy is the same one: vary EVERY hashed field, derived from the hash basis rather than listed.

*The gap was found by a mistake in the harness, not by the harness working. That is worth saying
plainly: the value came from investigating an anomaly rather than from the instrument reporting
one.*

