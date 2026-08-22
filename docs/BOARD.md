# BOARD — invincible-agent

**Generated — do not hand-edit.** Status lives in each item's packet header;
`scripts/generate_board.py` re-indexes them and a drift test asserts this file matches.
Hand-editing here is a lie the next regeneration silently reverts.

_Coverage: **62 of 64 packets indexed** — 2 carry pre-ADR-0040 legacy frontmatter, 0 are unheadered. Closing that gap is the migration._

## blocked-on-human

- **urn-reconciliation-guard** — Nothing checks that a URN a broker registers corresponds to a real DataHub entity. Every identity defect this week — platform, endpoint, bucket — produced the same silent 404, and this one check would have caught all three at startup instead of at a demo.
  status: blocked-on-human · owner: human · repo: dag-tools · blocked-on: a POSTURE ruling — fail broker startup on a URN that does not resolve in DataHub, or warn and serve. Fail-closed is the honest reading and also means a DataHub outage stops every broker. That trade is the human's to make.
  → [docs/plans/urn-reconciliation-guard.md](plans/urn-reconciliation-guard.md)

## open

- **adr0039-deliverables** — ADR-0039's three artifacts — schema generated from the executor models, authoring scaffold, BPMN exporter.
  status: open · owner: unassigned
  → [docs/plans/adr0039-deliverables.md](plans/adr0039-deliverables.md)

- **agent-loop-infra-error-flail** — A hard infrastructure error (ConnectError, 404) is handed to the code agent as an ordinary tool failure, so it burns steps re-attempting and narrating around something no amount of reasoning can fix — then reports `outcome=ok` for having produced an apology.
  status: open · owner: unassigned · blocked-on: nothing
  → [docs/plans/agent-loop-infra-error-flail.md](plans/agent-loop-infra-error-flail.md)

- **agentic-auth-flip** — ENABLE_AGENTIC_AUTH — the CONTENT-authz flip. Turns three Topaz asks on at once and deletes the fallbacks. Downstream of the transport flip.
  status: open · owner: agent · blocked-on: transport-flip, which is itself open/agent (2 decodes + 2 sweeps). Nothing is awaited from the human until that lands; the flip act is then theirs.
  → [docs/plans/agentic-auth-flip.md](plans/agentic-auth-flip.md)

- **answer-latency-tier1** — DECOMPOSED 2026-08-19 (n=5 + isolated hop probes). Tier-1 answer is 262.0s +/- 10.6 (the filed 324.9s was a ~6-sigma outlier, likely a cold 64.7GB model load). >99% is sequential LLM generation; ALL data/graph work totals 2.3s. Root cause: a 116.8B REASONING model at ~33 tok/s where 95-97% of generated tokens are hidden reasoning, called ~sequentially. Largest phase is composing (102.5s), which the original filing never named.
  status: open · owner: unassigned
  → [docs/plans/answer-latency-tier1.md](plans/answer-latency-tier1.md)

- **bff-liveness-probe-kills-under-load** — ⚠️ DEMO RISK, classified 2026-08-22, SCOPE CORRECTED the same day: this is CHART-WIDE, not one service. 16 of 27 deployments carry `timeoutSeconds: 1` on LIVENESS — every engine, the BFF, the registrar, the projector. Most engines pair it with `readiness: 10`, so someone already judged 1s too tight for readiness and did not carry that to the check that KILLS — the inversion is the finding. Two observed failing so far (BFF SIGKILLed exit 137; Engine DA flapping); the other fourteen have not been under load yet. cortex-bff was SIGKILLed (exit 137) under ordinary traffic — not OOM, a LIVENESS PROBE KILL. The probe allows `/health` `timeoutSeconds: 1` with `failureThreshold: 3`; kubelet recorded "Liveness probe failed x4 over 105m" and "Readiness probe failed x6" with `context deadline exceeded`. A single-threaded FastAPI event loop busy with an Electric shape proxy or a graph query cannot always answer within one second, so the BFF is killed for being busy. In a demo this is every answer failing at once with nothing in the log to point at — the container dies without writing a reason.
  status: open · owner: unassigned
  → [docs/plans/bff-liveness-probe-kills-under-load.md](plans/bff-liveness-probe-kills-under-load.md)

- **board-migration** — Retrofit ADR-0040 headers onto the unheadered packets; the board's first tracked item is its own completion.
  status: open · owner: unassigned
  → [docs/plans/board-migration.md](plans/board-migration.md)

- **broker-endpoint-env-divergence** — A domain broker re-loads the code location's Definitions in its OWN pod, so every env var that shapes an asset key must match between the two — and three did not, each producing an identical-looking 404. The asset key is assembled from env nobody owns, and identity silently follows any of it.
  status: open · owner: human · blocked-on: the source of the stuck PUBLOG_S3_BUCKET_URL is unfound — absent from `helm template`, absent from the image, present in the live Deployment. Removed by hand to unblock; will recur if a values layer still supplies it.
  → [docs/plans/broker-endpoint-env-divergence.md](plans/broker-endpoint-env-divergence.md)

