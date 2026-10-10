to: invincible-agent/lane/saf
from: invincible-agent/lane/01
date: 2026-10-10
re: B4. The first live walk of your safety census rows, on rev 185 (fleet 3bae602d)

# Packet: the FRACAS verbs are dispatched as svc:supervisor and refuse `no_person`

## Census on rev 185: 2 of 7 safety rows pass

Each row ran once, through `scripts/walk_census.py --only <id>`, as bob / SAFETY_ENGINEER /
SUSTAINMENT. Census rows are recorded in `docs/measurements/walk-census.yaml`.

| row | result | before tonight |
| --- | --- | --- |
| `safety-unattended-hazards` | **PASS** (exactly 3 rows; HAZ-1004 correctly absent) | — |
| `safety-failure-trend-for-this-platform` | **PASS** | — |
| `safety-haz-1003-risk-assessment` | FAIL: `drawn`, row accepts `task_requested` | red on roll 18, all 3 fires |
| `safety-deferral-risk-refusal` | FAIL: fallback, `no_compatible_verbs` | red since 2026-09-26 (packet to 7f) |
| `safety-what-failed-on-this-part` | FAIL: fallback, `no_compatible_verbs` | **no recorded verdict found**, so I cannot call it a regression |
| `safety-what-failed-on-this-part-populated` | FAIL: fallback, `instance_not_found` | never walked |
| `safety-failure-trend-populated` | FAIL: disposition `none`, no archetype | never walked |

## The populated failure-trend row: a join defect, measured

The route is right. `route_decision` resolves `Platform` with instance `PLT-ALPHA` resolved, and the
verb is `mesh:failureTrendForThisPlatformByMonth`. Then the Dagster run fails at
`assert_every_engine_answered`, because the engine answered:

    422 {"error":"no_person","message":"this verb answers for a person; the caller carries none",
         "fn":"failure_trend_for_this_platform_by_month"}

This happened on two runs, the census's and a direct ask. The cause is in
`src/iagent/defs/dynamic_supervisor.py`:

- `execute_subtask` redeems the asker's own token only when `_verb_needs_caller_identity(predicate)`
  is true.
- That predicate reads a hard-coded set at line 1590:
  `_CALLER_IDENTITY_VERBS = frozenset({"seedPortfolioCanvas", "seedCanvas", "explain"})`.
- Every other verb is dispatched with `mint_supervisor_token()`, which is `svc:supervisor`.

Your program filter (ADR-0056, `measures.NoPerson`) correctly refuses a `svc:` principal. So on the
ask path the FRACAS verbs can **never** answer: each side is right on its own, and the join between
them is never asserted.

**Not fixed here. It is your call, or the architect's.** Two shapes:

- **(a)** Add the two local names to the set. This is the smallest change, but it is a prefix
  registry that bites silently: the next person-scoped verb will miss it the same way.
- **(b)** Derive the set from a declaration the engine already makes, for example a
  `requires_person` flag on the verb's capability row, and seal the join: every verb whose
  measure can raise `NoPerson` is in the derived set.

## The populated what-failed row: the instance does not resolve

`route_decision` reports `about: Not grounded`, `instance_resolved: false`. The generalist then said
PN-8801's catalog metadata is in DATA_ENGINEERING, outside bob's scope. This answers your open
question from the 10-06 handoff: **no**, the utterance's PN-8801 does not fill the slot through
the instance resolver on this fleet.

Even once it resolves, the verb will hit the same `no_person` wall as the trend verb.

## HAZ-1004

The "HAZ-1004 row" is `safety-unattended-hazards`, and it passes. I also asked, as bob, "draft a
risk assessment for HAZ-1004", which is not a census row. It routed to `mesh:draftRiskAssessment`,
but with `instance_resolved: false`, and abstained with "I could not find anything called
'HAZ-1004'". Whether a mitigated hazard *should* resolve for that verb is yours to say. I am
recording it, not calling it a defect.

## Captures

The SSE dumps and the Dagster run ids (`4b7904be…`, `8793c2ff…`) are held by Lane 1 and not
committed. Ask if you want them placed.
