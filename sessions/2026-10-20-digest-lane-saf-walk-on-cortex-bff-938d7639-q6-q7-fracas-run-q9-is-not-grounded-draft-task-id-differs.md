from: invincible-agent/lane/saf
to: invincible-agent/seat/architect
cc: invincible-agent/lane/01

# Digest, lane/saf, 2026-10-20: whole-sheet walk on cortex-bff 938d7639 (helm rev 204) -- Q6/Q7/FRACAS now run the verb; Q9 is not grounded; the draft card's task_id is not the task row's

## Build basis (read-only; ns sandbox)

- The walk STARTED on cortex-bff 016473bb (helm rev 203; Lane 1 labelled it 198). Q1 x3 ran there (same result as below). During the walk the deployment rolled to **cortex-bff 938d7639f89695ee88fc768739c7a3faf360a40b, helm rev 204, chart 0.4.61**; the safety engine image is the same sha. I discarded the rest of the 016473bb walk and re-walked the WHOLE sheet on 938d7639.
- 938d7639 is on `origin/lane/01-197`; its log carries f3f988a3 "199 pins cortex d44b0cc and turns the card's row-edit flag on". I saw no Lane 1 report saying 199 is live, so this digest labels the build by sha, not as 199.
- Ancestry of 938d7639 (checked with `merge-base --is-ancestor`): 42cf25c4 (Q6), 9f4e9395 (identity), 3a5c405e (#70) all yes. #75 (the sheet fix, tip d583ecc6) is NOT in it and is still open, so rows are judged against #75's wording ("a draft card AND a task").
- Free commit before the walk 11.3 GB and after 14.3 GB (floor 2 GB). STARTED/STARTING/QUEUED runs: 0 before the walk (read on 016473bb) and 0 after (read on 938d7639); none cancelled. No rolls, no writes. One forward per read; zero open at hand-back.

## Run check

All walk requests: bob, `active_persona=SAFETY_ENGINEER`, `active_domains=[SUSTAINMENT]`, `frontend_id=cortex-ui`. 41 of bob's Dagster runs in the window carry one config: `persona PROCESS_ENGINEER, domain MAINTENANCE, user_persona SAFETY_ENGINEER`, user_id 4d51c8ab-..., user_email bob@example.com (the known mismatch, Lane 1's). route_decision `acting` reads persona SAFETY_ENGINEER, domains [SUSTAINMENT] on every routed run. I pooled the run tags and did not separate them per run; I did not re-verify the 194 finding that bob's tags are only `dagster/code_location=iagent`.

## Walk table (3 runs each; "run" = the verb ran)

| row | result on 938d7639 | vs 194 |
| --- | --- | --- |
| Q1 draft HAZ-1003 | 3/3 run: Medium (II D), draft card + review_request, audience risk_acceptance_medium:SUSTAINMENT | same |
| Q2 unattended | 3/3 run (mesh:findOrphanedHazards, rows from HAZ-1001); archetype KNOWLEDGE_DOCUMENT, presentation_source `refused`: "a live view recomputes against moving state and is a standing contract; it requires a caller that has registered its own render menu. The one-shot rendering of the same data remains available." | same: the menu-survives-prime change did not move it |
| Q3 deferral | run 1 routed mesh:explain (engine docs): "I could not find anything called 'this work order'. Nothing was run." Runs 2-3 `no_match no_verb_classified`: "No registered capability confidently fit that question. These were considered: mesh:explain." | same |
| Q4 what failed | 3/3 `no_match no_verb_classified`, about Failure Record, considered: mesh:explain only | same |
| Q5 trend | 3/3 ask: "Which platform did you mean? Options: PLT-ALPHA, PLT-BRAVO, PLT-CHARLIE." (reason slot-unfilled) | same |
| Q6 PN-8801 | 3/3 **run** (mesh:whatFailedOnThisPart, refused false): failure_count 1, FR-6001, sor-events-a:EVT-55101, platform PLT-ALPHA; presentation_source `refused` (live-view reason as Q2) | departure confirmed: was an ask |
| Q7 PLT-ALPHA | 3/3 **run** (see the retry round below): 2026-03 failure_count 1, FR-6001; presentation_source `refused` as Q2 | departure confirmed: was 422 no_person |
| Q8 HAZ-1001 | 3/3 run (on the retry round): Serious (I D), audience risk_acceptance_serious:SUSTAINMENT | same |
| Q9 HAZ-1005 | **3/3 not grounded**: `no_match subject_unknown`, about "Not grounded", Engine A fallback, candidates []. Answer verbatim: "The risk assessment for HAZ-1005 cannot be provided because the catalog metadata resides in the DATA_ENGINEERING domain, which is outside of the current access scope. No metadata was retrieved." The #70 evidence block was never reached. | new row; expected the closed-hazard refusal |
| Q10 HAZ-1007 | 3/3 run (plus 2 earlier runs, one a Dagster FAILURE): High (I B), audience risk_acceptance_high:SUSTAINMENT | same |
| Q11 HAZ-1006 | 3/3 refused, outcome `not_assessed`, reason verbatim: "hazard 'HAZ-1006' has not been assessed: severity and probability are not assessed on this hazard; no risk level is resolved and no authority is implied. Held: status not_assessed; neither severity nor probability held; opened 2026-08-30. To proceed, obtain a severity and probability assessment for HAZ-1006." evidence: `{"hazard_id":"HAZ-1006","status":"not_assessed","severity":null,"probability":null,"opened_on":"2026-08-30","mitigations":[],"closure_record":"not held"}` | matches #70 |
| Q12 HAZ-1008 | 3/3 run: Low (IV E), audience risk_acceptance_low:SUSTAINMENT | same |
| HAZ-1004 | 3/3 run: Serious (III B), audience risk_acceptance_serious:SUSTAINMENT | same |
| FRACAS 5530-184 | 3/3 refused, not `no_person` any more: outcome `no_failures_recorded`: "no failures recorded for part '5530-184': no source this engine reads holds a failure for it" | departure confirmed |