- **capability-registry-not-graph-backed** — ⚠️ LIVE DEFECT, found by the 2026-08-21 redeploy. The frontend capability registry is a MODULE-LOCAL DICT, and registration and selection run in DIFFERENT PODS — `/register_frontend_capabilities` is served by cortex-bff, `/render_ui` by presentation-agent. Registration can therefore NEVER reach the selector: every caller is anonymous from engine-f's view, the union is always empty, and every answer falls to the labelled floor. CHART_WIDGET is currently unselectable in production for anyone. ADR-0017's own mechanism (rendersAs triples in the shared Predicate collection, read via /search_predicates) was always the design; the in-memory dict was scaffolding that was never written down as a divergence.
  status: open · owner: agent
  → [docs/plans/capability-registry-not-graph-backed.md](plans/capability-registry-not-graph-backed.md)

- **cortex-ui-no-test-runner** — cortex-ui has NO test runner at all — no vitest, no jest, no `test` script, zero test files. Found 2026-08-20 while building the presentation contract slice. This is why ten hand-copied capability contracts could drift with nothing pinning them: the drift was not missed, it was UNOBSERVABLE. Sibling of no-ci-gate-on-the-suite, one repo over.
  status: open · owner: unassigned · repo: cortex-ui
  → [docs/plans/cortex-ui-no-test-runner.md](plans/cortex-ui-no-test-runner.md)

- **da-collects-before-filtering** — `SELECT ... LIMIT 2` reads the ENTIRE table into RAM. `get_dataframe` returns a LazyFrame so scans can push down projections and limits, and `.collect()` discards that one line later — so memory is a function of the DATASET, never of the query. OOM-killed Engine DA at work 2026-08-14 on a two-row read.
  status: open · owner: agent · blocked-on: nothing — the defect is two lines and the repair is a design choice about WHERE the query executes.
  → [docs/plans/da-collects-before-filtering.md](plans/da-collects-before-filtering.md)

- **da-schema-affordance** — Engine DA is handed a URN and no schema, so it guesses column names and learns them from BinderException text; and `query_datahub_asset` returns a JSON STRING, so the agent then discovers it cannot index it. 3 of 6 steps on a successful two-row read were spent on both.
  status: open · owner: unassigned · blocked-on: nothing — both halves are small and independently shippable.
  → [docs/plans/da-schema-affordance.md](plans/da-schema-affordance.md)

- **dag-tools-broker-register-unauthenticated** — Unauthenticated routing-table write — /api/v1/internal/register takes broker_url from the body and repoints any URN. Integrity write, so NOT acceptable on in-cluster reachability alone. First cross-repo instance of the undeclared-routes pattern.
  status: open · owner: agent · repo: dag-tools · blocked-on: nothing — CLASSIFIED. [[gate-class-follows-the-effect]] puts an integrity write in the never-acceptable-on-in-cluster-reachability column. Remaining work is the build: authenticate /api/v1/internal/register and /resolve.
  → [docs/plans/dag-tools-broker-register-unauthenticated.md](plans/dag-tools-broker-register-unauthenticated.md)

- **dag-tools-gateway-unverified-subject** — HIGH — the DA data gateway never verifies a bearer and takes its authz subject from a request HEADER, so per-user scoping is advisory. THE DELIVERABLE IS THE SUBJECT-SOURCE GAUGE — how many live requests ASSERT a subject vs PROVE one. Verification is the easy part; the gauge decides whether killing the header override is a config change or a coordinated migration.
  status: open · owner: agent · repo: dag-tools · blocked-on: THE READING — the OBSERVE gauge is built and wired (2026-08-11); it must run on the live gateway and be counted before step 2 is scoped. Verification/header-override work waits on that number.
  → [docs/plans/dag-tools-gateway-unverified-subject.md](plans/dag-tools-gateway-unverified-subject.md)

- **dagster-loader-call** — build_dynamic_jobs() runs unconditionally on every Dagster load; whether its catalog is empty is unconfirmed.
  status: open · owner: unassigned · blocked-on: an owner for the Dagster plane
  → [docs/plans/dagster-loader-call.md](plans/dagster-loader-call.md)

- **deterministic-decisions-made-by-llm** — ARCHITECTURAL — the parts of routing that should be mechanical are model judgments. Subject selection is an LLM picking from scored candidates (it chose a 0.477 candidate over a 1.0 one); archetype selection is made from output_uri before anyone looks at the rows. Not three bugs — one gap with three symptoms, and the reason the system feels non-deterministic.
  status: open · owner: human · blocked-on: a design session. The READ is done and the answer is known — subject selection IS a BAML call over scored candidates. What is owed is the ruling on which decisions become rules, and that is the ADR's SPO determinism work.
  → [docs/plans/deterministic-decisions-made-by-llm.md](plans/deterministic-decisions-made-by-llm.md)

- **doctools-ci-silent-on-push** — Pushes to doc-tools main produce ZERO CI runs — commits land unbuilt while reading as shipped. Use `gh workflow run`; verify the IMAGE, never the commit.
  status: open · owner: unassigned · repo: doc-tools
  → [docs/plans/doctools-ci-silent-on-push.md](plans/doctools-ci-silent-on-push.md)

