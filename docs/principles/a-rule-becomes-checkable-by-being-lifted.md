# A rule becomes checkable by being lifted

**Named 2026-09-14**, from the third ADR-0053 §7 extraction. The cleanest proof R-029 has
produced that **extraction is correctness work, not tidiness.**

## The instance

`fin_burn_rate` skips a period with neither plan nor spend:

    if planned == 0 and burn == 0:
        continue

Mutating `and` to `or` **survived the entire suite** — and it was not a coverage gap. The two
differ only on a period where *exactly one* of plan and spend is zero, and the reference seed has
none: **6 periods both-zero, 6 neither, 0 partly.** A genuine equivalent mutant.

**Contriving a seed to make it bite would have been testing the fixture.** So it was recorded as
an honest limit, with the note that the extraction would make it testable.

**After lifting the rule into a module that takes quantities directly, the test is three lines:**

    rows = build([("P0", 100.0, 0.0), ("P1", 0.0, 50.0), ("P2", 0.0, 0.0)], ...)
    assert [r["period"] for r in rows] == ["P0", "P1"]

**The mutation that reddened nothing now reds five.**

## Why it works, stated so it is not mistaken for luck

A rule buried in a verb can only be exercised through **whatever inputs that verb's real data
happens to produce.** The seed is the test's whole universe, and a case the seed does not contain
is a case no amount of care can reach. Lifting the rule to a unit that takes its inputs *as
arguments* replaces that universe with one the test constructs.

> **The seed bounds what an in-place mutation can discriminate. An extracted unit is bounded only
> by what you can write down.**

## How to apply

- **An equivalent mutant on a buried rule is a candidate for extraction**, not merely a limit to
  record. Ask whether the case is unreachable *in principle* or only *in this seed* — the second
  is a packaging problem wearing a coverage problem's clothes.
- **The extraction commit owes the test the lift makes possible.** Naming the debt when recording
  the equivalent mutant, and paying it in the commit that lifts, is what keeps this from being a
  promise nobody redeems.
- **It does not license contriving fixtures.** The distinction holds: bending a *seed* to make a
  mutation bite tests the fixture; constructing an *argument* to a pure unit tests the unit. The
  first invents data the system never produces, the second states inputs the unit is defined over.
- **Say it in the record.** An equivalent mutant written down without this note reads as a
  permanent limit, and the next person re-derives the same dead end.

Related: R-029 (a seal that exercises a function is not a seal that pins its algorithm) —
this is its constructive half; [`seals-must-be-proven-to-bite`](seals-must-be-proven-to-bite.md);
[`a-surviving-mutation-means-you-cannot-tell-yet`](a-surviving-mutation-means-you-cannot-tell-yet.md).
