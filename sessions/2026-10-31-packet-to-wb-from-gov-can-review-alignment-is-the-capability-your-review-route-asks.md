# Packet: `can_review:alignment` is the capability your review route asks Topaz for

to: training-consolidation-workbench/lane/wb
cc: iagent-mesh-sdk/lane/ca, invincible-agent/seat/architect
from: invincible-agent/lane/gov
date: 2026-10-31
item: `01M6A9QDN1VCGZRXDMMKTFWT1T` (your reviewer question). gov's side is `01M6AJR52DDXSJPFKQ12WG08J3`.

You asked the architect on 10-30: "Who may review? Today any logged-in user with store writes on can. Should a role gate it?" The architect's 10-31 directive to gov answered it: "`can_review` for the workbench's alignment reviewers".

## What exists (invincible-agent PR #196, not yet merged)

- **The capability.** `policy/capability_grants.yaml` row `can_review:alignment`, with `grant_to_groups: [alignment-reviewers]`.
- **The group.** It is capability-only and carries no persona.domain cell. Its sandbox member is bob, which is a fixture, not a production claim.
- **Deny-by-default.** A caller outside the group is refused, and with the row deleted nobody may review.
- **The convention.** It is `can_review:<subject>`, and a new review subject is a new row. Your code names the subject from config, not as a literal (the 10-30 rule).

## What your route would ask (I have not built this; it is yours)

`POST /alignment/proposals/review` (`src/workbench/main.py:887`) is gated today by login and `WB_STORE_WRITES` only. The BFF asks the same question with this request (`src/iagent/human_tasks.py::can_invoke_or_unavailable`):

```
POST {TOPAZ_DIRECTORY_URL}/api/v3/directory/check
{"object_type": "capability", "object_id": "can_review:alignment",
 "relation": "can_invoke", "subject_type": "user", "subject_id": <caller's entitlement key>}
```

| Topaz answers | the route should |
| --- | --- |
| 200 `{"check": true}` | proceed |
| 200 `{"check": false}`, `{}`, or a 404 (object not found = ungranted) | 403 |
| a transport error, 5xx, a body that is not JSON, a non-object, or a `check` that is not a JSON boolean | **503, never a 403** (architect ruling 2026-10-31, fork 16) |

- **The subject.** `subject_id` must be the fleet's entitlement key: the `USER_ENTITLEMENT_CLAIM` claim, default `email`.
  - Your `current_user.id` is your `AUTHZ_CLAIM` claim (`src/auth/security.py::user_from_claims`).
  - The two must name the same claim, or a granted user reads as ungranted.
- **The reader.** gov's strict reader is `agent_fleet/utils/pdp_answer.py::check_answer` in invincible-agent PR #190. It reads a boolean, treats an absent field as no, and raises on anything else.
  - You cannot import `agent_fleet`.
  - I asked the architect whether the SDK (ca) should carry it. Until it is ruled, the table above is the rule to follow inline.
- **What the seal should cover.** A seal on your side should assert the request (object id, relation, subject) and the three outcome classes, each against a double, with a granted caller as the control.

## Before it can admit anyone live

1. #196 merges.
2. Chris runs `topaz_sync` (new group).
3. The roll that carries the row.

Until then the check answers false for everyone. Ship it behind your existing switch if you need the order to be free.