- **endpoint-table-generation** — Generate the README endpoint table from the live route census instead of asserting it.
  status: open · owner: agent
  → [docs/plans/endpoint-table-generation.md](plans/endpoint-table-generation.md)

- **engine-da-ooms-on-a-plausible-question** — ⚠️ DEMO BLOCKER, diagnosed 2026-08-22. Engine DA is OOMKilled (exit 137, `Reason: OOMKilled`, 2Gi limit) executing an ordinary analytical question — `SELECT company, ARRAY_AGG(DISTINCT cage_code) FROM dataset GROUP BY company` over a publog table. It crashed MID-STEP on a real user question and the pod has been in CrashLoopBackOff; the previous pod restarted 15 times in 173 minutes. THE FAILURE IS SILENT FROM THE UI: routing succeeds and reports high confidence, the answer card renders with its title, and the body is empty with "No citations yet" — because the engine died before returning anything. An error would be better; this looks like an answer.
  status: open · owner: unassigned
  → [docs/plans/engine-da-ooms-on-a-plausible-question.md](plans/engine-da-ooms-on-a-plausible-question.md)

- **first-viewer-critical-path** — TRIAGE — FOUR load-bearing now (a prerequisite the triage missed was found by item 1's live witness: no asset is both granted and fetchable, so the data path serves nothing — inserted ahead of da-collects). Of 27 live board items, originally THREE were load-bearing for "one other person can use this", in a stated order. The other 24 sort into demo-day operational risk (3, now a runbook not board work) and hygiene/posture/architecture (21). The goal is three items away, not thirty-nine, and this packet names which and why the other 24 are not.
  status: open · owner: human · blocked-on: nothing — the scope sentence is ANSWERED (2026-08-15): Tier-3 row 8 IS in scope, so the path is three items in the order stated below. What remains is building them.
  → [docs/plans/first-viewer-critical-path.md](plans/first-viewer-critical-path.md)

- **instance-resolution-nondeterminism** — RETRACTED 2026-08-17 — the 'no nondeterminism' headline was WITHIN-RUN only. The same query gives opposite answers BETWEEN runs on an unchanged pod, because a 0.006 shift in one candidate score flips both the class and the extracted identifier (temperature-0 is deterministic per PROMPT, and the prompt carries the candidates). MEASURED 2026-08-15, 290 probes, 0 errors, 0 of 29 phrasings mixed WITHIN that run and the trailing-class-noun lead is refuted (bare 67% = trailing 67%). The real defect is the SHAPE of the extracted identifier: the matcher rejects qualified names it owns (`publog.p_cage`, `publog p_cage`) and accepts content words it does not (`cage` -> `p_cage`, so a nonexistent asset returns a confident answer about a real one). Too strict and too loose, same missing idea. Title retained as an id only; see the body.
  status: open · owner: agent · blocked-on: nothing — the read is DONE but its HEADLINE IS RETRACTED (within-run only; see the 2026-08-17 correction). ANNOUNCEMENT TO AGENT B, per the shared-surface rule in AGENTS.md: the fix's extraction half will change `ClassifyDomainIntent`'s prompt — the one call that emits BOTH class and identifier — so hold any in-flight class-selection read before it lands. The two halves (qualifier-stripping in matching, identifier-vs-content-word discrimination in extraction) MUST land together: the strict half alone widens the aperture that already admits a content word and makes the two stable false positives MORE reachable.
  → [docs/plans/instance-resolution-nondeterminism.md](plans/instance-resolution-nondeterminism.md)

- **jupyter-user-token-data-access** — Design + configuration for transparent per-user data access from notebooks — JupyterHub OIDC token reaching CortexDataClient. Blocked: without bearer verification the design LOOKS per-user and is not.
  status: open · owner: human · repo: dag-tools · blocked-on: gateway must verify bearers first — dag-tools-gateway-unverified-subject
  → [docs/plans/jupyter-user-token-data-access.md](plans/jupyter-user-token-data-access.md)

- **legacy-dns-guard-phantom-scope** — DISPROVED guard — `SCANNED_DIRS` lists "doc-tools", which is a SIBLING REPO not a subdirectory, so the walker skips it silently and passes green while the forbidden pattern is live in the unscanned tree.
  status: open · owner: unassigned
  → [docs/plans/legacy-dns-guard-phantom-scope.md](plans/legacy-dns-guard-phantom-scope.md)

- **no-ci-gate-on-the-suite** — CI runs exactly ONE test file (tests/test_telemetry.py). The 1543-test suite has no CI gate at all — which is why nine members of the borrowed-green class accumulated undetected for months. A workflow_dispatch-only draft exists at docs/proposals/suite-order-independence.yml.draft; it has never run on a GitHub runner.
  status: open · owner: unassigned
  → [docs/plans/no-ci-gate-on-the-suite.md](plans/no-ci-gate-on-the-suite.md)

- **no-granted-and-fetchable-asset** — NO ASSET ON SANDBOX IS BOTH GRANTED AND FETCHABLE — p_cage was materialized 2026-08-15 and has no read grant; the one granted asset returns HTTP 404 on read. So the data path cannot serve ANY query, which makes item 1's success arm unwitnessable and Tier-3 row 8 impossible. Discovered by the live witness, named on no board line, and it sits AHEAD of da-collects-before-filtering.
  status: open · owner: human · blocked-on: A CHOICE BETWEEN TWO CHEAP PATHS, either of which closes it — (a) grant alice a read on `publog/p_cage` (a `policy/asset_grants.yaml` write plus sync; the live Topaz write is a human act), or (b) fix the HTTP 404 on the already-granted `mesh_demo_customers` (the queued `minio-svc` values change). (a) is minutes; (b) also retires a demo-day risk.
  → [docs/plans/no-granted-and-fetchable-asset.md](plans/no-granted-and-fetchable-asset.md)

- **pcn-extraction-sort** — The decided three-pile sort (rename-and-promote / keep-domain-specific / delete) so the M2 extraction milestone is a mechanical execution rather than a fresh analysis. Pairs with the generic-at-birth rule. DECIDED, NOT EXECUTED - verified 2026-08-19: no three-pile implementation exists, and the cited 0cc406e is the review-state tripwire, a different artifact.
  status: open · owner: unassigned
  → [docs/plans/pcn-extraction-sort.md](plans/pcn-extraction-sort.md)

- **portfolio-review-rev3-delta** — Revision 3 of the portfolio-review plan, in DELTA form — what sections B/C/D of the 2026-08-21 requirements packet ADD to what is already built, never a re-plan of section A. A is not merely planned, it is LANDED AND CITED (abf16fd, 83 tests), and re-deriving built work in a plan document is how a plan drifts from its own repo. Every B item names the existing type or verb it extends so a reader can tell extension from invention. Carries one correction back to the packet: the sandbox runs `gpt-oss-128k:120b`, so the Day-5 eval must assert the CONFIGURED model name, not the name a document remembers.
  status: open · owner: unassigned · blocked-on: architect fills C3's private-overlay path
  → [docs/plans/portfolio-review-rev3-delta.md](plans/portfolio-review-rev3-delta.md)

- **portfolio-review-workshop-tool** — Live portfolio-review workshop tool — a T+7 demo whose real job is to demonstrate the presentation-SPO arc on a second grounding. REVISION 2 (2026-08-20): rev 1 was authored against the architecture as it stood a week earlier and the presentation-SPO arc landed seven commits underneath it; as written it would have rebuilt a parallel presentation stack (client-side measures never crossing /render_ui, an intent catalog naming chart types = `archetype-chosen-before-data` re-opened one day after it closed). Ruled by ADR-0042. Binding changes: measures are VERBS running server-side from commit 1 (mock the store, never the placement); intents declare `output_uri` never a view; every widget ships a `.contract.ts`; Gate 1 asserts `presentation_source == "registered"`, not "a card appeared"; two-repo cycle (BFF routes are in-scope, a second Fastify/tRPC backend is deleted); D6 VERIFIED 2026-08-20 against the live endpoint (/api/tags): `gpt-oss-120b` is ABSENT (the documented 404), sandbox is configured for `gpt-oss-128k:120b` (131072 context) NOT plain `gpt-oss:120b`, and the declared hardware fallback `gpt-oss:20b` IS NOT PRESENT — pull it or delete the escape hatch.
  status: open · owner: unassigned
  → [docs/plans/portfolio-review-workshop-tool.md](plans/portfolio-review-workshop-tool.md)

- **presentation-contract-enumeration** — ADR-0017's capability publication carries expected_fields (NAMES) but no types or cardinality, so every consuming contract lives in a React component and the backend mirrors it by hand. Enumerated 2026-08-19 from the components' actual prop types and key handling. THREE FINDINGS OUTRANK THE ENUMERATION - presentation_agent/capabilities.py hand-duplicates the ENTIRE UI capability registry with no seal; chart_normalizer.py (194 lines) mirrors a shape ChartWidget NO LONGER REQUIRES; and the dispatch boundary is typed `any`.
  status: open · owner: agent · trigger: D4 TIGHTENING - capability_admission.KNOWN_ARCHETYPES deliberately encodes the D4 defect: it admits the UNION of BAML's SemanticArchetype and the five archetypes the interpreter dispatches without the enum declaring them (GROUPED_REVIEW, APPROVAL_TASK, TRIAGE_TASK, WORKFLOW_OBSERVATION, INSTANCES_BY_PROPERTY). Enforcing the enum would refuse archetypes the UI genuinely renders, punishing users for a backend inconsistency they did not create. WHEN THE ENUM IS REPAIRED, THE VALIDATOR'S VOCABULARY MUST TIGHTEN TO MATCH - a validator that permanently encodes a defect becomes that defect's guardian.
  → [docs/plans/presentation-contract-enumeration.md](plans/presentation-contract-enumeration.md)

- **prime-ingest-timeout-shorter-than-its-own-queue** — ⚠️ MEASURED 2026-08-22 by a real helm-driven prime. `primeSubstrate.ingestTimeout` is 1800s; the prime launches 15 ontology ingests and dagster's `max_concurrent_runs` is 2, so they SERIALISE into ~8 batches. Ten finished inside the window, five did not — `mesh_system` (which carries every archetype class) among them. The prime then REFUSED to report success, which is the 9e31ae8 fix behaving exactly as designed: `reregister` never ran and no engine restarted against a partial class graph. Substrate left undamaged at its before-numbers (29 classes / 44 rows). The timeout is not tuned to the queue it waits on, and the two numbers have never been compared.
  status: open · owner: unassigned
  → [docs/plans/prime-ingest-timeout-shorter-than-its-own-queue.md](plans/prime-ingest-timeout-shorter-than-its-own-queue.md)

- **registrar-models-presentation-triples** — THE LAST ARCHITECTURAL PIECE for rendersAs. Presentations cannot reach Weaviate by ANY automatic path today: the gateway's RegistrationManifest models only verb edges (input_uri/output_uri), so register_presentation_to_mesh bypasses it and emits direct-to-DataHub — and the DataHub→Weaviate materializer (doc-tools' aitool sensor) was RETIRED 2026-06-13 when Gateway v0.2 became sole writer. Those emissions are audit records going nowhere. Teaching the manifest the SPO triple shape makes presentations register the way everything else registers: through the sole writer, Contract-D-checked against the archetype classes, landing in the same Predicate collection the 24 verb rows already occupy.
  status: open · owner: agent
  → [docs/plans/registrar-models-presentation-triples.md](plans/registrar-models-presentation-triples.md)

