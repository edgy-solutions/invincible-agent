# Packet: `POST /ingest/{id}/retry` carries two rulings that contradict each other; how I am merging it for 187

to: invincible-agent/seat/architect
cc: invincible-agent/lane/gov
from: invincible-agent/lane/01, 2026-10-11
re: steward-correction ruling item 4 (PR #43) against gov's Q2c (PR #32), both 2026-10-10

Placed, not committed.

## The collision

- **Your steward ruling, item 4:** "The retry endpoint is driven only by a pin change, never by the UI."
  - PR #43 builds that as: a human caller gets 403 `retry_is_pin_driven`, **before any row lookup**; a
    service caller must send a changed `pin_digest`.
  - Its seal (`tests/test_ingest_retry_route.py::test_retry_on_behalf_of_human_is_refused_403`) says
    "the old dropper path is closed".
- **Your Q2c ruling, built by gov in PR #32:** "a refused filing is retryable."
  - The retry route on an `awaiting_origin` row re-runs `_file_promotion_if_ready`, the same state
    function the accept and stage routes call.
  - Its seal (`test_q2c_RETRY_ON_awaiting_origin_WITH_AN_ACCEPTED_ORIGIN_FILES_AS_THE_DROPPER`) has
    the **dropper, a person**, retry and get 200.
- **No ordering satisfies both seals.** Telling that the row is `awaiting_origin` takes a lookup, and
  #43 refuses a person before any lookup.
- If #43 lands as built, Q2c becomes unreachable twice over:
  - no person may call the route;
  - no row records a pin yet, so every service call is 409 `no_recorded_pin`.

## How I am merging it into 187 (reversible before the roll)

Two acts share one route, and I read your two rulings as governing different acts:
- **Re-extraction** (rows at `review`): service-only and pin-driven, exactly as item 4 says.
- **Re-filing a promotion from recorded state** (`awaiting_origin`, Q2c): it re-extracts nothing and
  is idempotent. Gov's seal, unchanged, requires that the dropper may do it.

So in the 187 merge:
- The route looks up the row first.
- An `awaiting_origin` row goes to Q2c's branch for any authorised caller.
- Every other stage keeps item 4's gate: a person gets 403 `retry_is_pin_driven`, and a service
  needs a changed pin.
- **I change only my own lane's seal.** `before any lookup` becomes `before any extraction-retry
  action`, plus an arm that a person on a `review` row is still 403. Gov's seal is untouched.

## What I need from you

Rule one of:
- **(a) Keep the split above.** A person may re-file from state; only re-extraction is pin-driven.
- **(b) Item 4 wins.** Q2c's retry becomes service-only. Gov's Q2c arm 4 then changes to a service
  caller, which is gov's seal and gov's change. #43's "before any lookup" seal goes back in.
- **(c) Something else.**

Until you rule, 187 carries (a).

## Not checked

- Whether cortex exposes a retry button to the dropper today. I did not read cortex for this.
- Whether any service caller of `/retry` exists. #43's body says nothing calls it; I did not re-grep
  after #32.
