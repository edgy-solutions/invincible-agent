# BOARD — invincible-agent

**Generated — do not hand-edit.** Status lives in each item's packet header;
`scripts/generate_board.py` re-indexes them and a drift test asserts this file matches.
Hand-editing here is a lie the next regeneration silently reverts.

_Coverage: **25 of 73 packets indexed** — 2 carry pre-ADR-0040 legacy frontmatter, 46 are unheadered. Closing that gap is the migration._

## open

- **adr0039-deliverables** — ADR-0039's three artifacts — schema generated from the executor models, authoring scaffold, BPMN exporter.
  status: open · owner: unassigned
  → [docs/plans/adr0039-deliverables.md](plans/adr0039-deliverables.md)

- **agentic-auth-flip** — ENABLE_AGENTIC_AUTH — the CONTENT-authz flip. Turns three Topaz asks on at once and deletes the fallbacks. Downstream of the transport flip.
  status: open · owner: agent · blocked-on: transport-flip, which is itself open/agent (2 decodes + 2 sweeps). Nothing is awaited from the human until that lands; the flip act is then theirs.
  → [docs/plans/agentic-auth-flip.md](plans/agentic-auth-flip.md)

- **board-migration** — Retrofit ADR-0040 headers onto the unheadered packets; the board's first tracked item is its own completion.
  status: open · owner: unassigned
  → [docs/plans/board-migration.md](plans/board-migration.md)

- **dag-tools-broker-register-unauthenticated** — Unauthenticated routing-table write — /api/v1/internal/register takes broker_url from the body and repoints any URN. Integrity write, so NOT acceptable on in-cluster reachability alone. First cross-repo instance of the undeclared-routes pattern.
  status: open · owner: agent · blocked-on: nothing — CLASSIFIED. [[gate-class-follows-the-effect]] puts an integrity write in the never-acceptable-on-in-cluster-reachability column. Remaining work is the build: authenticate /api/v1/internal/register and /resolve.
  → [docs/plans/dag-tools-broker-register-unauthenticated.md](plans/dag-tools-broker-register-unauthenticated.md)

- **dag-tools-gateway-unverified-subject** — HIGH — the DA data gateway never verifies a bearer and takes its authz subject from a request HEADER, so per-user scoping is advisory. THE DELIVERABLE IS THE SUBJECT-SOURCE GAUGE — how many live requests ASSERT a subject vs PROVE one. Verification is the easy part; the gauge decides whether killing the header override is a config change or a coordinated migration.
  status: open · owner: agent · blocked-on: THE READING — the OBSERVE gauge is built and wired (2026-08-11); it must run on the live gateway and be counted before step 2 is scoped. Verification/header-override work waits on that number.
  → [docs/plans/dag-tools-gateway-unverified-subject.md](plans/dag-tools-gateway-unverified-subject.md)

- **dagster-loader-call** — build_dynamic_jobs() runs unconditionally on every Dagster load; whether its catalog is empty is unconfirmed.
  status: open · owner: unassigned · blocked-on: an owner for the Dagster plane
  → [docs/plans/dagster-loader-call.md](plans/dagster-loader-call.md)

- **doctools-ci-silent-on-push** — Pushes to doc-tools main produce ZERO CI runs — commits land unbuilt while reading as shipped. Use `gh workflow run`; verify the IMAGE, never the commit.
  status: open · owner: unassigned
  → [docs/plans/doctools-ci-silent-on-push.md](plans/doctools-ci-silent-on-push.md)

- **endpoint-table-generation** — Generate the README endpoint table from the live route census instead of asserting it.
  status: open · owner: agent
  → [docs/plans/endpoint-table-generation.md](plans/endpoint-table-generation.md)

- **jupyter-user-token-data-access** — Design + configuration for transparent per-user data access from notebooks — JupyterHub OIDC token reaching CortexDataClient. Blocked: without bearer verification the design LOOKS per-user and is not.
  status: open · owner: human · blocked-on: gateway must verify bearers first — dag-tools-gateway-unverified-subject
  → [docs/plans/jupyter-user-token-data-access.md](plans/jupyter-user-token-data-access.md)

- **legacy-dns-guard-phantom-scope** — DISPROVED guard — `SCANNED_DIRS` lists "doc-tools", which is a SIBLING REPO not a subdirectory, so the walker skips it silently and passes green while the forbidden pattern is live in the unscanned tree.
  status: open · owner: unassigned
  → [docs/plans/legacy-dns-guard-phantom-scope.md](plans/legacy-dns-guard-phantom-scope.md)

- **retire-inline-task-loop** — CLEANUP-GRADE (security read done 2026-08-10, outcome: not a fix). BPMNWorkflowRunner accepts a client-supplied definition, but WorkflowStartRequest drops the field and the ingress is ClusterIP — in-cluster only. ADR-0029's retirement condition is met; residual in-cluster risk folded into undeclared-routes.
  status: open · owner: unassigned
  → [docs/plans/retire-inline-task-loop.md](plans/retire-inline-task-loop.md)

- **subject-resolution-at-composition** — A resolvable MPN composes as subject_unresolved. Two hypotheses eliminated 2026-08-10; one survives (frozen-at-composition) with a named discriminating read.
  status: open · owner: unassigned
  → [docs/plans/open-subject-resolution-at-composition.md](plans/open-subject-resolution-at-composition.md)

- **suite-signal** — master is not green. Measured census; recommended owner the telemetry agent.
  status: open · owner: agent
  → [docs/plans/suite-signal-session.md](plans/suite-signal-session.md)