- **registration-boot-order-race** — An engine that boots before the ontology ingest lands gets a 422 Contract D rejection and NEVER retries — the ruling says 422 is permanent, and it is right for a real contract violation and wrong for "the graph is not populated yet". Witnessed at work 2026-08-14; recovery was a hand restart. The registrar is the only party that can tell the two apart.
  status: open · owner: agent · blocked-on: repair 3 (the registrar discrimination) LANDED in fbf7307. Repair 1 is still owed and unanswered — WHICH of the three ways the re-register hook failed to fire at work. Until that read is done, a deploy still depends on a hook nobody has verified runs.
  → [docs/plans/registration-boot-order-race.md](plans/registration-boot-order-race.md)

- **retire-inline-task-loop** — CLEANUP-GRADE (security read done 2026-08-10, outcome: not a fix). BPMNWorkflowRunner accepts a client-supplied definition, but WorkflowStartRequest drops the field and the ingress is ClusterIP — in-cluster only. ADR-0029's retirement condition is met; residual in-cluster risk folded into undeclared-routes.
  status: open · owner: unassigned
  → [docs/plans/retire-inline-task-loop.md](plans/retire-inline-task-loop.md)

- **seeder-manufactures-declarations** — The sandbox seeder MERGEs endpoint OntologyClass nodes as a SIDE EFFECT of seeding a predicate, so it manufactures declarations no TTL contains. Sandbox is green forever and no fresh cluster can be — and nothing inside sandbox can detect the difference.
  status: open · owner: agent · blocked-on: nothing — the instance is fixed and the sweep is clean; what remains is making the mechanism unable to recur.
  → [docs/plans/seeder-manufactures-declarations.md](plans/seeder-manufactures-declarations.md)

