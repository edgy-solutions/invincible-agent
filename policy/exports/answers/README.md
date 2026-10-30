# `policy/exports/answers/` -- an answer-export profile declares the kinds it takes

A row here declares one export deliverable with one row per answer. The loader is
`agent_fleet/utils/answer_exports.py` (read by the BFF and by engine-cost); the first profile is
the **plan answers export**, for a recipient that receives a Portfolio board's planning answers.

**This directory is fin's.** `policy/exports/*.yaml` (one level up) is lane/01's review export,
read by `src/iagent/export_profiles.py`, whose glob is not recursive. The two loaders speak ONE
profile language (the review export's keys) and are kept apart by this subdirectory only until the
export-profile header type lands in the SDK (iagent-mesh v0.9.12); one loader then reads both. A
join seal in `tests/test_a_portfolio_board_exports_to_a_plan_recipient.py` fails if either loader
can see the other's files.

**Kind:** `exports`, key `name`. One YAML file per row; `name` equals the file stem and matches
`^[a-z][a-z0-9-]{0,63}$`.

## The header

| key | meaning |
| --- | --- |
| `column_map_version` | `1`, the review export's `COLUMN_MAP_VERSION` |
| `name` | the row's key; also part of the produced filename; equals the file stem |
| `label` | what the picker shows |
| `format` | `csv` or `json` |
| `granularity` | what one row of the file is. Closed in this loader to `answer`; `notice_part` and `notice` belong to the review export's loader |
| `kinds` | the verb IRIs this profile takes (`mesh:<Verb>`). Required, non-empty, no duplicates. An answer whose verb is not listed is refused `not_a_kind_this_recipient_takes`; an answer with no verb is refused `no_verb`. |
| `recipients` | the recipient scopes that receive this profile. Required, non-empty. A scope appears in at most ONE profile across the loaded set; two profiles naming one scope refuse the load, naming both. |
| `columns` | see below |
| `deleted: true` | the overlay tombstone (ADR-0036); it removes the seed row of that `name`. |

## The columns

`columns` is `[{output, source: {field}}]`. `output` is the column header and must be non-blank and
unique within the profile. `source.field` is one of `answer_id, question, summary, verb, subject,
program, status, valid_as_of`. The review export's other column keys (`format`, `on_unresolvable`,
`landing`, `transforms`) and source keys (`row_field`, `absent_row`) are refused by name: this
granularity takes `source.field` only.

Anything else is a load refusal naming the key. A profile computes nothing: every cell is a value
the answer already carried. csv is CRLF with no BOM; json is `{"profile", "rows"}` with `None`
omitted; the same rows always give the same bytes.

## Seed and overlay

`plan-answers.yaml` is a SAMPLE seeded for the synthetic sandbox (a notional plan office). A
deployment replaces it, or adds its own, in an overlay directory:

    EXPORT_PROFILE_OVERLAY_DIRS=/app/policy/overlays/<deployment>/exports

(`os.pathsep`-separated, default empty). `EXPORT_PROFILE_POLICY_DIR` moves the seed (default
`policy/exports/answers`). An overlay row replaces the row of the same `name` whole. A malformed
row set refuses to load, listing every refusal.

## Kinds are an explicit list

`kinds` is an explicit list of verb IRIs. No wildcard (`*`, `mesh:*`) and no `all` exists; the
loader refuses each, and a bare string instead of a list.

**The plan recipient takes report verbs only** (ruled 10-29). `plan-answers.kinds` is these 11:

    planCostCurve, planFundingGap, planSiteLoad, planDependencyViolations,
    planDependencyNeighborhood, planMaturityGrid, planCapabilityPath, planProcessEvolution,
    planTechFootprint, planSchedule, planCoverageGap

and excludes the 3 session/scenario-state verbs, whose subject IS a scenario or session:
`planCommitScenario` (it writes baseline), `planDiff` (one plan state versus another),
`planSessionChanges` (a scenario's accumulated ops). A new Engine P verb is classified in
`tests/test_a_portfolio_board_exports_to_a_plan_recipient.py`, which fails until someone does.

Only baseline answers export (ruled 10-29). A report verb computed against a scenario
(`state_ref` other than `baseline`) is refused `scenario_answer`; the item carries `scenario_id`
and the reason names it (several distinct scenario ids are sorted and joined with `, `). The
state is read from the answer's `rendered_output` components' `state_ref` (Engine P echoes it, the
presentation agent copies it onto every component). Absent reads as baseline: a null or
unparseable `rendered_output`, or no component carrying `state_ref`, because baseline is Engine
P's default and pre-passthrough artifacts never carried the key. One refusal per answer, in the
order `no_verb`, `not_a_kind_this_recipient_takes`, `scenario_answer`.

## Kinds are disjoint

`kinds` must not name a verb engine-cost exports (`cost_agent.canvas.EXPORTABLE`) or a verb
engine-fin serves (`VERB_TO_FN`): those answers belong to their own engines' exports. Sealed by
`tests/test_a_portfolio_board_exports_to_a_plan_recipient.py`, which also classifies
every verb Engine P declares as report or session-state and holds `plan-answers.kinds` equal to
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

## can_export: who may produce the file

Producing a plan answers export needs Topaz `can_invoke` on the capability
`can_export:<profile name>` (`capability_grants`), on top of being a reader. It is **deny by
default**: a profile with no row is exportable by nobody.

- The row is governance's, not this directory's: `can_export:plan-answers` -> `portfolio-leads`
  (gov's #151). The export-door change adds no policy row.
- **Both doors check it**: the BFF's `POST /export/package` (403 `not_entitled_to_export`, after
  the reader check) and engine-cost's `POST /answers_export` (same refusal, before anything is
  written). A rail that cannot be asked is a 503 `can_export_unavailable`, never a deny. The
  picker and the offer list only recipients the caller is both a reader of and may export to.
- **The download does not check it.** can_export gates production; reading a produced package is
  a reader's act, so the download stays on `can_read_recipient`.
- One shared check: `agent_fleet/utils/export_capability.py`. It is the same question as the
  review export's `_may_export_profile`; the two fold together at iagent-mesh v0.9.12.
