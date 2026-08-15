---
id:         ui-renders-honest-failure-as-answer
status:     open
owner:      agent
blocked-on: nothing — HIGH PRIORITY. Definition of done is a VALUE on the UI for a query the data path can serve, not a green log.
closed-by:
code-site:  agent_fleet/data_analyst/main.py
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

## Related

- [[instance-resolution-nondeterminism]] — why there were two runs with different outcomes at
  all. Fixing that removes the race; fixing THIS removes the class.
- [[da-schema-affordance]] — the same run burned 3 of 6 steps guessing a column name.
