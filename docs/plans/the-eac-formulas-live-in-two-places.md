---
id:         the-eac-formulas-live-in-two-places
status:     open
owner:
blocked-on: ADR-0053 §2 — the method registry; this is part of that build rather than before it
repo:       invincible-agent
code-site:  agent_fleet/finance_agent/measures.py (fin_eac_comparison.compute), agent_fleet/finance_agent/measure_modules/eac_formulas.py
summary:    fin_eac_comparison reimplements all three EAC formulas in its own Decimal `compute(method)`, independent of the eac_formulas module fin_eac_calculation uses. MEASURED — they agree today, so this is unsealed duplication rather than a live wrong answer. It matters because §2a's transcription seal covers the module and NOT the comparison verb, whose three figures are the ones a customer sees side by side. A join seal is in place as the interim; the fix is for the comparison verb to CALL the module, which §2 requires anyway.
---

# The EAC formulas live in two places

## What was found, and what it is not

Extracting `eac_formulas` (`e3f726b`) and then checking which other callers the change touched
surfaced a second implementation: `fin_eac_comparison` has its own `compute(method)` computing
`REMAINING_AT_BUDGET`, `CPI` and `CPI_SPI` in Decimal.

**Measured before claiming anything — the two agree on every method today:**

    REMAINING_AT_BUDGET   13,130,000.00   both
    CPI                   14,152,380.95   both
    CPI_SPI               14,792,607.71   both

**So this is unsealed duplication, not a wrong answer.** No figure is wrong now.

## Why it is worth an item rather than a note

**§2a makes the PUBLISHED FORMULA the check** — a transcription seal evaluates
`eac_formulas.FORMULA[method]` and compares it against the function. That seal covers
`eac_formulas`. **The comparison verb does not use it.**

So the verb whose three figures a customer sees **side by side** computes from a copy the
transcription never touches. And once §2 makes methods registry rows:

> **A row would make `eac_formulas` authoritative while the customer-facing verb went on
> computing from something nobody transcribed.** The row would be honest about a module the
> comparison verb does not call.

It also breaks §2's own requirement in the seal table — *"the comparison verb runs every
registered method and no unregistered one"* — which cannot be true of a verb that computes from
a hardcoded local function.

## The interim, and why it is only that

`test_the_COMPARISON_verb_agrees_with_this_module_on_every_method` asserts the two agree on every
method, and that the method SETS match. It catches drift from tomorrow.

**It does not make either implementation authoritative**, and a join between two copies is a
weaker thing than one copy: it tells you they disagree, not which is right. It is
[`every-endpoint-verified-the-join-unasserted`](../principles/reachability-is-a-property-of-a-path.md)'s
remedy applied where the better remedy is deletion.

## What lands, as part of §2 rather than before it

1. `fin_eac_comparison` calls `eac_formulas.estimate_at_completion`.
2. **Its `why` strings move with it** — the comparison verb keeps an undefined method's row with
   a reason (`"no CPI"`), which is the behaviour ADR-0053 cites as correct and which
   `fin_eac_calculation` does NOT have (it raises). The module returns `None` and the reason is
   the caller's to phrase, or the module grows a paired `reason` return. **That decision is the
   substance of this item** — doing it badly would flatten a deliberate difference between two
   verbs into one.
3. The join seal above stays, now asserting a single implementation against its transcription
   rather than two against each other.

**Not done inside a step-2 Decimal pass**, deliberately: it changes which code computes a
customer-visible figure, and that does not belong in a commit whose claim is that only the
arithmetic's representation changed.
