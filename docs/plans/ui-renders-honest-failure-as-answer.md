---
id:         ui-renders-honest-failure-as-answer
status:     open
owner:      agent
blocked-on: THE LIVE WITNESS, which is NOT blocked — steps 1/2/4 and the job-graph repair landed 2026-08-15, but the definition of done is a VALUE ON THE UI and only a live run proves that. Separately, the one remaining CODE step (3 — do not let an ungrounded run win a race against a grounded one) IS blocked on instance-resolution-nondeterminism, per that step's own precondition.
closed-by:
code-site:  agent_fleet/data_analyst/main.py, agent_fleet/data_analyst/outcome.py, agent_fleet/presentation_agent/main.py, src/iagent/defs/dynamic_supervisor.py
repo:       invincible-agent
summary:    HIGH — an ungrounded DA run returns `status: "success"` with an apology as its `data`, so nothing downstream can distinguish "here is your answer" from "I could not find the asset". Witnessed 2026-08-15: the data path SUCCEEDED and returned real rows, and the UI showed the apology from a concurrent run that did not ground.
---

# An apology that reports itself as a success

**Witnessed at work 2026-08-15 01:16.** The same question ran twice. One run resolved the
URN, queried MinIO, and returned `['00000', '00001']` — real CAGE codes. The other did not
ground, and that is the one the user saw.

The presentation agent's input, verbatim:

```json
"expert_response": {
  "status": "success",
  "data": "I couldn't locate a specific DataHub URN for the publog p_cage dataset,
           so I'm unable to retrieve cage values. If you can provide the exact URN...",
  "sources": [],
  "output_uri": "http://invincible-agent/mesh#DatasetAnalysisReport"
}
```

`status: "success"`. The text is an honest failure and the envelope says it worked.

## Nothing downstream can tell the two apart, and everything downstream behaved correctly

- **The presentation agent** matched `CHART_WIDGET` on the `output_uri`, got `chart_data: "[]"`
  from BAML (correctly — there are no rows in an apology), and fell back to
  `KNOWLEDGE_DOCUMENT honest fallback`. That fallback is well-built and did exactly what it
  should with what it was handed.
- **`DA_FUMBLE_METRIC`** logged `outcome=ok` for the ungrounded run, same as for the one that
  returned data. The metric inherits the same blindness.
- **Whatever selected between the two concurrent runs** had no signal to prefer the grounded
  one, because both claimed success.

So the defect is not in any of them. It is that the DA envelope has one field for two
outcomes, and the *whole* pipeline downstream is therefore reasoning about a distinction it
was never given.

## Why this one is high priority

Every other failure this week announced itself — a CrashLoop, a 404, a named `UNREGISTERED`
alarm. This one renders. A user asks a question the system CAN answer, and receives a
confident, well-formatted, articulate statement that it cannot. There is no error anywhere,
no alarm, and the log says `success` twice.

It is also the shape that makes every other fix unverifiable: with this in place, "did the
data path work?" cannot be answered by looking at the UI, which is the only place most people
will look.

## A THIRD mode: a crashed pipeline renders as a BLANK CARD

Dagster run `a62ab191`, 2026-08-14 20:12. Routing was perfect — `route_status=matched`,
`subject_instance_id` resolved to the correct s3 URN, `mesh:analyzeDataset` at 0.86. Then:

```
20:12:45.767  POST -> data-analyst:8089/analyze_data
20:13:13.747  RemoteDisconnected('Remote end closed connection without response')
20:13:13.769  generate_ui_payload   ERROR  Dependencies failed. Not executing.
20:13:13.787  synthesize_stateful   ERROR  Dependencies failed. Not executing.
```

`execute_subtask` raised, so the two steps that BUILD the UI payload never ran, and the card
showed the question and nothing else. Neither timeout is implicated — the supervisor allows
1800s (`dynamic_supervisor.py:1652`) and DA's proxy allows 1800s to the Restate ingress
(`data_analyst/main.py:627-648`) — so the DA process dropped the connection at 28s.

So the UI now has THREE ways to not answer, and a user cannot distinguish them:

| what happened | what the user sees |
|---|---|
| grounded, queried, rows returned | the answer |
| did not ground; `status: "success"` | a confident apology |
| pipeline CRASHED | **a blank card** |

The third is arguably worst: the failure is loud in Dagster, fully diagnosed in a stack trace,
and communicates nothing. The UI has no representation for "this failed" — only for "here is
an answer", which is why a failure has to borrow one of the other two shapes.

**A failed subtask must still produce a UI payload** saying what broke. That is a different
repair from the `status` fix — it lives in the job graph, where `generate_ui_payload` should
run on failure rather than being skipped as a failed dependency.

(The DA crash itself is a separate question — restart count, `--previous` logs, and OOM status
on that pod. But even once it stops crashing, this rendering gap stays.)

