---
id:         engine-f-subject-widening-results
status:     open
owner:      agent
blocked-on: seam 9 (the filler lane) — cards cannot draw until it clears
repo:       invincible-agent
ruled-by:   ADR-0045 (Engine F); ADR-0033 (route | ask | abstain)
code-site:  agent_fleet/finance_agent/main.py (also_askable_of), docs/measurements/engine-f-subject-widening-prereg.md (written first)
summary:    RESULTS against a pre-registration written before the run. P1 CONFIRMED — compatible_count 2 -> 6 on every draw that grounded. P2 CONFIRMED — all four widened verbs now route where they previously returned no_match: finBurnRate 0.96, finPerformanceIndices 0.96, finVarianceDrivers 0.86, finFundingStatus 0.96. P3 CONFIRMED AS PREDICTED — cards still draw as KNOWLEDGE_DOCUMENT on all six, because seam 9 stops every finance question before dispatch; this was predicted in advance precisely so an unchanged symptom could not be read as this change failing. R1 CLEAN — both controls still route correctly, though finVarianceAnalysis's confidence fell 0.96 -> 0.92 against six competitors instead of two, which is the measurable price of the widening. R3 CLEAN — primaries intact, 10 rows, 4 distinct subjects, so the two-names idiom held. ONE ROW FAILED TO GROUND on its first draw (subject_unknown) and grounded on both re-draws; it is a row ALREADY RECORDED as unstable, so n=3 cannot separate flip from cause and no claim is made.
---

# Results: widening the subject to `fin:Program`

Measured against [`engine-f-subject-widening-prereg`](engine-f-subject-widening-prereg.md),
written before the run. Six questions as alice, persona `PROGRAM_FINANCE_ANALYST`, domain
`PROGRAM_FINANCE`, through `/interview/stream` — the real path, sequentially, nothing else loading
the run queue.

## The table

| question | subject | `compatible_count` | verb chosen | conf | before |
|---|---|---|---|---|---|
| **CONTROL** EAC | `fin:Program` 0.96 | **6** | `finEacCalculation` | 0.96 | ✅ held |
| **CONTROL** variance | `fin:Program` 0.95 | **6** | `finVarianceAnalysis` | 0.92 | ✅ held (was 0.96) |
| burn rate | `fin:Program` 0.97 | **6** | `finBurnRate` | 0.96 | **was `no_match`** |
| CPI/SPI | `fin:Program` 0.98 | **6** | `finPerformanceIndices` | 0.96 | **was `no_match`** |
| drivers | `fin:Program` 0.92 | **6** | `finVarianceDrivers` | 0.86 | **was `no_match`** |
| funding status | see below | **6** | `finFundingStatus` | 0.96 | **was `no_match`** |

## Against each prediction

**P1 — the eligible set widens. CONFIRMED.** `compatible_count=6` on every draw that grounded,
with all six verbs present in `candidates`. This is the claim the change was making, and it is
asserted on the SET, which is the layer measured as deterministic.

**P2 — the four widened verbs stop returning `no_match`. CONFIRMED, 4 of 4.** Each previously
produced `classify_predicate no_match` with `compatible=['mesh:finEacCalculation',
'mesh:finVarianceAnalysis']`. Each now routes to its own verb.

**P3 — the cards still do not draw. CONFIRMED, and predicted.** All six ended
`archetype=KNOWLEDGE_DOCUMENT`. Seam 9 converts every finance question into an ask before
dispatch, so no subject-layer change can move this. **Recorded in advance for exactly this
reason:** it is the third time this session that a correct repair produced no visible movement
because another seam sat behind it, and without the pre-registration the honest-looking reading is
"the widening didn't work."

**R1 — the two verbs that already worked. CLEAN, with a measurable price.** Both controls routed
correctly against six competitors instead of two. `finEacCalculation` held at 0.96;
**`finVarianceAnalysis` fell from 0.96 to 0.92.** That is not a failure — it is the cost of the
widening showing up where it should, and it is worth watching rather than dismissing.

The thinnest margin is **`finVarianceDrivers` at 0.86**, the lowest of the six and the verb
semantically nearest `finVarianceAnalysis` — a ranked list of contributors versus a nested
explanation of the same variance. The `anti_synonyms` and the "NOT that other verb" clauses in
each `desc` held at six candidates, which is the first real test they have had.

**R3 — the primaries were not swept. CLEAN.** 10 Engine F rows across 4 distinct subjects;
`PerformanceMeasurementBaseline`, `ControlAccount` and `FundingLine` all intact, each of the four
widened verbs carrying two subjects. The two-registration-names idiom worked.

## The one row that failed to ground, and why no claim is made about it

The funding-status question's **first** draw did not ground at all:

```
subject_uri=UNKNOWN subject_conf=0.0 fallback_reason=subject_unknown
  → generalist fallback (ADR-0019 Contract B: no LLM call without subject grounding)
```

Re-drawn twice, identical phrasing, minutes apart:

```
subject_uri=fin#Program subject_conf=0.9  compatible_count=6  verb=mesh:finFundingStatus 0.96
subject_uri=fin#Program subject_conf=0.9  compatible_count=6  verb=mesh:finFundingStatus 0.96
```

**`"what is the funding status"` is already on the record as an unstable row** — it flipped
between `FundingStatusGrid` and `FundingLine` across earlier runs in
`[[the-winner-is-a-sample-the-set-is-the-answer]]`. So 1 failure in 3 draws on a known flipper is
not evidence of anything at this n, and treating it as caused by the widening would be exactly the
forbidden arithmetic that packet exists to refuse.

**What IS new and worth recording:** this row's instability now reaches the *grounding* layer, not
just the winner within a stable set. A `subject_unknown` is a different and worse outcome than a
different winner, because it skips the mesh entirely for the generalist fallback. Whether the
failure mode genuinely widened, or a third draw of a known-unstable row simply landed somewhere
new, **is not decidable at n=3 and is not decided here.**

## What this does and does not license

* **Does:** the coverage gap is closed. A question naming the program can now reach all six verbs,
  which was the entire content of `[[four-subjects-means-four-questions]]`.
* **Does not:** claim any card draws. None does, and none can until seam 9 clears.
* **Does not:** quote a total. Six questions, one draw each (three for funding). Set membership per
  row and named outcomes only — no n-of-6 score, per the standing finding.

## Owed

* Re-run once seam 9 clears — that is the run where P3 becomes a real test rather than a
  prediction, and where the archetype-hardened path is exercised end to end for the first time.
* Watch `finVarianceDrivers` (0.86) and `finVarianceAnalysis` (0.92) at higher n. If either drifts
  further, the descriptions need the discrimination sharpened, not the threshold moved.
