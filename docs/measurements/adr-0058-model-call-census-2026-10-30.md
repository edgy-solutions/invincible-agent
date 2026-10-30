# ADR-0058 §4: the model-call census over the walk sheet

Lane 74, the first measurement for ADR-0058 (architect, 2026-10-28). It is a **floor** over the
walked population. It is not a measurement of what a budget would count.

## What was measured

- **Fleet:** every workload at image `4a5ff6b6`, chart 0.4.70, one replica each. No roll was in
  flight, and no other fire or walk ran in the window.
- **Population:** all 32 rows of `docs/measurements/walk-census.yaml`, fired by
  `scripts/walk_census.py --only <id>`, **one row at a time**: 14 as bob, 13 as alice, 5 as
  agent-user.
- **Window:** 2026-10-30 02:47:26Z to 04:11:22Z UTC (the evening of 10-29, local).
- **Per row:** the window ran from the row's start to 5 s after `walk_census.py` returned. Every
  engine's log was read for that window.

## Method: what was counted

| counter | source | what one line means |
| --- | --- | --- |
| BAML calls | BAML's own log. `BAML_LOG_LEVEL=info` is set in the chart values, so every BAML function call logs `[BAML INFO] Function <name>:` and then a `Client:` line with its stop reason and its tokens in and out | one model completion |
| Engine E's agent loop | `[Engine E CALIB] {...}`, one per run, field `n_steps` | `n_steps` model calls |
| data-analyst's agent loop | `DA_FUMBLE_METRIC ... steps=N`, one per run | about N−1 model calls (`steps` includes the task step) |
| requests | the transport-auth caller line, with `/version` and `/health` excluded | one authenticated request to that engine |

**Controls.**

- **One question per window.** The BFF logs one `orchestrate: user=` line per question, and every
  one of the 32 windows has exactly 1. So no row's count includes another question.
- **The two BAML counters agree.** The `Function` lines total 158, and the `Client` lines total
  158.
- **A silent engine is a real zero.**
  - engine-a, engine-w and data-analyst logged **no line at all** in any window.
  - Their request line does fire. Since their last start, each has logged 33 such lines, all
    `/version`, on 10-28 and 10-29, and none of them in the windows.
  - So no authenticated request reached them during the census. A broken capture would not explain
    the zero.

## Results

**Model calls per question (floor):**

| | value |
| --- | --- |
| minimum | 4 |
| median | 5 |
| maximum | 8 |
| total, 32 rows | 158 |
| tokens in / out, total | 150,185 / 42,337 |
| stop reasons | `stop` on all 158 |

**Where they were made:**

| engine | function | calls |
| --- | --- | --- |
| engine-o | `ExtractIntent` | 32 |
| engine-o | `DecomposeQuery` | 32 |
| engine-o | `ClassifyPredicate` | 33 |
| engine-o | `FillVerbSlots` | 31 |
| engine-o | `ClassifyDomainIntent` | 29 |
| engine-f | `DesignUI` | 1 |
| Engine E's loop (CALIB) | none ran | 0 |
| data-analyst's loop | none ran | 0 |

157 of the 158 calls are engine-o's routing. The one other call is engine-f's `DesignUI`, on
`finance-burn-rate`. engine-f received a `/render_ui` request on all 32 rows, but it made a model
call on only that one.

**Shapes per question:**

| rows | calls | what they were |
| --- | --- | --- |
| 25 | 5 | one each of the five routing functions |
| 4 | 4 | no `ClassifyDomainIntent`. These are 4 of the 5 docs rows: `docs-how-do-i-add-an-engine`, `docs-what-is-an-archetype`, `docs-how-do-i-add-a-canvas-template` and `docs-how-do-i-roll-a-service`. The fifth, `docs-how-do-i-add-an-engine-under-mesh`, made all five. |
| 1 | 4 | no `FillVerbSlots` (`sustainment-which-parts-does-pcn26-182-affect`) |
| 1 | 5 | four routing functions, without `FillVerbSlots`, plus engine-f's `DesignUI` (`finance-burn-rate`) |
| 1 | 8 | `ClassifyDomainIntent`, `ClassifyPredicate` and `FillVerbSlots` each twice: a second routing pass (`safety-deferral-risk-refusal`). Not diagnosed. |

**The walk outcome is recorded, not diagnosed.** 26 rows PASS and 6 FAIL. The failures are
`safety-haz-1001`, `-1003`, `-1007` and `-1008-risk-assessment`,
`safety-what-failed-on-this-part-populated` and `finance-burn-rate`. Five of them have the plain
5-call routing shape. `finance-burn-rate` also made 5 calls, but in the `DesignUI` shape above. A
failed row's count is still a count of the calls it made. Diagnosing the failures is Lane 1's.

## What the sheet does not reach

**No row reached an agent loop.**

- **engine-a, engine-w and data-analyst received no request at all** (the controls above).
- **engine-e received only** `/resolve_instance` and `/resolve_dmc`, 39 each. It logged no CALIB
  line, so it ran no agent loop.
- These engines answered with no BAML line in any window:
  - engine-cost, engine-fin and engine-safety through their `/measure/*` verbs;
  - engine-docs through `/explain`, with no model call;
  - engine-lg through one graph (`/graphs/fin_program_brief`).

So the census measures **routing**. It does not measure the agent loop, which ADR-0058 calls
unbounded. The ADR's figures for the loop are smolagents' default of 20 steps, which is not
verified here, and 10–15 calls on one question. Those 10–15 came from a retried timeout repeating
a prompt on revision 199, not from loop steps.

A budget calibrated on this census alone would be calibrated on 4–8 routing calls and would
never have seen a loop.

## Countable and not countable, per engine

This revises the static census at `4a5ff6b6`. That census found 35 sites: 18 BAML, 4 agent runs and
13 embeddings. It marked most BAML sites "not countable" because their call sites log nothing.

| sites | countable from logs? | how |
| --- | --- | --- |
| the 18 BAML sites (7 in engine-o, the rest in engine-a, engine-e, engine-w and engine-f) | **yes, per call** | BAML's own INFO log, whether or not the call site logs, as long as `BAML_LOG_LEVEL=info` stays set. The window is the correlation, because the line carries no case id. |
| Engine E's agent run | yes, per run | the CALIB line's `n_steps` |
| data-analyst's agent run | approximately, per run | `steps` − 1. The line carries no user, query or case id. |
| engine-w's agent run | **invocations only** | one line per `query_knowledge`, with no step count and no end line |
| engine-a's agent run | **no** | no per-run or per-step line on the success path. The loop the ADR worries about most is the one no log counts. |
| the 13 embedding sites | no; out of scope | Each is an embedding, not a completion. Most log only on failure. |

## What this means for ADR-0058 (observations; the numbers are the architect's)

1. **Routing costs 4–8 calls per question, median 5, on this sheet.** That is above "Q1 cost 4
   Engine O calls" in §4. All 32 rows made `ExtractIntent`, `DecomposeQuery` and
   `ClassifyPredicate`, and most also made `ClassifyDomainIntent` and `FillVerbSlots`.
2. **The loop term in "4 plus the loop cap" is unmeasured.** No walked question reached a loop.
3. **Measuring the loop needs two things this census lacked:**
   - rows that route to engine-a, engine-w, data-analyst or Engine E's `query_graph`;
   - a per-step or per-run line in engine-a. Without it, engine-a's loop stays uncountable from
     logs whatever is fired.

## Not done here

- No failing row was diagnosed, and neither was the 8-call second routing pass.
- No embedding was counted.
- Nothing was fired beyond the 32 sheet rows.
