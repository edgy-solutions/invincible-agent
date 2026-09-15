---
id:         the-burn-rate-figures-a-reader-acts-on-were-unsealed
status:     closed
owner:      lane/91 (invincible-agent-81)
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/finance_agent/measures.py (fin_burn_rate), tests/finance/test_the_burn_rate_means_what_it_says.py
summary:    Two figures in fin_burn_rate could be silently wrong with the full suite green — variance_to_plan with its sign flipped, and budget_remaining ignoring spend. THE CODE WAS CORRECT; nothing asserted that it was. Found by R-029's mutate-the-unit check before an ADR-0053 §7 extraction, sealed in b42ce8f. Filed separately from the extraction per the rule that a correctness gap found during a refactor does not ride in the refactor.
---

# The two burn-rate figures a reader acts on were unsealed

## What this record is, precisely

**Not a wrong answer that shipped.** `fin_burn_rate` computed both figures correctly, before and
after. What shipped was a **green that could not tell** — six mutations against a twelve-day-old
seal, six survivors. **The burn-rate card was proving the verb runs, not that it is right.**

Recording it as a defect record because the exposure was real and undated: any edit to those
lines, by anyone, would have landed with a full green.

## The two that matter

### 1. `variance_to_plan`, with its sign flipped

    "variance_to_plan": bcws - acwp        ->        acwp - bcws

**Positive means spending BELOW plan.** Flipped, a program running over plan reads as running
under it — and this seed **crosses that line**, from `+145,000` at FY26-02 to `-255,000` at
FY26-05. It is the single fact a reader acts on, and its sign was pinned by nothing.

### 2. `budget_remaining`, ignoring spend

    remaining = program.bac - cum_acwp     ->        remaining = program.bac

**Reports the full BAC forever.** In this seed the true figure falls from `10,995,000` to
`4,570,000` over six periods, so every row but the first was wrong under the mutation — and
`runway_periods` is computed from it, so **a program three periods from exhausting its budget
reads as comfortable.** One unsealed line, two wrong figures, both pointing the same reassuring
way.

## Why neither was caught

The standing seal exercised the verb — it called it, it checked the response had a shape — and
asserted nothing about the arithmetic. **R-029 in one instance:** *a seal that exercises a
function is not a seal that pins its algorithm.*

**And the age is why the check was run at all.** ADR-0053 §7's `seal_age_days` field showed
`803071e` dated 2026-09-02 against a run on 2026-09-14. Twelve days in a moving tree was enough
to ask whether the instrument still pinned anything; the answer was that it never had.

## What closed it

`b42ce8f` — nine seals, each recomputing from the **row's own published quantities** rather than
re-deriving from state, so a response whose variance disagrees with the amounts printed beside it
contradicts itself. All five real mutations now red.

**Four controls**, because each assertion is worthless without one: the sign must actually vary
across rows; `budget_remaining` must actually decrease; the smoothing must be active and the
window must fill; the trailing rate must diverge from the cumulative burn somewhere. **On a seed
lacking any of those properties the matching mutation is undetectable and the seal is green while
proving nothing** — so the controls fail loudly rather than letting the seals quietly stop
discriminating.

## The one that is not closed, and is not a defect

`and` → `or` in the skip rule survives. The two differ only on a period where **exactly one** of
plan and spend is zero, and this seed has none — measured: 6 both-zero, 6 neither, **0 partly**.
**A genuine equivalent mutant, recorded rather than forced**: contriving a seed to make it bite
would be testing the fixture.

**The extraction is what makes it testable.** Once the skip rule lives in a module taking
quantities directly, a partly-zero period is three lines to construct — `index_series` pins
exactly that case and could only do so *because* it was lifted. **The rule becomes testable by
being extracted**, which is an argument for the move beyond tidiness, and pinning it there is
owed by the commit that lifts it.
