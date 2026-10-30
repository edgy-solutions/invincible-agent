# `policy/exports/` -- an export profile declares the kinds it takes

A row here declares one export deliverable. The loader is `agent_fleet/utils/answer_exports.py`
(read by the BFF and by engine-cost); the first kind is the **plan answers export**, one file with
one row per answer, for a recipient that receives a Portfolio board's planning answers.

**Kind:** `exports`, key `name`. One YAML file per row.

## The shared header

Every row opens with the same four keys. lane/01's ingest-review export shares this header, and
fin's CDRL profiles (`policy/fin_export_profiles/`) open with the same four, so one picker can
list every kind.

| key | meaning |
| --- | --- |
| `name` | the row's key; also part of the produced filename |
| `format` | `csv` or `json` |
| `scope` | what one row of the file is. Closed in this loader to `answer` (one row per answer); lane/01 widens it to `row` / `notice` when it adds the review kind |
| `label` | what the picker shows |

## The answer keys

| key | meaning |
| --- | --- |
| `kinds` | the verb IRIs this profile takes (`mesh:<Verb>`). Required, non-empty, no duplicates. An answer whose verb is not listed is refused `not_a_kind_this_recipient_takes`; an answer with no verb is refused `no_verb`. |
| `recipients` | the recipient scopes that receive this profile. Required, non-empty. A scope appears in at most ONE profile across the loaded set; two profiles naming one scope refuse the load, naming both. |
| `columns` | `[{field, as}]`. `field` is one of `answer_id, question, summary, verb, subject, program, status, valid_as_of`; `as` is the column header and must be unique. |
| `deleted: true` | the overlay tombstone (ADR-0036); it removes the seed row of that `name`. |

Anything else is a load refusal naming the key. A profile computes nothing: every cell is a value
the answer already carried. csv is CRLF with no BOM; json is `{"profile", "rows"}` with `None`
omitted; the same rows always give the same bytes.

## Seed and overlay

`plan_answers.yaml` is a SAMPLE seeded for the synthetic sandbox (a notional plan office). A
deployment replaces it, or adds its own, in an overlay directory:

    EXPORT_PROFILE_OVERLAY_DIRS=/app/policy/overlays/<deployment>/exports

(`os.pathsep`-separated, default empty). `EXPORT_PROFILE_POLICY_DIR` moves the seed. An overlay
row replaces the row of the same `name` whole. A malformed row set refuses to load, listing every
refusal.

## Kinds are an explicit list

`kinds` is an explicit list of verb IRIs. No wildcard (`*`, `mesh:*`) and no `all` exists; the
loader refuses each, and a bare string instead of a list.

**The plan recipient takes report verbs only** (ruled 10-29). `plan_answers.kinds` is these 11:

    planCostCurve, planFundingGap, planSiteLoad, planDependencyViolations,
    planDependencyNeighborhood, planMaturityGrid, planCapabilityPath, planProcessEvolution,
    planTechFootprint, planSchedule, planCoverageGap

and excludes the 3 session/scenario-state verbs, whose subject IS a scenario or session:
`planCommitScenario` (it writes baseline), `planDiff` (one plan state versus another),
`planSessionChanges` (a scenario's accumulated ops). A new Engine P verb is classified in
`tests/test_a_portfolio_board_exports_to_a_plan_recipient.py`, which fails until someone does.

A report verb computed against a scenario (`state_ref` other than baseline) is still the same
verb: this profile decides by verb, not by state. Whether it should is an open question with the
architect.

## Kinds are disjoint

`kinds` must not name a verb engine-cost exports (`cost_agent.canvas.EXPORTABLE`) or a verb
engine-fin serves (`VERB_TO_FN`): those answers belong to their own engines' exports. Sealed by
`tests/test_a_portfolio_board_exports_to_a_plan_recipient.py`, which also classifies
every verb Engine P declares as report or session-state and holds `plan_answers.kinds` equal to
the report set.

## Who may read a recipient's file

Not the profile. A reader is granted on the `recipient_readers` rail under owner `plan`
(`policy/recipient_readers.yaml`), and every route that offers, writes or serves the file asks
`can_read_recipient("plan", scope, caller)`.

**Until that owner exists on the rail, nobody can export to a plan recipient.** Readers are
granted on the `recipient_readers` rail under owner `plan`; the shipped
`policy/recipient_readers.yaml` has no `plan` owner today, so Topaz answers no relation and
`can_read_recipient` is False for everyone. The feature is dark by default, and that is
intended. It lights when governance widens the rail's `OWNERS` to include `plan`, adds the
reader rows, and the sync is run.