- **transport-flip** — REQUIRE_TRANSPORT_AUTH. Throwaway REQUIRE witness passed; probe exemption live; sandbox rehearsal complete. Genuinely downstream of the work deploy.
  status: open · owner: agent · blocked-on: the 11 are remediated but UNWITNESSED — 2 decode-witnesses outstanding (svc:engine-a, svc:review-starter). Cross-repo enumeration COMPLETE 2026-08-11 (5/5; cortex-ui = structural zero, no server-side origin); ONE CONFIRMED unminted caller stands — doc-tools semantic_linker.py:99 -> engine-o (corrected 2026-08-12 from 2; dag-tools contributes ZERO, see the count correction in the packet). Returns to blocked-on-human when those land; the flip act is the human's.
  → [docs/plans/enable-agentic-auth-flip-packet.md](plans/enable-agentic-auth-flip-packet.md)

- **undeclared-routes** — RULED 2026-08-10 — the four dispositions are given and promoted to the standing rule [[gate-class-follows-the-effect]]. Three dependents unblocked. Residual: /workflow/start is verify-then-disable, and 2 of 5 repos are still unswept.
  status: open · owner: agent · blocked-on: nothing — all four dispositions given, and /workflow/start is EXECUTED (retired 410, 2026-08-11). Residual is build work: write the 12 manifest rows per [[gate-class-follows-the-effect]], which is what the 3 red test_every_source_route_is_declared cases are.
  → [docs/plans/endpoint-gating-undeclared-routes-recommendation.md](plans/endpoint-gating-undeclared-routes-recommendation.md)

## parked

- **engine-a-loop-idempotency** — Non-idempotent Superset write inside the agent loop. FILED NOT FIXED; the packet forbids attaching it to a durability session.
  status: parked · owner: human · blocked-on: design window (reserved)
  → [docs/plans/agent-loop-effect-idempotency-engine-a.md](plans/agent-loop-effect-idempotency-engine-a.md)

- **engine-o-internal-hardening** — Engine-o's internal read/orchestration routes are accepted at current posture. Fires when in-cluster reachability stops being an acceptable gate.
  status: parked · owner: unassigned · trigger: the cluster stops being closed — a SHARED work cluster, any workload you did not author, or a network-policy change
  → [docs/plans/engine-o-internal-hardening.md](plans/engine-o-internal-hardening.md)

- **silence-closure-arc** — Inventory of failure modes presenting as silence rather than error; instances checked against the repo.
  status: parked · owner: agent · blocked-on: inventory review
  → [docs/plans/silence-closure-arc.md](plans/silence-closure-arc.md)

- **watch-dashboard** — Live canvas cards — refresh-on-demand, then materialization, then streaming. Design note, unbuilt.
  status: parked · owner: human · blocked-on: enforcement locks (near complete)
  → [docs/plans/watch-dashboard.md](plans/watch-dashboard.md)

## closed

- **approval-bypass-bpmn-runner** — HIGH — RESOLVED d3ef8bf. The approval plane resolved promises with no caller identity. Gated on THREE surfaces, not the two declared: engine-a's route, the Restate approve handler, and GroupedReview.submit_decision (found while fixing the other two). Audience read from the workflow journal, never the request.
  status: closed · owner: unassigned · closed-by: d3ef8bf
  → [docs/plans/approval-bypass-bpmn-runner.md](plans/approval-bypass-bpmn-runner.md)

- **ceremony-record** — ADR-0034 ceremony, end to end — identity-vs-pointer repair, cursor wedge, at-least-once intake, escalation, and the completion witness (dr-08a9c7e7a8c04e00, the corpus's first monitored row).
  status: closed · owner: agent · closed-by: 96f2657
  → [docs/plans/2026-08-06-artifact-uri-repair-witness.md](plans/2026-08-06-artifact-uri-repair-witness.md)

- **cortex-ui-transport-idiom** — DESIGN READ (2026-08-11) for repo 5 of 5. cortex-ui is a static SPA behind nginx — there is NO server-side origin, so the "unminted caller" frame does not apply and the sweep population is browser call sites only. One confirmed defect: NodeInspector sends no token AND bypasses runtime config, two defects on one line where the outer masks the inner.
  status: closed · owner: unassigned · closed-by: d1184b3
  → [docs/plans/cortex-ui-transport-idiom.md](plans/cortex-ui-transport-idiom.md)

- **registration-wiring** — Six engines mint on /v1/register under decode-witnessed identities. Witnessed at a clean log boundary: 0 new unverified, 6 verified (svc:engine-o 1, svc:engine-w 5 — multiplicities matching each engine's verb count).
  status: closed · owner: agent · closed-by: 9d93146
  → [docs/plans/register-caller-enumeration.md](plans/register-caller-enumeration.md)

- **transport-gauge** — Gauge reads only migratable callers: probe paths exempt, 549 -> 22 -> 0-new-unverified.
  status: closed · owner: agent · closed-by: e18b5cf
  → [docs/plans/transport-auth-gauge-day-zero.md](plans/transport-auth-gauge-day-zero.md)

- **work-deploy** — DEPLOYED in OBSERVE. The go was given and the three reads are settled — 1 done, 2 retracted as the wrong tool for this cluster, 3 decode-verified green. Residual fifth read (which identity a notebook session carries) is not a blocker and lives with jupyter-user-token-data-access.
  status: closed · owner: human · closed-by: ecdd944
  → [docs/plans/work-deploy.md](plans/work-deploy.md)
