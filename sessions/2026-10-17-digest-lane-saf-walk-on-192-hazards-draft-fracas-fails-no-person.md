from: invincible-agent/lane/saf
to: invincible-agent/seat/architect

# Digest, lane/saf, 2026-10-17: walk on 192 (rev 197, image b89d4c95) -- the hazards draft; FRACAS fails `no_person`

## Serving build (read-only; ns sandbox)

Helm rev 197 (chart 0.4.52, deployed 2026-10-17 03:41Z; rev 196 superseded). cortex-bff and the
Dagster code location both run tag b89d4c95; pods started 03:41:49Z and 03:41:45Z. Ancestors of
b89d4c95 (checked): #58 0251006c, #60 434ee8f9, #61 2ddd1981, :242 739b0c74, 9ceb3862, #62 e5490b2d,
9989b82a. Dagster STARTED/STARTING/QUEUED before the walk: 0 (read 04:45Z, nothing cancelled).

## Walk: 04:46Z-05:08Z, POST /orchestrate, cortex-ui, 3 runs each

Run tags are only `dagster/code_location=iagent` (failed runs add `dagster/failure_reason=STEP_FAILURE`).
Run config (the person), same on every run read: user_email `bob@example.com`, user_id
4d51c8ab-53bc-4c0b-92f2-31bce2a94a11, user_persona `SAFETY_ENGINEER`, entitled_domains `SUSTAINMENT`.
Also on the config, unchanged from earlier builds: persona `PROCESS_ENGINEER`, domain `MAINTENANCE`.

| prompt | runs (UTC) | observed, 3 of 3 | vs expected |
| --- | --- | --- | --- |
| Q1 HAZ-1003 | 04:46-04:48 | draft, Medium, `risk_acceptance_medium:SUSTAINMENT`, orphan "mitigation owned but never verified in the field" | unchanged |
| Q8 HAZ-1001 | 04:50-04:52 | draft, Serious, `risk_acceptance_serious:SUSTAINMENT`, orphan "no mitigation recorded" | departure FROM 188-era `ambiguous_in_domain`, as expected |
| Q10 HAZ-1007 | 04:53-04:56 | draft, High, `risk_acceptance_high:SUSTAINMENT` | as expected |
| Q12 HAZ-1008 | 04:57-05:00 | draft, Low, `risk_acceptance_low:SUSTAINMENT`, MIT-2108 owned and verified | as expected |
| HAZ-1004 | 05:05-05:07 | draft, Serious, `risk_acceptance_serious:SUSTAINMENT` | as expected (was `ambiguous_in_domain`) |
| FRACAS "what failures are recorded for part 5530-184" | 05:01-05:03 | NOT `no_failures_recorded`: pipeline_error x2 per run (below) | DEPARTURE |

None of the five hazard prompts produced a refusal. Every card was `refused: false`, with a
`review_request` for the tier shown.

### FRACAS, verbatim (all 3 runs identical)

SSE pipeline_error events:
- `{"message": "Pipeline failed.", "kind": "retrieving", "retryable": false, "cause": "dagster_run_failed"}`
- `{"message": "Timeout or failed to fetch UI payload.", "kind": "composing", "retryable": true, "cause": "ui_payload_timeout"}`

Dagster run FAILURE, step failure text (service host elided) (runs 67ebdb17, 8eeafeb0, 6a87e2ef):
`1 of 1 subtask(s) could not reach their engine. ... mesh:whatFailedOnThisPart: HTTPError: 422 Client Error:  for url: <engine-safety>/measure/what_failed_on_this_part | body: {"error":"no_person","message":"this verb answers for a person; the caller carries none","fn":"what_failed_on_this_part"}`

What the logs show: routing bound subject `pcn#Component`, verb `mesh:whatFailedOnThisPart`
(score 0.96), and `slots_filled ... {'part_number': '5530-184'}`: the verb receives the BARE id, not
the IRI (confirmed from the run log). Engine S then saw `caller: svc:supervisor
(no-verification-key)` on `/measure/what_failed_on_this_part`, and `_visible_records` raised
`NoPerson`. That is the program filter doing what ADR-0056 Q2 says: a service identity is never a
member, so the answer is a refusal, not an empty list.

Reading: the earlier `unknown_part` (rev 193) hid this, since the shape check ran before the filter.
The identity does not reach Engine S on this path: the draft path's calls arrive as
`svc:supervisor` too, but `draft_risk_assessment` has no per-caller filter. Not a defect in the
verb. I did not touch `_visible_records` (ruled).

FRACAS therefore stays unresolved on 192; it needs the user identity carried on the
whatFailedOnThisPart dispatch (a routing/identity change, not Engine S).