- **stale-sandbox-images-predate-presentation-arc** — The sandbox runs pre-arc builds. `iagent-engine-f` started 2026-08-18 and `iagent-cortex-ui` started 2026-08-15; the ENTIRE presentation-SPO arc (slices 2a/2b/2c/4, the frontend_id seam, the union fallback, and every component contract) landed 2026-08-20. Probed 2026-08-21: a planning `output_uri` to `/render_ui` returns `x-presentation-path: fallback-designui` — the OLD LLM path, because the deployed code has no `select_presentation`. CONSEQUENCE: any integration check against sandbox today is testing an architecture that no longer exists in the tree, and would report green or red for reasons unrelated to the code under test. Blocks the portfolio-review plan's Gate 1, which asserts provenance the deployed engine cannot emit.
  status: open · owner: unassigned
  → [docs/plans/stale-sandbox-images-predate-presentation-arc.md](plans/stale-sandbox-images-predate-presentation-arc.md)

- **subject-resolution-at-composition** — A resolvable MPN composes as subject_unresolved. Two hypotheses eliminated 2026-08-10; one survives (frozen-at-composition) with a named discriminating read.
  status: open · owner: unassigned
  → [docs/plans/open-subject-resolution-at-composition.md](plans/open-subject-resolution-at-composition.md)

- **suite-signal** — CLAIMED by Agent B 2026-08-17. master green in-order (9 failed -> 0) AND under shuffle; class grew 3 -> 9 members; all 166 test files now pass standalone. Policy + guards landed. Open: no full-suite CI job exists to wire the shuffle into.
  status: open · owner: agent
  → [docs/plans/suite-signal-session.md](plans/suite-signal-session.md)

