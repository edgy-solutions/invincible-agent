# BOARD — invincible-agent

**Generated — do not hand-edit.** Status lives in each item's packet header;
`scripts/generate_board.py` re-indexes them and a drift test asserts this file matches.
Hand-editing here is a lie the next regeneration silently reverts.

_Coverage: **19 of 66 packets indexed** — 2 carry pre-ADR-0040 legacy frontmatter, 45 are unheadered. Closing that gap is the migration._

## blocked-on-human

- **agentic-auth-flip** — ENABLE_AGENTIC_AUTH — the CONTENT-authz flip. Turns three Topaz asks on at once and deletes the fallbacks. Downstream of the transport flip.
  status: blocked-on-human · owner: human · blocked-on: transport-flip (REQUIRE_TRANSPORT_AUTH must land first — see ordering below)
  → [docs/plans/agentic-auth-flip.md](plans/agentic-auth-flip.md)

- **transport-flip** — REQUIRE_TRANSPORT_AUTH. Throwaway REQUIRE witness passed; probe exemption live; sandbox rehearsal complete. Genuinely downstream of the work deploy.
  status: blocked-on-human · owner: human · blocked-on: unminted-caller enumeration (static) — review_composer calls /resolve_instance with no credential
  → [docs/plans/enable-agentic-auth-flip-packet.md](plans/enable-agentic-auth-flip-packet.md)

- **undeclared-routes** — 12 routes undeclared in the gating manifest, incl. decision-plane writes.
  status: blocked-on-human · owner: human · blocked-on: gate-class judgment per route
  → [docs/plans/endpoint-gating-undeclared-routes-recommendation.md](plans/endpoint-gating-undeclared-routes-recommendation.md)

- **work-deploy** — Deploy to the work cluster in OBSERVE, behind three reads. Not gated on further build work.
  status: blocked-on-human · owner: human · blocked-on: your go — nothing technical
  → [docs/plans/work-deploy.md](plans/work-deploy.md)

## open

- **adr0039-deliverables** — ADR-0039's three artifacts — schema generated from the executor models, authoring scaffold, BPMN exporter.
  status: open · owner: unassigned
  → [docs/plans/adr0039-deliverables.md](plans/adr0039-deliverables.md)

- **board-migration** — Retrofit ADR-0040 headers onto the unheadered packets; the board's first tracked item is its own completion.
  status: open · owner: unassigned
  → [docs/plans/board-migration.md](plans/board-migration.md)

- **dagster-loader-call** — build_dynamic_jobs() runs unconditionally on every Dagster load; whether its catalog is empty is unconfirmed.
  status: open · owner: unassigned · blocked-on: an owner for the Dagster plane
  → [docs/plans/dagster-loader-call.md](plans/dagster-loader-call.md)

- **doctools-ci-silent-on-push** — Pushes to doc-tools main produce ZERO CI runs — commits land unbuilt while reading as shipped. Use `gh workflow run`; verify the IMAGE, never the commit.
  status: open · owner: unassigned
  → [docs/plans/doctools-ci-silent-on-push.md](plans/doctools-ci-silent-on-push.md)

- **endpoint-table-generation** — Generate the README endpoint table from the live route census instead of asserting it.
  status: open · owner: agent
  → [docs/plans/endpoint-table-generation.md](plans/endpoint-table-generation.md)

- **retire-inline-task-loop** — BPMNWorkflowRunner still accepts a CLIENT-SUPPLIED definition via request["definition"]. ADR-0029 made its retirement conditional on the definition path sealing — which happened this week, so the condition is now met and nobody noticed.
  status: open · owner: unassigned
  → [docs/plans/retire-inline-task-loop.md](plans/retire-inline-task-loop.md)

- **subject-resolution-at-composition** — A resolvable MPN composes as subject_unresolved. Two hypotheses eliminated 2026-08-10; one survives (frozen-at-composition) with a named discriminating read.
  status: open · owner: unassigned
  → [docs/plans/open-subject-resolution-at-composition.md](plans/open-subject-resolution-at-composition.md)

- **suite-signal** — master is not green. Measured census; recommended owner the telemetry agent.
  status: open · owner: agent
  → [docs/plans/suite-signal-session.md](plans/suite-signal-session.md)

- **unminted-caller-enumeration** — Static read of every outbound call in the fleet, classified exempt / minted / unminted. The flip's real precondition.
  status: open · owner: agent
  → [docs/plans/unminted-caller-enumeration.md](plans/unminted-caller-enumeration.md)

## parked

- **engine-a-loop-idempotency** — Non-idempotent Superset write inside the agent loop. FILED NOT FIXED; the packet forbids attaching it to a durability session.
  status: parked · owner: human · blocked-on: design window (reserved)
  → [docs/plans/agent-loop-effect-idempotency-engine-a.md](plans/agent-loop-effect-idempotency-engine-a.md)

- **silence-closure-arc** — Inventory of failure modes presenting as silence rather than error; instances checked against the repo.
  status: parked · owner: agent · blocked-on: inventory review
  → [docs/plans/silence-closure-arc.md](plans/silence-closure-arc.md)

- **watch-dashboard** — Live canvas cards — refresh-on-demand, then materialization, then streaming. Design note, unbuilt.
  status: parked · owner: human · blocked-on: enforcement locks (near complete)
  → [docs/plans/watch-dashboard.md](plans/watch-dashboard.md)

## closed

- **ceremony-record** — ADR-0034 ceremony, end to end — identity-vs-pointer repair, cursor wedge, at-least-once intake, escalation, and the completion witness (dr-08a9c7e7a8c04e00, the corpus's first monitored row).
  status: closed · owner: agent · closed-by: 96f2657
  → [docs/plans/2026-08-06-artifact-uri-repair-witness.md](plans/2026-08-06-artifact-uri-repair-witness.md)

- **registration-wiring** — Six engines mint on /v1/register under decode-witnessed identities. Witnessed at a clean log boundary: 0 new unverified, 6 verified (svc:engine-o 1, svc:engine-w 5 — multiplicities matching each engine's verb count).
  status: closed · owner: agent · closed-by: 9d93146
  → [docs/plans/register-caller-enumeration.md](plans/register-caller-enumeration.md)

- **transport-gauge** — Gauge reads only migratable callers: probe paths exempt, 549 -> 22 -> 0-new-unverified.
  status: closed · owner: agent · closed-by: e18b5cf
  → [docs/plans/transport-auth-gauge-day-zero.md](plans/transport-auth-gauge-day-zero.md)
