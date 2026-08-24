# Demo script — STABLE PHRASINGS

Generated 2026-08-24 from three full 51-case runs at n=3 (verb-scored funnel B).

**Pick the script's final wordings from this list, not from memory.**

## Tier 1 — GOLD (46 phrasings)

Passed **stably in all three runs** — semantic retrieval ON, semantic retrieval OFF,
and post-contrast-fix. That is **9 consecutive correct routings each**, including with
the vector term removed. These are the safest words in the room.

### `capability_path` (3)
- [q7-a] "which projects mature Straight-through invoicing and by when"
- [q7-b] "what gets Straight-through invoicing to target"
- [q7-c] "who is doing the work on Straight-through invoicing"

### `maturity_grid` (3)
- [q3-a] "capability maturity by site versus target"
- [q3-b] "show me the maturity grid as of FY26-Q4"
- [q3-c] "where are we against where we said we would be"

### `process_evolution` (6)
- [q1-a] "how does the Financial Close Automation process evolve over time"
- [q1-b] "walk me through the plateaus for Financial Close Automation"
- [q1-c] "where is Financial Close Automation headed"
- [q2-a] "which capabilities enable Supply Chain Visibility"
- [q2-b] "what has to be in place for Supply Chain Visibility to work"
- [q2-c] "what feeds Supply Chain Visibility"

### `projects_in` (5)
- [q4-a] "what is scheduled by initiative and phase"
- [q4-b] "show me the plan broken out by initiative"
- [q5-a] "what is happening in FY26-Q3"
- [q5-b] "what runs during FY26-Q3"
- [q5-c] "what lands in the third quarter of FY26"

### `show_cost_curve` (9)
- [q12-a] "what does spend look like per period"
- [q12-b] "show me the cost curve"
- [q12-c] "how is the money phased"
- [q16-a] "where does spend exceed the cap"
- [q16-b] "which periods breach the funding cap"
- [q16-c] "where are we over budget" _(soft/colloquial)_
- [q17-a] "capex versus expense, time-phased"
- [q17-b] "split the spend by capex and expense over time"
- [q17-c] "how much of the spend is capital"

### `show_funding_gap` (9)
- [q13-a] "where is funding short by organization"
- [q13-b] "show the funding gap per funding org"
- [q13-c] "who has not put up their share" _(soft/colloquial)_
- [q14-a] "where is funding short by initiative"
- [q14-b] "show the funding gap broken out by initiative"
- [q14-c] "which initiative is underfunded"
- [q15-a] "which organization is under-committed"
- [q15-b] "which funding org has committed less than required"
- [q15-c] "who is short" _(soft/colloquial)_

### `show_site_load` (6)
- [q9-a] "which sites are affected and when"
- [q9-b] "show change load across the sites"
- [q9-c] "who is taking the hit and when"
- [q11-a] "which sites are over their change-load threshold"
- [q11-b] "which sites exceed the threshold in FY26-Q4"
- [q11-c] "which sites are overloaded" _(soft/colloquial)_

### `site_schedule` (2)
- [q6-a] "what is happening at Site A — Aurora"
- [q6-b] "show the schedule for Site A — Aurora"

### `tech_footprint` (2)
- [q8-a] "where is the Core ERP Platform used"
- [q8-c] "show the footprint of the Core ERP Platform"

### `what_blocks` (1)
- [q10-b] "what is Wave 1 Cutover waiting on" _(soft/colloquial)_

## Tier 2 — VERIFIED-FIXED (2 phrasings)

Failed before the dependency-verb synonym-collision fix; **pass now**, confirmed twice
in the deployed config (targeted n=3 re-check + the full final run). Safe to use, but
they depend on a fix landed 2026-08-24 — **re-verify if engine-p is rebuilt**.

### `downstream_of` (1)
- [q10-c] "what slips if Wave 1 Cutover slips"

### `what_blocks` (1)
- [q10-a] "what blocks Wave 1 Cutover"

## EXCLUDED — do not put these in the script (3)

| id | expected | why |
|---|---|---|
| q4-c | `projects_in` | stable OVER-REFUSAL — returns no_intent_match |
| q6-c | `site_schedule` | UNSTABLE — flips between two wrong verbs |
| q8-b | `tech_footprint` | stable OVER-REFUSAL — returns no_intent_match |

Their phrasings: "what is on the board"; "what is Aurora getting"; "what depends on the Core ERP Platform"

## Coverage warning for whoever writes the beats

Intents with at least one stable phrasing: **11**.
Intents with NO stable phrasing (do not build a beat on these): **none**

`site_schedule` has stable phrasings but its third (q6-c) is excluded — the intent is
usable, that particular wording is not.

**Slots are NOT measured.** These phrasings are verified to reach the correct VERB.
Whether the slots come back right is a separate arm funnel B does not score — see
`docs/proposals/typed-mutations-parsed-but-unconsumed.md`.