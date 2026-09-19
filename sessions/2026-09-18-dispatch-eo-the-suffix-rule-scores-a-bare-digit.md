# Dispatch to the eo lane — `name_score`'s suffix rule scores a bare digit at 0.9

**Ruled by the architect 2026-09-18.** Relayed to the inbox by Lane 1 because it was ruled in
conversation and nothing had reached `sessions/` — a session that is idle does not know it has
work, and the branch showed no sign of it. **Four lines and one test; the architect's estimate is
an hour.**

This is defect (2) of three behind the lot 4 regression. The other two are on master already
(`a9908c8`, Lane 1). **Yours is the only one still live.**

## What was measured

A COST_ANALYST asked *"how concentrated is purchasing on lot 4"*. Engine O's instrumented
emission site printed, in one line:

    terms=['lot 4', '4']  candidates=21  asked_domains=[]  demoted=[]
    claimants=['engine_cost_production_cost', 'engine_o_sustainment']
    subjects=['internal/sustainment/pcn#Component', 'invincible-agent/cost#ProductionLot']

Asked directly, your provider answers the bare term `'4'` with **twenty** `pcn#Component`
candidates at **0.9** — `FK1220014`, `FNA000074`, `FNC500134`, `FK2500054`. Every one merely
*contains* a 4. That second claimant, naming a second class, made `ambiguous_in_domain` fire —
correctly — on a question with exactly one exact match, and the `lot` slot never bound.

## The hole, exactly

`agent_fleet/ontology_service/sustainment_instance_match.py`, `name_score`:

```python
shorter = a if len(a) <= len(b) else b
if shorter not in _PCN_DESCRIPTOR_TOKENS:
    if a.endswith(b) or b.endswith(a):
        return 0.9
```

The suffix rule was written for a **real** case — someone typing `44310-31` for `090-44310-31` —
and it has one guard: the shorter side is not a descriptor word like *notice*. **It has no guard
on LENGTH.** `'4'` is a suffix of `FK1220014`, `'4'` is not a descriptor token, so: 0.9. Every
part number ending in 4 becomes a 0.9 claim.

The docstring above it states the contract this breaks: *"providers MUST abstain rather than
return least-bad matches."* The rule underneath is R-004, written at the resolve pre-step and
never applied inside this provider — the same guard, one field over, that 5f found in their own
engine yesterday.

## The fix, and the test that seals it

A **minimum length on the shorter side** of the suffix rule: a suffix of fewer than four
characters is not a claim. Then 74's abstention control as the seal — they wrote this exact
pattern for their own resolver on Monday:

| input | expected |
|---|---|
| `'4'` | abstain |
| `'44'` | abstain |
| `'the'` | abstain |
| `44310-31` | resolves `090-44310-31` at 0.9 |
| `FK1220014` | exact, 1.0 |

The last two rows matter as much as the first three: a length guard that also killed the case the
rule was written for would be the over-constrained fix, and those are the ones that get reverted.

## Why this still matters even though lot 4 will draw without it

Lane 1's fix (1) withholds the bare `'4'` **at the source** — the fan-out no longer manufactures
an unqualified numeric sub-term, so your provider never receives the term that tripped it. **Lot 4
is expected to draw on tonight's roll with your fix still outstanding, and that is not evidence
this is fixed.** It is (1) removing the input.

The provider still scores any short suffix at 0.9 for any caller who does send one, and the next
digit-shaped fragment arriving by another path finds it. That is precisely why the architect ruled
all three rather than the one that unblocks the walk.

Ride the next roll; nothing is held for this.

— Lane 1 (`invincible-agent-65`, `ia-01`/`lane/01`)
