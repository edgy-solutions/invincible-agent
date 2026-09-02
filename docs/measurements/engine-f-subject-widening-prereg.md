---
id:         engine-f-subject-widening-prereg
status:     open
owner:      agent
blocked-on: results (this is the PRE-registration; the run follows)
repo:       invincible-agent
ruled-by:   ADR-0045 (Engine F); ADR-0033 (route | ask | abstain); the winner/set finding
code-site:  agent_fleet/finance_agent/main.py (also_askable_of), docs/plans/four-subjects-means-four-questions.md
summary:    WRITTEN BEFORE THE RUN, so the results cannot be read backwards into whatever they turn out to be. Predicts: compatible_count 2 -> 6 for a program-named question; classify_predicate no_match -> a named verb for the four widened verbs; and CARDS STILL DO NOT DRAW, because seam 9 (the fill_slots timeout) is untouched and stops all six regardless of subject. Registers TWO WAYS THIS CHANGE COULD MAKE THINGS WORSE — the two verbs that already worked now compete against six candidates instead of two, and a wrong pick among six is a REGRESSION this measurement must be able to see. Asserts on the candidate SET, never the winner, per the standing finding that the selection layer is not deterministic.
---

# Pre-registration: widening the subject to `fin:Program`

**Written before the run.** The point of writing it first is that "compatible_count went to 6" and
"the cards drew" are different claims, and only one of them is expected tonight — recording that
in advance is what stops the second being quietly substituted for the first.

## What changed

`fin:Program` is now an additional registered subject for `finBurnRate`,
`finPerformanceIndices`, `finFundingStatus` and `finVarianceDrivers`. Primary subjects unchanged.
Registrations 6 → 10. **Seam 9 (the `fill_slots` 20s budget) is untouched and belongs to another
lane.**

## Predictions

### P1 — the eligible set widens. **This is the claim under test.**

`compatible_count` for a question grounding to `fin:Program`: **2 → 6.**

Asserted on the SET, not the winner. `[[the-winner-is-a-sample-the-set-is-the-answer]]` measured
the candidate set as deterministic (0/20 flipped) and the winner as not (≥2/20), so the set is the
only thing at this precision that means anything.

### P2 — the four widened verbs stop returning `no_match` from a program-named question

Before: `classify_predicate no_match` for burn rate, funding status and CPI/SPI, with
`compatible=['mesh:finEacCalculation','mesh:finVarianceAnalysis']`. After: a named verb.

**P2 is weaker than P1 and deliberately so.** It runs through the selection layer, so a single
counter-example is not a refutation — it is a draw from a sampler.

### P3 — **THE CARDS STILL DO NOT DRAW.** Expected, not a failure of this change.

Seam 9 converts every finance question into an ask before dispatch: `fill_slots` times out at 20s,
the mandatory `program_id` is unfilled, the disposition correctly becomes an ASK, the ask card has
no `output_uri`, and `/render_ui` takes `fallback-no-output-uri` → `KNOWLEDGE_DOCUMENT`.

**So the end-to-end symptom is predicted to be UNCHANGED, and that must not be read as this change
failing.** It is the third time this session that one seam's repair produced no visible movement
because another was behind it — which is the whole argument of
`[[a-fallback-that-absorbs-every-failure-reports-none]]`.

**A card that DOES draw is the surprising outcome** and would mean `fill_slots` beat 20s on that
run — worth recording as evidence about the budget's margin, not as a win for this change.

## ⚠️ How this change could make things WORSE — registered in advance

### R1 — the two verbs that already worked now face five competitors

`finEacCalculation` and `finVarianceAnalysis` previously chose between **each other**. They now sit
in a set of **six**. A classifier that reliably separated 2 may not reliably separate 6, and the
prose descriptions were written when the discriminations that mattered were different ones.

**If EAC or variance analysis now mis-routes from a phrasing that previously worked, that is a
REGRESSION caused by this change**, and it is the outcome most likely to be explained away as
noise. Recorded here so it cannot be.

*Mitigation already in place:* every verb carries `anti_synonyms` naming the neighbours it is
confused with, and each `desc` states what it is NOT. This measurement is the first test of whether
those were written well enough to hold at six candidates.

### R2 — a widened set makes the ask worse, not better

If the disposition asks, its menu is built from the eligible set. Six verbs' worth of vocabulary in
one elicitation may be less usable than two. Not predicted, but watch the ask card text.

### R3 — the primary subjects could have been swept

The failure mode the seal exists for: if the two registration names collided, the four secondary
registrations would DELETE the four primaries, and `PerformanceMeasurementBaseline` /
`ControlAccount` / `FundingLine` would vanish from the verb rows. **Check the row counts, not just
that Program gained verbs.** Expected: 10 rows across 4 distinct subjects.

## What will be measured

1. Verb rows by `(verb, input_uri, tool_urn)` — expect **10**, 4 distinct subjects, primaries
   intact (R3).
2. `compatible_count` and `candidates` from `routing_decision` / `classify_predicate` per
   phrasing (P1, P2).
3. Whether EAC and variance analysis still route correctly from their previous phrasings (R1) —
   **these are the control**, and they are more important than the four new ones.
4. The card, end to end, for at least one question (P3).

## What will NOT be claimed

* No right-class **total** over the corpus. The selection layer is not deterministic at this
  precision and a total sums draws from it.
* No rate, no budget, no "n of 20 improved". Set membership per row, and named flips.
