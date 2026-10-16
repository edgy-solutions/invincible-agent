# Hand-repro walk sheet -- Lane 1

**What this sheet is.** Questions a human asked in a real session that went wrong, in the asker's
EXACT words. They are deliberately NOT catalogue synonyms: the wording a person used is the thing
the walk measures. No synonym seal applies to this sheet (contrast `safety-walk-sheet.md`, whose
prompts must be an engine's declared synonyms). Each row names who asked, on which revision, and
what it answered then.

`docs/measurements/walk-census.yaml` stores each question and is checked against the prompts below
in both directions by `tests/test_the_walk_census_is_derived_from_the_sheets.py`.

| Q | question | verb | what a PASS looks like |
|---|---|---|---|
| 1 | what failures are recorded for part 5530-184 | `what_failed_on_this_part` | **a refusal (no failures recorded)**: outcome `no_failures_recorded`, the reason naming 5530-184; never an abstain |

---

## Q1 -- Failures recorded for a PCN26-184 part  **expect a REFUSAL (no failures recorded), never an abstain**

> **"what failures are recorded for part 5530-184"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT`
**Asked by:** Chris, by hand, on rev 185. **It answered:** "NOT GROUNDED / no capability for this
subject" -- the supervisor's `no_verb_classified` abstain (`src/iagent/defs/dynamic_supervisor.py`).
**Expected disposition:** `refused`, one disposition only -- **NOT YET WALKED LIVE** (walk after 189 rolls).

The closest declared synonym is "what failures were recorded for this item"
(`agent_fleet/safety_agent/main.py`:238-243); the asker's wording differs ("are recorded for part"),
and that difference is the point. 5530-184 is a PCN26-184 part: it resolves to a `pcn:Component`
that no failure source holds a record for, and it is not a safety-critical item. Since #57
(lane/saf `e862aae1`), the engine's answer is the no-failures-recorded refusal: outcome
`no_failures_recorded`, a reason naming 5530-184, and no task
(`tests/safety/test_a_part_number_is_settled_by_the_verb_asked_across_classes.py`,
`test_a_resolved_component_with_no_records_gets_no_failures_recorded_and_no_task`).
`unknown_part` is kept for a part string that resolves to nothing.

### What a correct result looks like BROKEN

- **An abstain / "no capability for this subject".** That is the 185 defect: a routing miss.
- **A generalist fallback.** Same defect, answered by the wrong party.
