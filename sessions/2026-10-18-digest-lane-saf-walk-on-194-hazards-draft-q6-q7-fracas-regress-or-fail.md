from: invincible-agent/lane/saf
to: invincible-agent/seat/architect
cc: invincible-agent/lane/01

# Digest, lane/saf, 2026-10-18: walk on 194 (helm rev 199, chart 0.4.54, cortex-bff 8a57437a) -- hazards draft; Q7 and FRACAS fail `no_person`; Q6 now asks

## Serving build (read-only; ns sandbox)

The cortex-bff image tag is 8a57437af272c14915ed94e303d8a748ad2fb6ae (read from the deployment, matches Lane 1's
report of rev 199). #70 is still OPEN, so Q9 and Q11 are NOT walked (deferred by ruling, to the build that
contains #70). Dagster STARTED/STARTING/QUEUED before the walk: 0 (read just before the first run; nothing
cancelled). I did not re-check ancestors of 8a57437a beyond Lane 1's report.

## Walk: 00:04Z-00:46Z, POST /orchestrate, cortex-ui, bob, 3 runs each (36 runs)

Request body carried `active_persona=SAFETY_ENGINEER`, `active_domains=[SUSTAINMENT]`. Run tags are only
`dagster/code_location=iagent`. Run config, same on every run read: user_email `bob@example.com`, user_id
4d51c8ab-53bc-4c0b-92f2-31bce2a94a11, user_persona `SAFETY_ENGINEER`, entitled_domains `SUSTAINMENT`; and
persona `PROCESS_ENGINEER`, domain `MAINTENANCE` -- NOT what the request carried (the known persona/domain
mismatch, Lane 1's).

| row | observed, 3 of 3 unless stated | vs sheet |
| --- | --- | --- |
| Q1 HAZ-1003 | draft, Medium, `risk_acceptance_medium:SUSTAINMENT`; `review_request.task_id` risk-acceptance-HAZ-1003; orphan "mitigation owned but never verified in the field" | tier as expected. Departure: the answer is a `KNOWLEDGE_DOCUMENT` card (the draft as JSON), the sheet says "not a card". I did not read `human_tasks`, so whether a task row exists is UNMEASURED |
| Q2 unattended | route `findOrphanedHazards`; `KNOWLEDGE_DOCUMENT` carrying the rows (HAZ-1001 rank 1 with share 0.3206, HAZ-1003 rank 2, ...) plus reason "a live view recomputes against moving state and is a standing contract; it requires a caller that has registered its own render menu. The one-shot rendering of the same data remains available." | DEPARTURE: sheet expects a `CONTRIBUTION_RANKING` card, 3 rows. Row count not checked here |
| Q3 deferral | runs 1 and 3: route `no_match` / `no_verb_classified`, `ELICITATION` ask, message "No registered capability confidently fit that question. These were considered: mesh:explain. Naming one, or rephrasing toward it, will route.". Run 2: routed to `mesh:explain`, `abstain`, "I could not find anything called 'this work order'. Nothing was run." | DEPARTURE: sheet expects a refusal asking for `work_order_id`; observed varies run to run (2 of 3 vs 1 of 3) |
| Q4 what failed | 3 of 3 `no_match` / `no_verb_classified`, same message as Q3 runs 1 and 3, options `mesh:explain` | DEPARTURE: sheet expects a refusal asking for `part_number`; `whatFailedOnThisPart` is not even considered |
| Q5 trend | route `failureTrendForThisPlatformByMonth`; `ELICITATION` ask, slot `platform_id`: "Which platform did you mean? Options: PLT-ALPHA, PLT-BRAVO, PLT-CHARLIE." | as expected (ask for the platform) |
| Q6 PN-8801 | route `whatFailedOnThisPart`; `ELICITATION` ask, slot `part_number`, reason `ambiguous_in_domain`, `free_text_reason` `no_provider`, options none: "Which part number? I heard 'PN-8801', which is not one of them. Name it and I will run this." | DEPARTURE: sheet expects a `CONTRIBUTION_RANKING` card, 1 row. The verb is never run; no part-number candidate was found |
| Q7 PLT-ALPHA | route `failureTrendForThisPlatformByMonth`; the Dagster step failed with a 422 from the safety engine: `{"error":"no_person","message":"this verb answers for a person; the caller carries none","fn":"failure_trend_for_this_platform_by_month"}`. SSE: `pipeline_error` `dagster_run_failed` then `pipeline_error` `ui_payload_timeout`, no `final_payload` | DEPARTURE: sheet expects a `MULTI_SERIES` card. Same cause as FRACAS |
| Q8 HAZ-1001 | draft, Serious, `risk_acceptance_serious:SUSTAINMENT`, orphan "no mitigation recorded" | as expected (same card-vs-task departure as Q1) |
| Q10 HAZ-1007 | draft, High, `risk_acceptance_high:SUSTAINMENT`, MIT-2107 owned and verified | as expected (same card-vs-task departure) |
| Q12 HAZ-1008 | draft, Low, `risk_acceptance_low:SUSTAINMENT`, MIT-2108 owned and verified | as expected (same card-vs-task departure) |
| HAZ-1004 | draft, Serious, `risk_acceptance_serious:SUSTAINMENT`, MIT-2104 owned and verified | as on 192 |
| FRACAS 5530-184 | route `whatFailedOnThisPart`, about `http://internal/components/5530-184`; the Dagster step failed with a 422: `{"error":"no_person","message":"this verb answers for a person; the caller carries none","fn":"what_failed_on_this_part"}`. SSE: `pipeline_error` `dagster_run_failed`, then `ui_payload_timeout`; no `final_payload` | refuses `no_person`, as predicted for 194 (Lane 1's identity fix is on lane/01-195) |
| Q9, Q11 | not walked | deferred until #70 is in a build |

Failed runs: Q7 x3 and FRACAS x3 (6 of 36), all `STEP_FAILURE` in `assert_every_engine_answered`.

## What this says

- The five hazard drafts hold on 194, with the same tiers as 192.
- Two things reach the safety engine as no person: the trend and the part-number verbs, when dispatched as the
  supervisor service (Q7, FRACAS). One cause (identity forwarding, Lane 1), two rows.
- Q3, Q4 and Q6 are routing/slot departures, not engine faults: the engine is not reached (Q3, Q4) or is reached
  only for an ask (Q6). I have not diagnosed them. Q6 changed since the sheet was written (the sheet is a card).
  I do not know whether it changed on 192 -> 194, because I did not walk Q6 on 192.

## Architect questions

1. Q6 asks for a part number it was just given (`no_provider`). Is this 194's `binds: identifier` change (the
   slot now needs a provider candidate that PN-8801 does not match), and who owns it: 74, Lane 1 or me?
2. Q3 and Q4 do not route to the safety verbs on 194. Were they ever walked after the router change, and are
   they in scope for me, or for the router's owner?
3. Q2 returns a `KNOWLEDGE_DOCUMENT`, not a `CONTRIBUTION_RANKING`. Is that the live-view refusal text in the
   payload (so the sheet is stale), or a regression?
4. The sheet says a draft makes a task and no card; every draft here is a card with a `review_request`. Should
   the sheet change, or is the card a defect? (Whether a `human_tasks` row exists is unmeasured by me.)
5. Do you want a `human_tasks` read for bob on the next walk? I cannot read it from here without a live read
   path you name.
