# lane/saf -- FRACAS repro on 188 (3 runs), HAZ re-walk held for 188b

to: invincible-agent/seat/architect (cc invincible-agent/lane/01)

## Build serving
- helm release `iagent` rev 191, chart invincible-agent-0.4.45, deployed 2026-10-13 11:36:32 CDT.
- cortex-bff, dagster user-code, webserver and daemon all run image tag c9091040f003a184f30534972c595d5381f0e819
  (merge "lane/01-failure-reaches-row (6d5c791f) into rev 188").
- cortex-bff pod started 2026-10-13T16:36:47Z; user-code pod 16:36:43Z. 188 live from about 16:36Z on 10-13.
- Dagster STARTED/STARTING/QUEUED runs before the walk: 0 (no zombie).

## Runs ("what failures are recorded for part 5530-184", bob, SAFETY_ENGINEER, [SUSTAINMENT])
| # | supervisor run start (UTC, 2026-10-15) | run id | route | final |
| --- | --- | --- | --- | --- |
| 1 | 02:25:58 | 7ba1339c | no_match / no_compatible_verbs, subject UNKNOWN, Engine A fallback | KNOWLEDGE_DOCUMENT; "no registered capability's contract is satisfied by this payload"; 6 refusals |
| 2 | 02:28:08 | 16cbfe9b | same | same |
| 3 | 02:29:59 | 32ff4772 | same | same |

All three agree. No disposition and no verb: the question never reaches a verb (verb=UNKNOWN, classify_called=false).
`on_behalf_of`: no log line in cortex-bff or the code location names it (0 matches over 30 min), so
whether it reached the supervisor is NOT observable from logs; unexamined, not proven either way.

## Delta against 187
187 gave no_verb_classified, then "no registered capability's contract is satisfied by this payload".
188 gives the same fallback text with the route shape no_compatible_verbs (not no_verb_classified);
the refusal text is unchanged. Subject stays "Not grounded" although context_update names "Part 5530-184".
Q6/Q7 rows untouched (FAILURE_SOURCE_CONNECTORS pending). HAZ/Q1/Q8/Q10/Q12 held for 188b.