- **supervisor-mint-missing-identity** — Every supervisor dispatch is unauthenticated at work — `mint_supervisor_token()` raises KeyError, so specialists record `caller: none`. Inert under OBSERVE, and it becomes a hard failure the moment REQUIRE_TRANSPORT_AUTH flips.
  status: open · owner: agent · blocked-on: nothing — one read settles it: `printenv` for SUPERVISOR_CLIENT_ID and SUPERVISOR_CLIENT_SECRET in the pod that runs the supervisor. KeyError does not say which.
  → [docs/plans/supervisor-mint-missing-identity.md](plans/supervisor-mint-missing-identity.md)

- **transport-flip** — REQUIRE_TRANSPORT_AUTH. Throwaway REQUIRE witness passed; probe exemption live; sandbox rehearsal complete. Genuinely downstream of the work deploy.
  status: open · owner: agent · blocked-on: the 11 are remediated but UNWITNESSED — 2 decode-witnesses outstanding (svc:engine-a, svc:review-starter). Cross-repo enumeration COMPLETE 2026-08-11 (5/5; cortex-ui = structural zero, no server-side origin); ONE CONFIRMED unminted caller stands — doc-tools semantic_linker.py:99 -> engine-o (corrected 2026-08-12 from 2; dag-tools contributes ZERO, see the count correction in the packet). Returns to blocked-on-human when those land; the flip act is the human's.
  → [docs/plans/enable-agentic-auth-flip-packet.md](plans/enable-agentic-auth-flip-packet.md)

- **undeclared-routes** — RULED 2026-08-10 — the four dispositions are given and promoted to the standing rule [[gate-class-follows-the-effect]]. Three dependents unblocked. Residual: /workflow/start is verify-then-disable, and 2 of 5 repos are still unswept.
  status: open · owner: agent · blocked-on: nothing in this packet — the gate is wired and inert until ENABLE_AGENTIC_AUTH flips, which is [[transport-flip]]'s item, not this one. (A 2026-08-13 note claiming TOPAZ_DIRECTORY_URL was unwired was WRONG and is corrected: it is set to http://topaz-svc:9393 on both engines via iagent-config, verified in the running pods.) Everything else is done: dispositions given, /workflow/start retired (410, 2026-08-11), ALL 12 ROWS DECLARED (2026-08-12), and the two engine-o WRITE residuals CLOSED endpoint-side 2026-08-13 (can_invoke on the single decider, discriminating pair sealed, break-on-purpose verified; both rows now class: gated).
  → [docs/plans/endpoint-gating-undeclared-routes-recommendation.md](plans/endpoint-gating-undeclared-routes-recommendation.md)

## parked

- **engine-a-loop-idempotency** — Non-idempotent Superset write inside the agent loop. FILED NOT FIXED; the packet forbids attaching it to a durability session.
  status: parked · owner: human · blocked-on: design window (reserved)
  → [docs/plans/agent-loop-effect-idempotency-engine-a.md](plans/agent-loop-effect-idempotency-engine-a.md)

- **engine-o-internal-hardening** — Engine-o's internal read/orchestration routes are accepted at current posture. Fires when in-cluster reachability stops being an acceptable gate.
  status: parked · owner: unassigned · trigger: the cluster stops being closed — a SHARED work cluster, any workload you did not author, or a network-policy change
  → [docs/plans/engine-o-internal-hardening.md](plans/engine-o-internal-hardening.md)

- **section-reference-phantoms-unsealed** — PARKED, evidence-gated. `§N` references inside ADRs have no reader — ADR-0042 shipped a status-line `§9` pointing at a section that did not exist, caught by deliberate audit rather than by any check. One instance does not yet arm a 42-file heading-normalization sweep during a deadline week. TRIGGER: the next §-reference phantom found in the wild — a second instance proves audit does not scale and arms the sweep. FIRST ATTEMPT MEASURED THE INSTRUMENT, NOT THE SUBJECT (see below); a real seal needs heading normalization first.
  status: parked · owner: unassigned · trigger: the next §-reference phantom found in the wild — one instance caught by deliberate audit proves the defect exists; a SECOND proves the audit does not scale, and that is what arms the 42-file heading-normalization sweep
  → [docs/plans/section-reference-phantoms-unsealed.md](plans/section-reference-phantoms-unsealed.md)

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

- **archetype-chosen-before-data** — CLOSED 2026-08-20 by 15fcf17 — the claim is now FALSE BY CONSTRUCTION. The payload is validated against the published contract BEFORE the archetype is accepted, so a list of CAGE codes fails as `rows aren't objects` and CHART_WIDGET never enters the candidate set. Was: The UI archetype is selected from the verb's output_uri before anything looks at the rows, so every analyzeDataset result becomes a CHART_WIDGET — including a list of CAGE codes, which are identifiers and can never be plotted. The payload's shape should decide; output_uri is a hint, not a verdict.
  status: closed · owner: agent · closed-by: 15fcf17
  → [docs/plans/archetype-chosen-before-data.md](plans/archetype-chosen-before-data.md)

