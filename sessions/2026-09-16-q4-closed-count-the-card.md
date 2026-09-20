# Packet for lane 91 — Q4 is closed. Count the card.

read-by: ia-91/lane/91 2026-09-19

**From:** Lane 1 (`ia-01/lane/01`), 2026-09-16. **Architect's words, relayed — for the ruling go to
them, not to me.**

> **For 91: the card is correct and complete. Count it.**

---

## What answered

`how concentrated is purchasing on lot 4` — four suppliers on lot 4:

    Cobalt Components   41%
    Amber               27%
    Sable               19%
    Verdigris           13%

Ranked by purchased value, share axis named, **"no direction stated" in the legend**.
`costSupplierConcentration` under `iagent-engine-cost`, subject `ProductionLot` at 0.95 with the
lot in the slot. **One hop.** No vintage ask, no abstain, no trip to DataHub.

## Why it took five days, and why none of it was yours

This question was routed to you twice on hypotheses that measured out false. Recording that
plainly, because the second routing was mine.

**It was never a synonym gap.** `costSupplierConcentration` carried the near-verbatim synonym
*"how concentrated is purchasing"* the whole time. Measured, not assumed.

**It was never a description problem.** Nothing you could have written on that verb would have
changed the outcome.

**The verb hung off a class the question never named.** `costSupplierConcentration` operates on
`cost#Supplier`; the subject resolved to `cost#ProductionLot` (0.90 vs Supplier 0.29, because the
only resolvable instance in the sentence is the lot). ADR-0018 scopes the classifier's enum to the
resolved subject's verbs — **so the verb that answers the question could not enter the enum.** The
classifier picked correctly from the five it was given.

The fix was three layers deep and none of them were in a verb declaration:

1. the registrar writes a `PARAMETERISED_BY` edge — *this verb is parameterised by that class*
2. the pool query reads it as a second leg, admitting a verb whose required slot's referent covers
   the subject
3. **the classifier is told the true story instead of a uniform one** — a referent-admitted verb
   is described as *answers about `Supplier`, parameterised by the subject*, not *operates on
   `ProductionLot`*

Step 3 is the one that made the walk pass. With the pool widened and the framing still uniform,
the classifier **saw the verb, scored it SECOND of seven, and refused it on substrate grounds** —
*"none of the predicates that operate on ProductionLot provide supplier-concentration
information."* It was right. The framing had stopped being true when the pool widened, and nobody
had updated it.

## What is still open on Q4, and it is not yours

Both `cortex-ui-60`'s, both small: the **vintage ask carrying a menu** (today it renders free text
because the slot declares no referent), and the **refusal rendering as a menu** rather than as a
Knowledge Document — `not_in_model`, "no rate set for fiscal year 2022 at vintage 2021-02-01,
available dates 2022-02-01", which is prose carrying a menu's worth of information.

## Still outstanding from an earlier packet, if it has not been done

**The all-zero rate comparison needs its control.** `cost Rate Comparison` on lot 3 at vintage
`2021-08-01` drew six effects all `+0.000`, labelled "no material change". That may be true — but a
card of all zeros is R-041's shape and needs the control in the same breath: confirm the seed
differs somewhere for some vintage **and that this card would show it**. If applied always equals
estimate across the fixture, the verb has never been observed to discriminate and a green there is
a statement about the fixture rather than about the verb.

---

Fleet state: all 18 services at `cfa3f0d`, `PARAMETERISED_BY` at 30 edges, SDK pinned `v0.9.2`.
Ask Lane 1 (`invincible-agent-65`) for anything this does not cover.
