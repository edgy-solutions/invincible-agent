from: invincible-agent/lane/saf
to: invincible-agent/lane/01
cc: invincible-agent/seat/architect

# FRACAS on 188: subject UNKNOWN, and the Dagster run tags carry no caller key

Placed untracked; Lane 1 reads and commits it. Read-only measurement; nothing changed.

## Build
helm release iagent rev 191, chart invincible-agent-0.4.45, image c9091040f003a184f30534972c595d5381f0e819 (cortex-bff and Dagster code location).

## Runs ("what failures are recorded for part 5530-184", bob, SAFETY_ENGINEER, [SUSTAINMENT])
| supervisor start (UTC, 2026-10-15) | run id | status |
| --- | --- | --- |
| 02:25:58 | 7ba1339c-7a5a-463e-a025-9c1dc15f1f62 | SUCCESS |
| 02:28:08 | 16cbfe9b-e9cd-4ab2-9f3a-1327f8b1d568 | SUCCESS |
| 02:29:59 | 32ff4772-ca7c-4fbc-8ea0-3a7e39ceaff3 | SUCCESS |

All three: route_status=no_match, reason_code=no_compatible_verbs, subject UNKNOWN, verb UNKNOWN, classify_called=false, Engine A fallback. Final: KNOWLEDGE_DOCUMENT, "no registered capability's contract is satisfied by this payload".
context_update names "Part 5530-184" while route_decision says "Not grounded" (instance_resolved=false).

## Run tags (read-only Dagster GraphQL)
Each of the three runs has exactly one tag key: `dagster/code_location`. No on_behalf_of key, no caller key, no persona/user key. So the caller identity is not carried on the run tags. (Whether it travels in run config or inputs instead was not examined.)

## Ruling (Chris, via coordinator, 2026-10-14), quoted
"the subject should resolve to part 5530-184 whether or not FAILURE_SOURCE_CONNECTORS is set. An UNKNOWN subject means the caller's identity is not reaching the router. That trace is Lane 1's, not yours."
The trace is yours; lane/saf has not touched it.
