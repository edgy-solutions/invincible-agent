---
status: WALK SHEET — for a human with the UI open; nothing here is verified until the cards are seen
date: 2026-09-19
engine: engine-fin
---

# Finance card walk — eight prompts, seven cards and one refusal

**This sheet exists because a payload check is not a card walk.** Every number below came from
calling the engine directly, which means **none of it is evidence that anything renders.** The
only evidence is the card on screen.

## ⚠ NOT WALKED YET — every expectation below is DERIVED, not observed

The cost sheet earned its banner by being walked and finding five defects the engine's own green
suite could not. This one has no such banner, and **should not be read as if it had.** What is
written here is what the engine produces and what the archetype contracts say they draw; the
column that matters — *did a person see it* — is empty.

**Where each expectation came from**, so a reader can weigh it:

| field | derived from |
|---|---|
| prompt | the verb's own `OWNS the phrasings` line in `finance_agent/main.py` |
| expected verb | the same declaration |
| expected archetype | the capability row in `presentation_agent/capabilities.py` |
| minimum rows | measured against the notional seed, 2026-09-19 |
| disposition | measured — the EAC refusal is a real 422 with `needs_slots: ["method"]` |

**Fleet state assumed:** master `3849f72` or later. `fin_eac_comparison` must be bound to
`COMPETING_MEASURES` (landed 2026-09-18); before that commit prompt 7 draws nothing at all.

**Data:** NP-MERIDIAN is notional throughout — invented program, round figures, public EVM
methodology. No real program, lot or supplier data is in this engine.

---

## 1. The program brief — three findings in one answer

> **"give me the program brief for NP-MERIDIAN"**

`fin_program_brief`, the one graph here rather than a measure. It composes the variance
decomposition, the burn against plan and the funding position into **three findings that each
cite the artifact they came from**, which is why its row floor is 3 and not 1.

**No archetype.** The brief is a `StatefulSupportResponse`, not a card — its expectation is
`expect_archetype: null`, and a row asserting one would be asserting the wrong contract.

⚠ **A 422 HERE IS A NEW CAUSE.** The old one is understood and fixed: the graph declares
`checkpointer: true` and therefore needs a `thread_id`, which the supervisor now threads from
`run_id`. That was self-inflicted and it is on master. If this 422s again, **do not reach for
that explanation** — it is the shape of a stale claim that matched the symptom once.

## 2. Why are we over — the decomposition

> **"why are we over on NP-MERIDIAN"**

`fin_variance_analysis` → `VARIANCE_TREE`. The only **recursive** payload in this engine.

⚠ **THE ROW FLOOR IS ALMOST MEANINGLESS HERE AND THE SHEET SAYS SO.** The payload is **one
row** — the root — and everything that matters hangs off it in `contributors`. `min_rows: 1` is
satisfied by a tree that decomposed into nothing at all. **What a walker must actually check is
on the screen:** that the tree has depth, that each branch says why it stopped
(`stop_reason`), and that the contributors under a node sum to that node's variance. A
decomposition whose children do not sum to their parent is the arithmetic lie this engine is
most likely to tell.

## 3. Which account is worst — the ranking

> **"which account is driving the overrun on NP-MERIDIAN"**

`fin_variance_drivers` → `CONTRIBUTION_RANKING`. Three rows, ordered by **absolute**
contribution with the sign on the row.

Check on screen that a **favourable** driver — positive variance inside an unfavourable root —
is not drawn as though it made things worse. The two signs on one row disagree and both are
correct, which is why the producer emits `favourable` rather than letting the card colour from
the number.

## 4. The funding position

> **"what is the funding status on NP-MERIDIAN"**

`fin_funding_status` → `SHORTFALL_GRID`. **Eighteen cells** — six funding lines across three
periods — of which the verdict says eleven are short.

Check that the grid draws **authorized / obligated / expended per line per period**, and that a
line which is *over*-obligated (committed more than authorised) does not render as a negative
shortfall. That is a real condition and the producer floors `shortfall` at zero, carrying the
signed figure beside it in `gap`.

## 5. Burn against the phased plan

> **"what is the burn rate on NP-MERIDIAN"**

`fin_burn_rate` → `MULTI_SERIES`. Six periods, **two declared series** — spend and the phased
plan — both in USD.

The verdict reads *"Spend above plan since FY26-04"*. Check the card draws **both** series and
not just cumulative spend: a single plotted line here is the defect, and it looks entirely
reasonable.

## 6. The performance indices

> **"show me CPI and SPI for NP-MERIDIAN"**

`fin_performance_indices` → `MULTI_SERIES`, six periods, two series, and **neither declares a
unit**. That absence is the assertion, not an omission — CPI is a ratio, and a dollar sign on
0.85 is a lie the producer would be telling.

Check the card draws the **1.0 reference line** and says nothing about which side of it is good.
For a performance index below 1.0 is unfavourable; for other ratios it is the opposite, so the
line is drawn and the judgement is left to the reader.

## 7. The estimate at completion — THE REFUSAL IS THE PASS

> **"what is the estimate at completion for NP-MERIDIAN"**

`fin_eac_calculation`. **This must NOT draw a card.** It must ask which method, naming all
three: CPI, CPI_SPI, REMAINING_AT_BUDGET.

**Scoring this red would fail the engine for doing the one thing it was built to do.** The
method slot is mandatory and carries no default because the three formulas disagree by about
13% of the budget on this very seed — a forecast with no method named is ambiguous by more than
a million dollars, and picking one silently is the failure ADR-0045 exists to prevent.

**Three option chips, and the count is the assertion.** The three values come out of the
`EACMethod` declaration, so a fourth formula appears in this refusal on the same edit that adds
it. An empty menu here is the defect — *"it asked"* and *"it asked answerably"* are different
facts and only the second is a usable refusal.

## 8. All three methods at once — the spread IS the finding

> **"compare the estimate at completion methods for NP-MERIDIAN"**

`fin_eac_comparison` → `COMPETING_MEASURES`. Three rows, one per method, and the spread stated
as a figure: **1,662,608 USD** across methods on this seed.

This verb exists because R-001 ruled that pinning one estimate hides the divergence that IS the
finding. So check the card shows the **spread**, not three numbers the reader has to subtract —
and that an undefined method **keeps its row with a reason beside it**, so three rows are never
mistaken for three answers.

⚠ **THIS CARD COULD NOT DRAW AT ALL UNTIL 2026-09-18.** The archetype existed at every layer
from 2026-09-11 — projector passthrough, component, contract, glyph — with this verb named in
its contract header as its first consumer, and **no capability row claimed it.** If it draws
with blank high and low figures, the projector's field names have drifted from the contract's
again; that pair is `lowest_value` / `highest_value`, not `lowest_eac` / `highest_eac`.

---

## What this sheet cannot tell you

**Every expectation here is one side of a mirror.** The census stores the same eight questions
and the seal compares them both ways, so a prompt reworded here without a matching census row is
red — but **nothing checks that these are the right eight questions.** They are the ones the
engine declares it owns. A phrasing a user would actually type, that no verb claims, is invisible
to this sheet and to the census both, and would show up only as a person asking something and
getting a knowledge document back.

**And a green census row is not a walked card.** The runner asserts route status, verb,
archetype and a row floor. Every defect the cost walk found — a single plotted series, a
neutral row coloured as an improvement, an overhead struck on the wrong basis — sat **inside** a
payload that would have passed all four.
