# Unminted-caller enumeration — platform pass

> **STATUS: PLATFORM ONLY.** `iagent-mesh-sdk`, `dag-tools`, `doc-tools` and `cortex-ui` are
> **not swept** and are the majority of the remaining risk surface.

## READ THIS FIRST — the classifier was wrong THREE times, in three different ways

This is the section that governs how every row below should be read.

**Three automated passes over one tree produced three different answers, and each was wrong
differently:**

1. **Indirection defeats a string match.** Pass 1 flagged `dynamic_supervisor.py:1037` UNMINTED.
   It is minted — the credential attaches inside `_telemetry_headers(config)`, so searching the
   call block for `Authorization` finds nothing.
2. **Over-resolution drops true positives.** Pass 2 resolved helpers and then reported only ONE
   minted call, losing four that reading confirms are minted. Target regex and window too narrow.
3. **A 20-line window cannot see past a 15-line comment.** Pass 3 reported nine callers
   "RAISES, uncaught" and three "unchecked — body used as result". **Both were false.** These
   call sites carry long explanatory comments between the request and its handling, so the
   window ended before `raise_for_status()` and before the enclosing `except`. There are **zero**
   unchecked consumers, and the raisers split roughly evenly between stopping and degrading.

The third error is the instructive one: it produced a **severity-above-the-flip emergency** —
"a 401 body becomes a supervisor result, live in OBSERVE today" — that does not exist. It was
about to be filed as its own board item. **A classifier that errs in three directions on one
corpus is a candidate generator, not an oracle.**

**Closing this item means READING each candidate, not re-running the script.** A flip gated on a
count from this classifier would be a signature over a guess — and the guess was wrong three
times in one evening.

## CONFIRMED MINTED — read individually

| site | credential | target |
|---|---|---|
| `dispatch_driver.py:221` | `mint_service_token()` → Bearer | cortex-bff `/internal/human_tasks/register` |
| `dispatch_driver.py:371` | `mint_service_token()` → Bearer | cortex-bff `/triage_tasks` |
| `extraction_review_sensor.py:555` | `Bearer {token}` | review start |
| `extraction_review_sensor.py:592` | `Bearer {token}` | review start |
| `dynamic_supervisor.py:1037` | `_telemetry_headers(config)` | engine-A `/analyze` |
| `dynamic_supervisor.py:1650` | `_telemetry_headers(config)` | engine leg |

**A question, not a finding:** `dispatch_driver` mints via `mint_service_token()`, which reads
`REVIEW_STARTER_CLIENT_ID` behind a general name — the exact shape that made the supervisor
dispatch as the review starter. It may be correct here (dispatch_driver runs in that process),
but *correct-by-coincidence and correct-by-design are different*, and the decoded subject on
those two calls should be witnessed rather than assumed.

## CANDIDATE UNMINTED — 19 sites, corrected failure modes

Every site below lacks a credential. The severity column is **effective behaviour under
REQUIRE**, re-derived with a window that reaches past the comment blocks:

### STOPS the caller — 9

`review_composer.py:94` · `dispatch_driver.py:247` · `restate_analyst/main.py:544` ·
`policy_rules_client.py:75` · `spo_interview.py:113` · `spo_interview.py:154` ·
`spo_step_executor.py:96` · `agent_routers.py:65` · `agent_routers.py:193`

These raise with no enclosing handler. Under REQUIRE the caller fails — for the composer,
verified: every review fails to COMPOSE, which is worse than every subject going unresolved
because an unresolved subject is a handled outcome.

### DEGRADES — 10

All `dynamic_supervisor.py` sites (`146`, `280`, `362`, `679`), all `gateway.py` sites
(`124`, `956`, `2641`), `spo_interview.py:176`, `restate_analyst/main.py:2157`,
`decision_record_writer.py:71`.

They raise and catch, or never raise. A 401 degrades the request rather than stopping the
service.

### What this changes about the flip

**The supervisor and the gateway degrade; the analyst-side callers stop.** That is a materially
different — and more tractable — picture than "the fleet stops", which is what the uncorrected
numbers said. The remediation arc is real but bounded: nine call sites, concentrated in
`restate_analyst` and `agent_routers`.

**Zero sites consume a 401 body as a result.** The "wrong data silently, live in OBSERVE"
emergency was an artifact of the window, not a property of the code.

## Not swept — the majority of remaining risk

`iagent-mesh-sdk` (MeshClient.ask, registration transport), `dag-tools` (central_gateway,
CortexDataClient), `doc-tools` (ingest→mesh calls), `cortex-ui` (browser calls terminating on
gated routes). **Stated because "the repo I was in" is exactly how `review_composer` stayed
invisible** while the platform's registration callers were being enumerated carefully.

## Acceptance

- Every candidate above read and confirmed or reclassified.
- Four remaining repos swept the same way.
- Each confirmed-unminted caller either minted, or exempted with a stated reason.
- A guard that fails when a new mesh-targeted outbound call appears unclassified — otherwise
  this is a one-time census and the next `review_composer` arrives unannounced.