Intermittent failures, all on the first pass in a slow window (runs took about 3 minutes, and another lane's `Tell me about procedure TEST-1234` runs failed after 365 and 970 seconds in the same window): Q7 run 3 and Q8 runs 1 and 2 were `pipeline_error` "Failed to determine execution intent." (kind understanding, cause route_intent_failed, retryable true); one Q10 run was a Dagster FAILURE after 306 s. A retry of Q7 and Q8 (3 each) was 6/6 clean at about 75 s per run. I did not find the cause; the window coincided with the load above, which is a correlation only.

## Task matches (GET /me/human_tasks as bob; ids and status only)

- Before and after every draft run the list was read (21 to 23 tasks). The walk created no new risk-acceptance row: bob sees exactly two, `risk-acceptance-HAZ-1008-low~1:acceptance` (pending, created 2026-10-17) and `risk-acceptance-HAZ-1003-medium~1:acceptance` (pending, created 2026-10-04). The count moved 22 to 23 once, during the HAZ-1004 runs, and I did not identify that row as a risk-acceptance one.
- **The card's id is not the row's id.** Every Q1 card carries `review_request.task_id = "risk-acceptance-HAZ-1003"`; the row is `risk-acceptance-HAZ-1003-medium~1:acceptance`. Equality matches 0 of the draft cards. The two agree on subject_ref, kind and audience, so I matched by those. The card has no `workflow_id`. The engine builds the short form (`measures.py:494`, `f"risk-acceptance-{h.hazard_id}"`). This answers Lane 1's packet of 10-18: on this build the field really is the short form.
- Matched by kind + subject_ref + audience: Q1 (HAZ-1003 medium) and Q12 (HAZ-1008 low) have a row. Q8 (HAZ-1001 serious), Q10 (HAZ-1007 high) and HAZ-1004 (serious) have NO row in bob's list. I believe that is audience gating (bob not entitled to serious/high), not a missing row, but I did not measure it.

## Questions (numbered)

1. Lane 1: is cortex-bff 938d7639 / rev 204 what you call 199? If a 199-labelled sha differs, which rows would it change?
2. Lane 1 / cortex: the card's `review_request.task_id` (`risk-acceptance-HAZ-1003`) differs from the row's (`risk-acceptance-HAZ-1003-medium~1:acceptance`). Which side moves, or is the card meant to carry the workflow id? Until then an `/act` from the card by that id has nothing to equal. (Mine to change if the answer is the engine, `measures.py:494`.)
3. Who owns Q9? HAZ-1005 is closed and is in `entities.py`, but the router returns `subject_unknown` and the generalist answers from the DATA_ENGINEERING catalog. HAZ-1006 and the open hazards resolve. I have not looked at the instance resolution that drops it; I suspect closed hazards are not in what the router resolves against, but that is a guess.
4. Q2/Q6/Q7: presentation_source is `refused` for all three, with archetype KNOWLEDGE_DOCUMENT and the whole answer as a JSON block in the markdown. Is that the intended end state until a frontend registers a menu, or should the sheet name it?
5. Q3/Q4: unchanged, still the router's (Lane 1's packet of 10-18). Nothing new seen.
6. Held for Chris (morning): are serious and high tasks meant to be absent from bob's list?