## Definition of done — stated because a green log is not it

**A VALUE on the UI**, for a query the data path can serve. Not `outcome=ok`, not a 200 from
`/render_ui`, not rows visible in the engine log. The number, in the interface.

## Work

1. **Give the envelope an honest outcome.** DA must distinguish *answered* from
   *could-not-ground* — a distinct `status`, and `sources`/rows as corroboration. The
   codebase already has this discipline elsewhere and names it: `/resolve`'s abstention gate
   separates `instance_not_found` from `subject_unknown`; the router separates
   `domain_scope_excluded` from `no_compatible_verbs`. Same move, at the DA boundary.
2. **Make the honest-empty path visible rather than decorative.** Once the status is
   distinguishable, the presentation agent can render "not found, here is why" as a
   deliberate state instead of inferring it from an empty chart.
3. **Do not let an ungrounded run win a race against a grounded one.** Needs
   [[instance-resolution-nondeterminism]] understood first — with grounding stable, the race
   may not arise; without it, a preference rule is the mitigation.
4. **`DA_FUMBLE_METRIC outcome`** should follow the same distinction, or it keeps reporting
   `ok` for runs that answered nothing.

## LANDED 2026-08-15 — three of the four steps, plus the job-graph repair

**Not closed.** The definition of done is stated above as *a VALUE on the UI*, and nothing below
is a live run. What changed is that the distinction now exists to be rendered.

| step | what landed |
|---|---|
| 1 | Engine DA emits `ungrounded` with a `reason`, distinct from `success`. Two symbolic discriminators, neither of which asks the model whether it answered: `resolved_instance_id` (known BEFORE the loop — empty means the run was structurally incapable of grounding) and a query that provably returned. |
| 2 | The presentation agent renders a DECLARED non-answer deliberately, upstream of archetype selection, on its own `X-Presentation-Path: declared-ungrounded`. |
| 4 | `DA_FUMBLE_METRIC` carries the same classification, so it can no longer log `outcome=ok` for a run that answered nothing. |
| job graph | A dead engine returns a typed `engine_unreachable` result instead of raising, so `generate_ui_payload` still runs and the user gets a card that says what broke rather than a blank one. |
| 3 | **NOT DONE** — blocked, see the header. |

### The corroboration signal is NOT `sources`, and that nearly went wrong

The obvious discriminator is "did we collect any sources". It is wrong: `_record_query_attempt`
fires **before** the fetch, deliberately, so the SourcesTrail can show *"we tried this"* when the
data plane is unreachable. A classifier keyed on `sources` being non-empty would therefore call a
failed read an answer — the original defect wearing a different signal. Successes are tracked
separately, and the seal asserts the classifier cannot even *see* attempts.

### Two design decisions worth arguing with

**`rows_returned: 0` on a `success` is an ANSWER, not an abstention.** "The query ran and the
table had no matching rows" is a result; "I never ran a query" is not. Collapsing them would
re-commit the one-field-for-two-outcomes defect one level down, in the direction that hides
working infrastructure behind an apology.

**The job-graph repair trades a red Dagster run for an honest card, and that is a real loss.**
The op now returns where it used to raise, so the run goes GREEN where it went red. Accepted
because the redness was being paid for by rendering *nothing* — but it is the shape this repo
distrusts, so the compensating controls are all three load-bearing: an ERROR log, output
metadata on the op, and a typed status that reaches the UI and can be counted. **If a run-level
red is wanted back, it belongs in a final op that reads the collected results and fails when all
of them are `engine_unreachable` — after the payload has been produced, never instead of it.**

### What the seals cover, and what they do not

`tests/test_da_outcome_distinguishable.py`, 12 tests, five mutations verified to go red
(zero-rows collapsed into ungrounded; the renderer forgetting `engine_unreachable`; the outcome
dropped from the durable step's success return; ungrounded collapsed back into success; the
success envelope losing its corroboration).

**Two of the first four seals did not bite and had to be rewritten** — they asserted a string
appeared *somewhere* in a function, which stayed true when the branch was replaced with
`if False:` and when the keys were deleted from the success-path return. Both were the scope
defect from [[a-green-check-proves-only-its-scope]], committed hours after that principle was
written. The repair was structural rather than a better grep: the envelope rule moved into the
dep-free `outcome.py` where a test can **execute** it, and the replay-trap check now selects the
`ok=True` return by AST instead of scanning the whole function.

**NOT SEALED, and stated rather than implied:** that a live run produces any of this. The unit
layer proves the rule; the UI is what proves the repair.

## Related

- [[instance-resolution-nondeterminism]] — why there were two runs with different outcomes at
  all. Fixing that removes the race; fixing THIS removes the class.
- [[da-schema-affordance]] — the same run burned 3 of 6 steps guessing a column name.
