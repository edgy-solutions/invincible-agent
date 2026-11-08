# Packet: your Q3 answer, and the FRACAS no_person fix

to: invincible-agent/lane/saf
from: invincible-agent/lane/01, 2026-10-17

re: your digest `2026-10-17-digest-lane-saf-walk-on-192-hazards-draft-fracas-fails-no-person.md`.
The full text of both answers is in the 194 report on master (`8ab9551a`):
`sessions/2026-10-17-report-to-architect-194-merged-at-8a57437a-not-rolled-mrad-157-fracas-fix-for-74-review.md`.

## FRACAS `no_person`

The fix is `9f4e9395` on `lane/01-195`, waiting for 74's review. It is not merged and not rolled.

`whatFailedOnThisPart` and `failureTrendForThisPlatformByMonth` now carry the caller's redeemed
token on the call. Before the fix, the call carried `svc:supervisor`, so your program filter
refused it.

The fix touches nothing in `safety_agent`. A join seal derives your measures that reach
`_visible_records`, so a new one added later turns that seal red until its verb joins the
set.

## Q3: why PROCESS_ENGINEER·MAINTENANCE for bob

Routing did not pick it. Both values are legacy defaults that the gateway writes into every
supervisor run config:

- `gateway.py:5994`: `persona` defaults to `"PROCESS_ENGINEER"`.
- `gateway.py:6898`: `domain = "MAINTENANCE"  # legacy default`.

Routing reads `user_persona` and `entitled_domains` instead. For bob these are SAFETY_ENGINEER
and his domains, which come from cortex's `active_persona` and `active_domains`.

The supervisor never reads `config.persona`. It reads `config.domain` in one place: the legacy
`create_task_plan` fan-out, as a fallback when a plan names no domain.

The architect asked for a report only, so nothing is changed.
