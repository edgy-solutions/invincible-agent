# The cost-of-guessing-is-a-mutation law

> **When a router guesses, the worst case is not a wrong answer. It is an unrequested write.**
> Refusing to act on a low-confidence match is therefore a SAFETY property, not tidiness — and
> it must be argued as one, because the case for loosening it is always framed as recall.

## The instance that names it

2026-08-26. `make me a portfolio canvas` was typed into the demo. The router:

* resolved the subject to **Portfolio at 0.96** — high confidence, correct
* walked the verbs typed against Portfolio
* **found nothing that fit**, and returned `NO_VERB_CLASSIFIED`

The seeding intent had a catalog entry, BAML phrasings and a working BFF route, and no
registered capability — so there was genuinely nothing to nominate. The refusal was correct.

**Now look at what was in the walk.** The decision path shows the router passing over
`mesh:planCommitScenario`. That is *the commit ceremony* — the one verb that writes baseline from
a scenario, the path that records who moved the portfolio and why.

A router tuned to always return its best candidate would have had `planCommitScenario` sitting
there as a Portfolio-typed verb with a plausible-looking name, at a moment when the operator's
actual intent was "build me a board". **The cost of guessing would not have been a confusing
card. It would have been a governance write against the plan, attributed to a person who asked
for a canvas.**

## Why this needs writing down BEFORE the argument arrives

The pressure to loosen a disposal threshold is always the same and always reasonable-sounding:

> "We refuse too often. Recall is bad. Take the top candidate when confidence is close."

That argument is easy to make and easy to win, because the visible cost of refusal is a user who
did not get an answer, and the visible benefit is a demo that responds to more phrasings.

**The counter-argument is only obvious once someone has written down what the walk contained.**
Nobody proposing a threshold change enumerates the candidate set it would then act on. In this
instance the set included a write. That is not a hypothetical: it is what was on screen.

So the rule is not "never loosen the threshold". It is:

> **A proposal to lower a refusal threshold must state which verbs become reachable, and
> whether any of them MUTATE.** A recall argument that has not enumerated its new action space
> is a proposal to guess with unknown blast radius.

## The corollary the same day produced

This is the reading half of the same law, from the mutation-testing work running in parallel:

> **A surviving mutation is not evidence the code is wrong. It is evidence you cannot tell yet.**

Every mutation that caught something that day caught an **absent guard**, not bad code. Which
means the technique's real product is *a map of what is unguarded* — and unguarded-but-correct is
a state that looks identical to guarded, right up until something changes.

Both halves say the same thing from opposite ends: **the dangerous state is the one you cannot
distinguish from the safe one.** A guessing router looks like a helpful router until the guess is
a write. Untested-correct code looks like tested code until an edit lands.

## What follows

* **Honest refusal is a feature with a cost centre and a safety budget.** Argue changes to it in
  terms of the action space, not the answer rate.
* **The HUD is part of the mechanism, not decoration.** This diagnosis took minutes because the
  refusal was *legible*: resolved subject, confidence, candidates considered, the verb walked
  past, and the reason. A refusal nobody can read is indistinguishable from a bug, and gets
  "fixed" by loosening.
* **`NO_VERB_CLASSIFIED` on a demo path is not automatically a defect to remove.** Here it was
  the system being right about a capability that did not exist. The repair was to register the
  capability — not to make the router less careful.

## Related

* [[a-fallback-without-a-counter-becomes-the-architecture]] — the other direction: what happens
  when the system *does* answer rather than refuse, and nobody counts it.
* [[decide-the-meaning-before-the-measurement]] — a threshold is a meaning decision wearing a
  number's clothes.
* [[gate-class-follows-the-effect]] — the same reasoning applied to endpoints: what a thing DOES
  determines how it must be guarded, and a mutation cannot borrow a read's justification.
