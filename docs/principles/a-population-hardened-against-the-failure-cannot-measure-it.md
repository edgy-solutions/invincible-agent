# A population hardened against the failure cannot measure the failure

**RULED 2026-09-11**, from invincible-agent-5f's reading of seal 3's result. It generalises
well past that seal, which is why it is here rather than in the packet.

## The instance

ADR-0050 called seal 3 *"the one seal phrase-based seeding cannot pass"*: seed a canvas, prime
the substrate, seed again, and compare the panel sets. The claim was that phrase-based seeding
would drift across a prime and declared verbs would not.

**It passed.** Four times — three same-window, once across a prime with the fleet constant and
the scope corrected to verb **and** slots. The empirical claim is false.

**Then the reading that matters.** The five phrases in the seeded list are stable **because
they were curated to be**. Slot 3 was deliberately reworded on 2026-08-28 after returning
eleven organisations, so that it would match a verb's default. **The seal was measuring a list
that had already been hand-hardened against the exact failure it was built to detect.**

And the motivating drift — *"where are we over budget"*, recorded moving Portfolio 0.86 → Site
0.75 — **is not one of the five**. The population that would have shown the failure was not in
the sample.

## The law

**When a population has been hardened against a failure, a test over that population measures
the hardening, not the system.** It will pass, and its passing carries no information about the
unhardened case — which is the case that ships.

The hardening is usually invisible at measurement time. Nobody records "I reworded this to stop
it drifting" as a property of the fixture; it looks like a fixture that simply works.

## Why it is not just selection bias

Selection bias is choosing a favourable sample. This is **the sample having been repaired**,
often by the same people, often for good reasons, often months earlier. The repair is the
system working — someone found a drift and fixed it. What it destroys is that item's value as
evidence, permanently and silently.

**So the diagnostic question is: has anything in this population been touched in response to
this failure mode — ever, by anyone, for any reason?** If yes, that item is a regression check,
not a measurement. The two are different instruments and only one of them can support a
decision.

**The phrasing of that question is load-bearing, and the obvious shorter version is wrong.**
"Did someone harden this for my test?" answers *no* here, honestly, and leaves the sample
repaired. Slot 3 was reworded eight months before seal 3 was scoped, by someone fixing a card
that was lying to a viewer — an independent and entirely good reason, with no test in view.
**The hardening does not have to be intentional, contemporaneous, or aware that a measurement
would ever exist.** A question that asks about intent will clear a repaired population every
time; only a question about the population's *history* catches it. (invincible-agent-5f, who
caught this reading of their own law.)

## What it did to the argument, which is the useful part

The empirical case for declared verbs — *phrases drift* — was the decorative half, and the
seal proved it decorative by passing. The load-bearing case never needed a drift:

> **A phrase seed has no panel set until after it runs**, on every substrate, whether or not
> anything drifts.

That is structural, holds without measurement, and survives this result intact. Stated
correctly, the case is not *"phrases drift"* but **"phrases are only stable because someone did
the declaring by hand, invisibly"** — and nobody curates the sixth phrase added next month,
nor would anything in the phrase path tell them to.

## Disposal

* **Keep the seal, rename it to what it measures.** It is a regression seal over a curated
  list, not a test of phrase seeding. A seal whose name overstates its scope is the next
  reader's wrong conclusion.
* **Record the unhardened experiment as the seal's POSITIVE CONTROL**, not as a to-do: seed a
  list that includes a documented-unstable phrase. Do not run it speculatively; run it the
  first time a future run differs, when it is the thing that distinguishes a real change from
  a curated one.
* **Do not let a pass promote the decorative argument.** The structural claim carried the
  decision before the measurement and carries it after.

Related: [[a-green-seal-can-be-green-for-the-wrong-reason]],
[[seals-must-be-proven-to-bite]],
[[a-green-check-proves-only-its-scope]],
[[decide-the-meaning-before-the-measurement]].