- **broker-catalog-urn-derivation** — CLOSED — the broker keyed its Redis routes from a derivation forcing platform="dagster", which also flipped the NAME LAYOUT to dotted, so one asset had two irreconcilable identities and every data read 404'd against a routing table that looked fully populated. Proven end-to-end at work 2026-08-15.
  status: closed · owner: agent · repo: dag-tools · closed-by: a99779f
  → [docs/plans/broker-catalog-urn-derivation.md](plans/broker-catalog-urn-derivation.md)

- **ceremony-record** — ADR-0034 ceremony, end to end — identity-vs-pointer repair, cursor wedge, at-least-once intake, escalation, and the completion witness (dr-08a9c7e7a8c04e00, the corpus's first monitored row).
  status: closed · owner: agent · closed-by: 96f2657
  → [docs/plans/2026-08-06-artifact-uri-repair-witness.md](plans/2026-08-06-artifact-uri-repair-witness.md)

- **column-intercepts-without-verb-coverage** — CLOSED — 48% -> 0%, measured before and after on the same rig. idp:Column intercepted nearly half of catalog queries with ZERO compatible verbs because it hangs off prov:Entity and the compat-walk only climbs. Four verbs declared from the ontology's own Column definition; re-measured clean. ORIGINALLY: idp:Column intercepts nearly half of catalog queries and has ZERO compatible verbs, because it hangs off prov:Entity rather than idp:Dataset so no subClassOf walk reaches the nine catalog verbs. The class was restored to the Weaviate pool without the verb migration that was supposed to accompany it.
  status: closed · owner: agent · closed-by: 482ed6f
  → [docs/plans/column-intercepts-without-verb-coverage.md](plans/column-intercepts-without-verb-coverage.md)

- **cortex-ui-transport-idiom** — DESIGN READ (2026-08-11) for repo 5 of 5. cortex-ui is a static SPA behind nginx — there is NO server-side origin, so the "unminted caller" frame does not apply and the sweep population is browser call sites only. One confirmed defect: NodeInspector sends no token AND bypasses runtime config, two defects on one line where the outer masks the inner.
  status: closed · owner: unassigned · repo: cortex-ui · closed-by: d1184b3
  → [docs/plans/cortex-ui-transport-idiom.md](plans/cortex-ui-transport-idiom.md)

- **fingerprint-input-normalization** — format_fingerprint stopped being a recording device and became half the trust key that routes supervised vs autonomous, so untidy inputs became trust-key material. Normalization (canonical vendors, attested doc_type, both segments guarded) landed BEFORE any real promotion, which was the whole ordering requirement - a pre-normalization key would have been orphaned by normalization later.
  status: closed · owner: agent · closed-by: 025c8ba
  → [docs/plans/fingerprint-input-normalization.md](plans/fingerprint-input-normalization.md)

- **phase-1-3-consumer-derive-packet** — The consumer half of the 1.3 trust key - the starter DERIVES (format_fingerprint, pipeline_version) from the fetched artifact and the caller supplies only a pointer. Held together rather than staged because a half-derived conjunction inherits the weaker component's trust. Verified 2026-08-19: 29 tests green; test_artifact_provenance_derive.py pins BOTH halves server-derived plus the refuse-loudly and supervised-floor arms.
  status: closed · owner: agent · closed-by: f8837bf
  → [docs/plans/phase-1-3-consumer-derive-packet.md](plans/phase-1-3-consumer-derive-packet.md)

- **registration-wiring** — Six engines mint on /v1/register under decode-witnessed identities. Witnessed at a clean log boundary: 0 new unverified, 6 verified (svc:engine-o 1, svc:engine-w 5 — multiplicities matching each engine's verb count).
  status: closed · owner: agent · closed-by: 9d93146
  → [docs/plans/register-caller-enumeration.md](plans/register-caller-enumeration.md)

- **render-request-carries-no-frontend-id** — CLOSED 2026-08-20 by e947069. frontend_id threads all five hops (cortex-ui -> bff -> SupervisorQueryConfig -> supervisor -> /render_ui); select_presentation is wired live; anonymous callers get the DERIVED UNION of registered menus, labelled default-menu, with the empty-registry floor pinned. The acceptance's third item was REWORDED, not met as written: capabilities.py is NOT deleted — only its dead `lookup_capability` is. Was: ACCEPTANCE GREW 2026-08-20: the seam and the retirement of agent_fleet/presentation_agent/capabilities.py are ONE change, because the seam is what makes the registered menu AUTHORITATIVE. The multi-UI promise is proven in tests and unreachable in production. `select_presentation` filters a caller's REGISTERED menu by payload satisfaction, but `RenderRequest` carries no `frontend_id`, so nothing can name the calling client. Small plumbing — a request-model field plus the cortex-bff caller threading it. ⚠️ DO NOT wire it with frontend_id=None: that resolves every caller to the default menu and turns every answer into a KNOWLEDGE_DOCUMENT.
  status: closed · owner: unassigned · closed-by: e947069
  → [docs/plans/render-request-carries-no-frontend-id.md](plans/render-request-carries-no-frontend-id.md)

- **sdk-transport-auth-handoff** — One authenticated registration transport in the SDK app factory. Verified CONSUMED, not merely shipped - 68e28c0 is an ancestor of tag v0.3.0, and invincible-agent pinned v0.3.0 at the time of verification (now v0.3.1, which supersedes it).
  status: closed · owner: agent · repo: iagent-mesh-sdk · closed-by: 68e28c0
  → [docs/plans/sdk-transport-auth-handoff.md](plans/sdk-transport-auth-handoff.md)

- **suite-unrunnable-on-windows-native** — CLOSED 2026-08-21, and the finding was MY INVOCATION, not the tree. `uv run --frozen --extra agent-fleet python -m pytest tests/` gives 1538 passed / 167 skipped / 0 failed / ZERO collection errors in 12:08 — all three named causes gone (rdflib and smolagents come from the extra; WinError 1920 never fires). `.venv.wsl` still exists and is still untraversable by a bare Windows interpreter, so the observation was real; the conclusion that the SUITE was unrunnable was wrong. The repo's own test docstrings already prescribed the uv form. The N-minus-7 qualifier this packet asked people to attach to local results is WITHDRAWN — it would have made every correct green read as provisional.
  status: closed · owner: unassigned · closed-by: 20a7e00
  → [docs/plans/suite-unrunnable-on-windows-native.md](plans/suite-unrunnable-on-windows-native.md)

- **transport-gauge** — Gauge reads only migratable callers: probe paths exempt, 549 -> 22 -> 0-new-unverified.
  status: closed · owner: agent · closed-by: e18b5cf
  → [docs/plans/transport-auth-gauge-day-zero.md](plans/transport-auth-gauge-day-zero.md)

- **triage-card-archetype** — A triage task is a THIRD species, not an approval. Offering Approve/Reject on "this notice could not be prepared for review" records a decision the schema cannot represent, and ADR-0034 would archive it as evidence. Verbs are now per-species and a wrong verb is REFUSED, not stored; cortex-ui ships TRIAGE_TASK (e55d308). Verified 2026-08-19: 11 tests green incl. refuses-approve-and-reject and acknowledge-without-a-reason-is-refused.
  status: closed · owner: agent · trigger: WAKE when the first real unprocessable notice arrives that Re-drive CANNOT fix - i.e. when a human actually needs an escalation lane, not before. Until then Acknowledge-with-reason covers the case honestly. Lifted out of prose into this field 2026-08-20 so a generated board can see the condition. · closed-by: 906cf64
  → [docs/plans/triage-card-archetype.md](plans/triage-card-archetype.md)

- **ui-renders-honest-failure-as-answer** — CLOSED 2026-08-18 — the SUCCESS arm is witnessed live: alice asked a Tier-1 question and got a real absence stated as an answer in a proper card, verified against ground truth measured BEFORE the query ran. NB the grant is applied but INERT (ENABLE_AGENTIC_AUTH=false fleet-wide), so this witnesses the pipeline and the honest-failure render, NOT authz. Was: HIGH — an ungrounded DA run returns `status: "success"` with an apology as its `data`, so nothing downstream can distinguish "here is your answer" from "I could not find the asset". Witnessed 2026-08-15: the data path SUCCEEDED and returned real rows, and the UI showed the apology from a concurrent run that did not ground.
  status: closed · owner: agent · closed-by: 210ecdd
  → [docs/plans/ui-renders-honest-failure-as-answer.md](plans/ui-renders-honest-failure-as-answer.md)

- **unminted-caller-enumeration** — Five-repo sweep for callers reaching mesh routes without a minted identity. CLOSES ON CONSUMPTION, NOT PUBLICATION - the remedy (iagent-mesh-sdk a934c61, "bind the SDK's OWN consumer") shipped as v0.3.1 on 2026-08-10 and this repo pinned v0.3.0 for nine days. Closed 2026-08-20 by 9b52b75, which bumps the fleet to v0.3.1 across 23 files (2 root pins, 10 engine pins, the domainBroker chart value, 11 lockfiles). Evidence: the SDK seal test_registration_consumer_is_bound.py is 5/5 green at a934c61, uv.lock resolves a934c617 by sha, every pyproject reports exactly ['v0.3.1'], and 37 consuming-repo seals pass incl. the broker-vs-fleet coherence check.
  status: closed · owner: agent · closed-by: 9b52b75
  → [docs/plans/unminted-caller-enumeration.md](plans/unminted-caller-enumeration.md)

- **work-deploy** — DEPLOYED in OBSERVE. The go was given and the three reads are settled — 1 done, 2 retracted as the wrong tool for this cluster, 3 decode-verified green. Residual fifth read (which identity a notebook session carries) is not a blocker and lives with jupyter-user-token-data-access.
  status: closed · owner: human · closed-by: ecdd944
  → [docs/plans/work-deploy.md](plans/work-deploy.md)
