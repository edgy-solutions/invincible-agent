# The 17 leadership questions → verbs

Gate 0 requires this map, and requires that **any question with no verb is flagged, not
fudged**. That instruction is followed literally below, including where following it is
inconvenient.

## ⚠️ Scope of this document — read before trusting a row

**The verbatim text of the 17 questions is not in this repository.** The plan carries them
only as `Q1`…`Q17` against a measure table. The "question shape" column below is therefore
**reconstructed from each verb's definition**, not transcribed from the source list.

Writing plausible question text here and letting it read as the leadership's own words would
be the phantom-citation defect this arc has now hit four times (filenames, line numbers,
conversational shorthand, section anchors) — a citation that is transcription, and
transcription lies. So the shapes are marked as inferred, and **the first task of the next
session with access to the source list is to replace this column and re-verify the mapping.**

Until then: the VERB column is real and tested. The SHAPE column is a hypothesis.

## The map

| Q | shape (INFERRED — verify) | verb | output_uri | state |
|---|---|---|---|---|
| Q1 | how does this business process evolve over time | `plan_process_evolution` | `mesh:PlateauTimeline` | tested |
| Q2 | which capabilities enable this process | `plan_process_evolution` | `mesh:PlateauTimeline` | tested |
| Q3 | capability maturity by site, versus target, as of a date | `plan_maturity_grid` | `mesh:MaturityMatrix` | tested |
| Q4 | what is scheduled, by initiative and phase | `plan_schedule` | `mesh:IntervalSchedule` | tested |
| Q5 | what is happening in a given window | `plan_schedule` | `mesh:IntervalSchedule` | tested |
| Q6 | what is happening at a given site | `plan_schedule` (`site_id`) | `mesh:IntervalSchedule` | tested |
| Q7 | which projects mature this capability, and by when | `plan_capability_path` | `mesh:ContributionSequence` | tested |
| Q8 | where is this technology used | `plan_tech_footprint` | `mesh:FootprintSet` | tested |
| Q9 | which sites are affected, and when | `plan_site_load` | `mesh:LoadThresholdGrid` | tested |
| Q10 | what blocks this / what does it block | `plan_dependency_violations` | `mesh:ConstraintViolationSet` | tested |
| Q11 | which sites are over their change-load threshold | `plan_site_load` | `mesh:LoadThresholdGrid` | tested |
| Q12 | what does spend look like per period | `plan_cost_curve` | `mesh:PeriodCostSeries` | tested |
| Q13 | where is funding short, by organization | `plan_funding_gap` (`org`) | `mesh:FundingGapSet` | tested |
| Q14 | where is funding short, by initiative | `plan_funding_gap` (`initiative`) | `mesh:FundingGapSet` | tested |
| Q15 | which organization is under-committed | `plan_funding_gap` (`org`) | `mesh:FundingGapSet` | tested |
| Q16 | where does spend exceed the cap | `plan_cost_curve` (`over_cap`) | `mesh:PeriodCostSeries` | tested |
| Q17 | capex versus expense, time-phased | `plan_cost_curve` (split by kind) | `mesh:PeriodCostSeries` | tested |
| — | what did this meeting change | `plan_session_changes` | `mesh:ChangeLog` | tested (INV-4) |

## Flagged: what the model does NOT answer

These are not verbs and must route to the refusal path. Listing them here is what makes the
refusal honest rather than a shrug — the system can say *what* it does not capture.

| asked-for | why the model cannot | disposition |
|---|---|---|
| ROI / NPV / payback on an initiative | no benefit or revenue entity exists; only cost | refuse; offer `plan_cost_curve` as nearest |
| risk owner, risk register, RAG status | no risk entity | refuse; nothing near — log the miss |
| headcount, FTE, resource levelling | no person or role entity; `load_weight` is site change-load, NOT labour | refuse. **Do not offer `plan_site_load`** — the units are unrelated and the offer would read as an answer |
| vendor / contract status | no contract entity | refuse; log the miss |
| benefits realisation against plateau | plateaus carry dates, not benefit measures | refuse; offer `plan_process_evolution` |

## A known limitation, recorded rather than papered over

`plan_capability_path` reports `contributions_outstanding` — *work is still landing after this
plateau's target date* — and deliberately does **not** report "the plateau was missed." The
model has no per-plateau maturity REQUIREMENT edge, so nothing can know whether a capability
already reached the level an early plateau needed before its last project finished.

Naming that field `missed` was the first draft and it overclaimed: the label would have been
read as a verdict and repeated in a room as one. A per-plateau maturity requirement is a
**model extension** and belongs in the miss-log as a Phase-7 candidate.
