# BOARD — invincible-agent

**Generated — do not hand-edit.** Status lives in each item's packet header;
`scripts/generate_board.py` re-indexes them and a drift test asserts this file matches.
Hand-editing here is a lie the next regeneration silently reverts.

_Coverage: **6 of 55 packets indexed** — 2 carry pre-ADR-0040 legacy frontmatter, 47 are unheadered. Closing that gap is the migration._

## blocked-on-human

- **transport-flip** — REQUIRE_TRANSPORT_AUTH. Throwaway REQUIRE witness passed; probe exemption live; sandbox rehearsal complete. Genuinely downstream of the work deploy.
  status: blocked-on-human · owner: human · blocked-on: work-deploy validated + witnessed zero at work
  → [docs/plans/enable-agentic-auth-flip-packet.md](plans/enable-agentic-auth-flip-packet.md)

- **undeclared-routes** — 12 routes undeclared in the gating manifest, incl. decision-plane writes.
  status: blocked-on-human · owner: human · blocked-on: gate-class judgment per route
  → [docs/plans/endpoint-gating-undeclared-routes-recommendation.md](plans/endpoint-gating-undeclared-routes-recommendation.md)

## open

- **suite-signal** — master is not green. Measured census; recommended owner the telemetry agent.
  status: open · owner: agent
  → [docs/plans/suite-signal-session.md](plans/suite-signal-session.md)

## parked

- **engine-a-loop-idempotency** — Non-idempotent Superset write inside the agent loop. FILED NOT FIXED; the packet forbids attaching it to a durability session.
  status: parked · owner: human · blocked-on: design window (reserved)
  → [docs/plans/agent-loop-effect-idempotency-engine-a.md](plans/agent-loop-effect-idempotency-engine-a.md)

## closed

- **registration-wiring** — Six engines mint on /v1/register under decode-witnessed identities. Witnessed at a clean log boundary: 0 new unverified, 6 verified (svc:engine-o 1, svc:engine-w 5 — multiplicities matching each engine's verb count).
  status: closed · owner: agent · closed-by: 9d93146
  → [docs/plans/register-caller-enumeration.md](plans/register-caller-enumeration.md)

- **transport-gauge** — Gauge reads only migratable callers: probe paths exempt, 549 -> 22 -> 0-new-unverified.
  status: closed · owner: agent · closed-by: e18b5cf
  → [docs/plans/transport-auth-gauge-day-zero.md](plans/transport-auth-gauge-day-zero.md)
