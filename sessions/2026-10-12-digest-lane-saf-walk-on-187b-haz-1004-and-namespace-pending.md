# Digest, lane/saf, 2026-10-12: walk on the deployed 187b fleet; namespace declaration pending #51

Deployed (kubectl --context edge, ns sandbox, read-only): iagent-engine-safety, iagent-engine-o and
iagent-cortex-bff all run image tag 49aa5e28cd70 ("chart 0.4.43, rev 187b"; in master). PR #46's
commits (b8b8fd04 and b4e9c862) are NOT ancestors of 49aa5e28, so the instance_id fix is NOT in the
safety image. Dagster STARTED/STARTING/QUEUED runs before the walk: 0 (no zombies; nothing cancelled).

Walk: bob, SAFETY_ENGINEER, [SUSTAINMENT], frontend cortex-ui, POST /orchestrate, 3x each.
| prompt | expected (sheet/census) | observed (3 of 3) | field |
| Q1 HAZ-1003 | task_requested | KNOWLEDGE_DOCUMENT carrying review_request risk_acceptance_medium:SUSTAINMENT, instance_resolved true; bff log "safety acceptance dispatched hazard=HAZ-1003 level=Medium workflow=risk-acceptance-HAZ-1003-medium" x3 | components[0].markdown_content.review_request; route_decision.about.instance_resolved |
| Q8 HAZ-1001 | task_requested | slot_abstain, no_members, total_count 0 | components[0].status/reason/total_count |
| Q10 HAZ-1007 | task_requested | same | same |
| Q12 HAZ-1008 | task_requested | same | same |
| HAZ-1004 (Chris) | task_requested | same: "I could not find anything called 'HAZ-1004'. Nothing was run." | same |
| FRACAS "what failures are recorded for part 5530-184" | what_failed_on_this_part card or unknown-part refusal | runs 1-2: ELICITATION no_verb_classified; runs 3-5 (a later batch): fallback "no registered capability's contract is satisfied by this payload" | components[0].reason |
HAZ-1004 is still ambiguous until #51 (and the member-key fix reaches the image). Exactly what came back:
the card says no_members; the ambiguity is carried by engine-o's log, not the card: "fan-out ...
claimants=['engine_o_sustainment','engine_safety_sustainment'] subjects=[pcn#Component, safety#Hazard]
... fill_slots: mesh:draftRiskAssessment.hazard_id could not resolve 'HAZ-100x' (ambiguous_in_domain)".
NEW: the same double claim hits HAZ-1001, 1004, 1007, 1008 (candidates 7/3/3/2); HAZ-1003 has ONE
claimant (candidates=1, engine_safety_sustainment only), which answers Lane 1's question of why 1003 binds.
Task ids: the only writes were 3 risk-acceptance dispatches for HAZ-1003, workflow id
risk-acceptance-HAZ-1003-medium (a human_tasks row id was not read; the runner cannot see it).
Q8/Q10/Q12 created none. Q9/Q11 not walked. Census rows were not run (greens belong to 49aa5e28).
Scratch only: lane scratch scripts saf_walk.py / saf_runs.py; first batch was cut at 12 of 18 by my own timeout.

#51 (74, engine-o one namespace one claimant): OPEN, so the HAZ-/CSI-/MIT- declaration and the unskip
are pending. Tests: unchanged tip b4e9c862, tests/safety 423 passed 5 skipped; refused/census trio 38 passed.

## Correction 2026-10-13: walk times re-stamped against 13:53Z (rev 187 = 49aa5e28 live since 13:53Z)
The roll line says e977c32b (13:33Z) was failed helm rev 188, replaced by rev 189 = 49aa5e28 at
13:53Z. My image check read 49aa5e28, and every batch ran after it. File mtimes (local CDT, +5h = UTC):
| batch | prompts | UTC (finished) | vs 13:53Z |
| 1 (cut at 12 of 18 by my timeout) | Q1, Q8, Q10, Q12 x3 | started ~16:20Z, last write 16:33:59Z | after, on 49aa5e28 |
| 2 | FRACAS runs 1-2 | last write 16:43:45Z | after |
| 3 | HAZ-1004 x3 | last write 17:05:29Z | after |
| 4 | FRACAS runs 3-5 | last write 17:10:29Z | after |
The Dagster STARTED-run check was ~16:20Z. NO RUN is before 13:53Z, so none drops out and NO ROW OF THE
DELTA TABLE MOVES. (Times are file mtimes, not event timestamps; to the minute at best.)
Q3 ruled (architect): the task existing is the pass; recorded in the walk sheet.
