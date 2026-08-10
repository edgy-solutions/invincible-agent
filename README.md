<p align="center">
  <img src="assets/icon.jpg" alt="Invincible Agent" width="280"/>
</p>

<h1 align="center">Invincible Agent</h1>

<p align="center">
  <strong>Authorization between retrieval and synthesis</strong><br/>
  An agentic data mesh where the model never receives content the caller isn't cleared for
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Dagster-1.12.x-4F43DD?style=flat-square" alt="Dagster"/>
  <img src="https://img.shields.io/badge/BAML-0.219.x-FF6B6B?style=flat-square" alt="BAML"/>
  <img src="https://img.shields.io/badge/Restate-1.6.2-000000?style=flat-square" alt="Restate"/>
  <img src="https://img.shields.io/badge/Topaz-0.33.13-2E7D32?style=flat-square" alt="Topaz"/>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square" alt="Python"/>
</p>

---

## What this is

Agentic systems leak because they authorize the **action**, not the **content the model sees**.
An agent with tool access can be prompted — by injection, jailbreak, or ordinary ambiguity —
into surfacing data the caller was never cleared for, because the permission check happens at
the *tool call*, not on the *content flowing back through it*.
[MCP](https://modelcontextprotocol.io/) standardizes **how** agents reach tools and data; it
does not govern **which content within a response** a given caller may see. That layer — above
the tool-access model — is where this system enforces.

**The gate sits between retrieval and synthesis.** The model never receives content the caller
isn't authorized to see, so it *cannot* surface it — regardless of prompt, jailbreak, or model
behaviour. Enforcement is by construction, not by trusting the model:

- **Content-level, pre-synthesis.** Each engine filters retrieved rows / document chunks /
  graph nodes / ontology classes against the caller's grants **before** the model synthesizes.
  The model is handed only the authorized subset.
- **Deny-by-default, explicit per-asset grants.** A caller reads an asset only via an
  *explicit, auditable* grant. Entitlement / persona / domain are *eligibility* (necessary),
  never the grant (sufficient) — need-to-know, not clearance-implies-access.
- **Deny-by-construction where the surface is dangerous.** The graph-query interface is a
  bounded, Cypher-flavoured API, not free-text Cypher: unsafe queries are *inexpressible*, not
  filtered-after — there is no parser at the security boundary to be incomplete.
- **Single decider.** One authorization authority ([Topaz](https://www.topaz.sh/), ReBAC);
  every enforcement point *asks* and honours the answer. No policy predicate in application
  code, no drift between where a decision is made and where it's enforced.
- **Compartment-ready as a deployment overlay.** The same system runs unclassified or fully
  classified by config. Compartment assignment is per-deployment overlay, not code.

Designed to be **certifiable**: enforcement lives at the data / query layer, provable to a
reviewer by reading a bounded surface, rather than resting on an application-completeness claim.

> **How it works** → [`docs/architecture/authorization.md`](docs/architecture/authorization.md).
> **The decisions** → [ADR-0025](docs/adr/) (instance-plane access control),
> [ADR-0026](docs/adr/) (persona/entitlement authorization).

### The mechanism: a polyglot agentic mesh on Kubernetes

A strictly decoupled microservice architecture where a **Dagster control plane** orchestrates a
fleet of independent FastAPI engines. Each engine has its own codebase, OCI image, and K8s
Service. Inter-service contracts are BAML-typed; routing decisions are predicate-graph driven
(ADR-0004). The polyglot mesh is *how* the thesis above is delivered — it is not the point.

---

## Current posture — as of 2026-08-08

This section is dated because it describes **live enforcement state**, and a stale posture claim
is worse than none. Updating it is part of each flip's definition of done.

| control | state | meaning |
|---|---|---|
| **transport auth** (`REQUIRE_TRANSPORT_AUTH`) | **OBSERVE** (default) | Every mesh service validates any credential presented, logs the caller posture per request, and **refuses nothing**. The migration is read from a gauge, not asserted. |
| unverified-caller gauge | **22**, on non-exempt paths | All 22 are engine self-registration (`/v1/register`) with no Authorization header. Kubelet probe paths are exempt, so this number can reach zero. |
| **`ENABLE_AGENTIC_AUTH`** | **DISABLED** (dark launch, ADR-0025) | Gates three Topaz asks: DataHub `can_view`, Weaviate per-chunk `can_read`, Neo4j per-result `can_read`. Flips last, after every caller is verifiable. |
| central-gateway data-access ask | **live, fail-closed** | Non-200 and exceptions are hard denies with a `TOPAZ AUTHZ DENIED` marker. The former `ALLOW_MOCK_AUTH` fail-open is **removed** (dag-tools `60cf283`). |
| API docs routes | **disabled in deployment** | `/docs`, `/redoc`, `/openapi.json` are off; `IAGENT_MESH_DOCS=1` re-enables for dev. |

**Known-open, named rather than omitted:** the contract-phase flip is blocked on those 22
callers minting; engine self-registration does not yet authenticate; and the test suite is not
green (see [`docs/plans/suite-signal-session.md`](docs/plans/suite-signal-session.md) for the
measured census).

---

## Agent fleet

| Engine | Framework | Port | Primary endpoint | Role |
|--------|-----------|------|------------------|------|
| **O** | rdflib + Weaviate + BAML | 8084 | `/route_intent`, `/resolve`, `/search_predicates` | Ontology + predicate-graph router. Subject grounding via RDF; engine selection via the Weaviate predicate graph (ADR-0004). |
| **A** | Restate + smolagents | 8081 | `/analyze` | Durable analyst with a code-agent loop; JIT-bound tools discovered through DataHub. |
| **B** | LangGraph + Postgres | 8082 | `/support` | Stateful synthesis & follow-up dialog (`AsyncPostgresSaver`). |
| **C** | Swarms.ai | 8083 | `/scrape` | Stateless heavy-compute extraction. |
| **D** | httpx + DataHub GMS | 8085 | `/query_metadata`, `/lineage_by_platform` | Catalog wrapper — owner, lineage, freshness, tags, schema. |
| **DA** | Restate + smolagents + Polars | 8089 | `/analyze_data` | Universal data plane. Postgres / ClickHouse / S3 Parquet / Delta / Iceberg via CortexDataClient, Topaz-enforced RLS/CLS. |
| **E** | Restate + smolagents + Neo4j + mem0 | 8086 | `/query_graph`, `/resolve_instance`, `/resolve_dmc` | Knowledge-graph expert; bounded Cypher-flavoured API. |
| **F** | FastAPI + BAML | 8087 | `/render_ui` | Presentation router → typed `DashboardUI` archetypes. |
| **W** | Restate + smolagents + Weaviate | 8088 | `/query_knowledge` | Semantic knowledge expert; per-domain segregation. |

**Supporting services:** cortex-bff (8090, user entry), central-gateway (data broker),
mesh-registrar (verb registration), projector, domain-broker.
**Infrastructure:** PostgreSQL, Restate, Neo4j, Weaviate, Fuseki, Keycloak, Topaz, MinIO,
ClickHouse, DataHub GMS, OpenSearch, Redpanda — one Helm chart.

---

## The workflow & review plane

Beyond query-answering, the mesh runs a **governed review pipeline**: extraction produces
candidate records, a sensor starts reviews, humans (or, under an explicit trust grant, the
system itself) dispose of them, and every disposition lands as a decision record.

- **Extraction → review** — [`src/iagent/defs/extraction_review_sensor.py`](src/iagent/defs/extraction_review_sensor.py)
  turns extraction output into review work.
- **Review start** — [`agent_fleet/restate_analyst/review_starter.py`](agent_fleet/restate_analyst/review_starter.py),
  a durable Restate workflow holding `can_invoke(mesh:startReview)` under its own service
  identity (`svc:review-starter`).
- **Grouped review** — reviews are presented in batches at the grain a reviewer actually works,
  surfaced through the BFF.
- **Process model** — [ADR-0029](docs/adr/) defines SPO-native workflow steps on Restate.
- **Trust lifecycle** — [ADR-0034](docs/adr/) defines admission policy, decision records, and
  how autonomy is granted and revoked.

### Autonomy is a trust rung, not a mode

Coverage is total — everything is reviewed. What varies is *who* may dispose of it, and that is
resolved by an explicit **trust table**
([`agent_fleet/utils/trust_table.py`](agent_fleet/utils/trust_table.py), ADR-0034):

| rung | meaning |
|---|---|
| `supervised` | a human disposes. **The default, and the value computed from absence.** |
| `monitored` | the system may act, with sampling as the standing evidence engine |
| `trusted` | the system may act unsupervised for this key |

Three properties make this a governance mechanism rather than a feature flag:

- **Deny-by-default, computed from absence.** An unlisted vendor-format resolves to
  `supervised`. A missing row cannot mean "go ahead."
- **The grant is keyed on `(format_fingerprint, pipeline_version)` and BOTH must match.** A rung
  earned under one pipeline version does **not** carry to the next — autonomy lapses on version
  drift rather than surviving it.
- **No rung above `supervised` may key on a value that cannot discriminate.** Sentinel
  fingerprints and sentinel versions are rejected at parse time, because four unrelated vendors
  sharing one key would otherwise inherit one another's trust.

The resolver has **one home**, deliberately: it moved to `agent_fleet/utils/` when
`ReviewStarter` became a second caller, because *two copies of an admission-policy resolver are
two chances to disagree about whether a pipeline may act unsupervised*.
[`src/iagent/trust_table.py`](src/iagent/trust_table.py) is a re-export shim so existing
importers were provably unaffected.

For what has actually been witnessed in a running system — as opposed to what the table permits
— see the dated `sessions/` trail.

---

## Identity & transport auth

Service-to-service identity is **declaration-born and minted at use**. There is no long-lived
service credential in a config file to leak or to go stale.

| concern | mechanism |
|---|---|
| identity exists because | `keycloak.serviceClients` in the chart, converged by a post-upgrade **realm-reconcile job** — never hand-created |
| credential obtained by | `iagent_mesh.service_identity.mint_token(client_id, client_secret)` — **client-credentials, minted per use**, no stored JWT to expire |
| inbound verification | `iagent_mesh.transport_auth` — one implementation, applied as an app-level FastAPI dependency on every mesh service, validating signatures against Keycloak's JWKS |
| user (front-door) auth | `src/iagent/auth.py::get_current_user` — Keycloak JWT, signature verified against live JWKS, `algorithms=["RS256"]` pinned, all failure paths 401 |
| posture visibility | every service announces `transport auth: OBSERVE (default)` at startup and logs one gauge line per request |

**Identity is an argument, never an ambient env read.** A helper with a general name reading a
specific service's credentials is how a dispatcher once came to act as another role; the mint
takes its client id explicitly, and every new call site decodes its first token and asserts the
subject. **The mint's witness is the decoded subject, not the 200.**

> `MESH_DEV_TOKEN` is a **dev-only fallback that announces itself** when used. It is not the
> normal path and must not appear in a deployed configuration; a static token whose safety rests
> on *where the process happens to run* is the perimeter assumption this design removes.

---

## Design principles

1. **Strict decoupling** — each engine is an isolated pod with its own codebase and image. No
   cross-engine framework imports; Dagster never imports an agent SDK.
2. **FastAPI everywhere** — one wire protocol (HTTP + JSON) across every agent framework.
3. **BAML as interface** — type-safe contracts shared mesh-wide. Tool docstrings are part of the
   contract surface.
4. **Ontology-first grounding** — subjects are resolved through the IOF/MIMOSA RDF graph before
   any agent executes. The RDF graph is the *vocabulary*; the predicate graph is the *router*.
5. **Durable at the step level** — Engines A / DA / E / W wrap side-effecting calls in Restate
   `ctx.run()`, so a step survives pod restarts and replays return journaled values.
   **Stated honestly:** this is *step-level* durability. Effects issued *inside* an agent loop
   are not yet exactly-once — loop-effect idempotency is a known-open design item, not a
   property to assume. Telemetry boundaries are replay-safe by construction (ADR-0038).
6. **Stateful when needed** — Engine B checkpoints conversation state in Postgres; A/DA/E keep
   long-term episodic memory in mem0.
7. **Multi-stage Docker via `uv`** — engines build from their own pinned lockfile with
   `uv sync --locked`, so a lockfile that disagrees with its `pyproject.toml` **fails the build**
   rather than silently producing an image missing a declared dependency.
8. **Dagster as router** — pure HTTP dispatch; the supervisor is dynamic, one
   `/search_predicates` lookup per subtask.
9. **Declaration over hand-seeding** — identities, predicates and config come into being because
   the chart declares them. A hand-created resource makes a sandbox work while making it *wrong
   as evidence*.

---

## What NOT to do

Each of these is a paid-for defect class, not a style preference.

- **Don't grant a service identity data-read access.** `svc:*` identities say *which service
  called*, never *whose data may be read*. Transport is not entitlement; the acting human
  travels as data and is derived from the front-door identity.
- **Don't add a permissive fallback cell** to the entitlement matrix. A default-allow cell is
  indistinguishable from a grant someone made deliberately, and it survives every audit that
  reads names instead of code.
- **Don't hand-mutate what a reconciler owns.** Keycloak clients, Topaz relations and predicate
  registrations are declared. A hand-created identity works until the next fresh deploy, and
  then fails as a new incident with no diff to review.
- **Don't disable a gate to unblock yourself.** A bypass branch's only remaining function after
  the real path works is hiding the next outage — coupled interim mechanisms retire together.
- **Don't treat a `request_key` as a pointer.** It is an artifact key: stable, meaningful, and
  used as trace identity. Never LLM-derived.
- **Don't read a comment as a deployment fact.** A comment asserting deployment state is an
  untested claim, and a comment describing a *fixed* defect reads exactly like one describing a
  live one.

---

## Boundaries — what this system is not

- **Agentic ≠ autonomous.** Every path is reviewed. Autonomy is a *trust rung* granted per
  format at notice grain, and revoked by version drift. There is no "the agent decides" mode.
- **Authorization ≠ authentication.** Topaz answers *may this subject do this*; it assumes the
  subject was authenticated elsewhere. Enforcing authorization on an unauthenticated identity
  produces real, logged, auditable, and meaningless decisions.
- **The gate is not the model.** No prompt, system message, or fine-tune is load-bearing for
  access control. If enforcement depended on model behaviour, it would not be certifiable.
- **Dark-launched ≠ enforcing.** Flags default off and announce their own state, so a gate that
  is present but disabled is legible as such.

---

## Architecture decision records

Every load-bearing decision is captured in [`docs/adr/`](docs/adr/) — **38 records**
(ADR-0001 … ADR-0038). Regenerating this index is part of any new ADR's definition of done.

| ADR | Subject |
|-----|---------|
| [0004](docs/adr/) | **Predicate-graph routing** (the current router) |
| [0009](docs/adr/) | **Sunset of legacy classification axes** |
| [0012](docs/adr/) | UI archetype rigidity (deferred fix) |
| [0013](docs/adr/) | Engine D capability surface |
| [0014](docs/adr/) | No hardcoded URN hints in prompts; broker/catalog separation |
| [0016](docs/adr/) | Fact-storage authority: read from the system-of-record |
| [0017](docs/adr/) | Presentation-as-Predicate |
| [0019](docs/adr/) | **The ontology is the routing substrate** |
| [0022](docs/adr/) | DataHub integration: owned wrapper |
| [0023](docs/adr/) | AnswerArtifact as a graph-native CQRS object |
| [0025](docs/adr/) | **Instance-plane access control as provenance** (ABAC over Topaz) |
| [0026](docs/adr/) | **Persona & entitlement authorization via Topaz** |
| [0027](docs/adr/) | Composable multi-dimensional approval policy |
| [0029](docs/adr/) | **The process-workflow model** (SPO-native steps on Restate) |
| [0031](docs/adr/) | Instance-resolution ladder |
| [0034](docs/adr/) | **The trust lifecycle** — admission policy, decision records, autonomy |
| [0035](docs/adr/) | Two planes: process and data, joined by embedded provenance |
| [0036](docs/adr/) | Config layering: seed, overlay, composition |
| [0038](docs/adr/) | **Telemetry as provenance projection** (Langfuse standard) |

Bold rows shape the current implementation; the full set including superseded and deferred
decisions is in the directory.

---

## Getting started

```bash
uv sync                      # root deps (orchestrator-side work)
dg dev                       # Dagster at http://localhost:3000
uvicorn agent_fleet.ontology_service.main:app --port 8084   # any engine, standalone
```

Engines A / DA / E / W are Restate-durable; for full durability they need a Restate server and
registration as Restate deployments. The FastAPI proxy routes exercise the same code path
without durability guarantees.

**Deploy:**

```bash
scripts/upgrade-sandbox.sh   # bakes in every values file — omitting one is impossible
```

The chart provisions every engine plus supporting infrastructure. Components can be disabled
(`<component>.enabled: false`) or pointed at external instances (`external<Component>`).

**Roll a service:**

```bash
scripts/roll-litany.sh iagent-engine-w
```

Six legs per service — rollout, digest changed, **code present in the container**, posture
announced, gauge line produced, trace joined. It stops at the first failure, because a defect
found at population size one is free.

---

## Testing

```bash
uv run pytest tests/                  # unit / contract tests, no cluster
uv run tests/sandbox_e2e/test_engine_w_knowledge.py   # end-to-end through cortex-bff
```

End-to-end tests fire through the deployed `cortex-bff /orchestrate` with a real Keycloak JWT
and consume the SSE stream. See [`tests/sandbox_e2e/README.md`](tests/sandbox_e2e/README.md).

**`master` is not currently green.** The measured failure census and its owner are recorded in
[`docs/plans/suite-signal-session.md`](docs/plans/suite-signal-session.md) — a green suite is not
yet a valid gate, and saying so is cheaper than letting someone discover it.

---

## Where to read next

| you want | read |
|---|---|
| why a decision was made | [`docs/adr/`](docs/adr/) — 38 records, one decision each |
| how to work in this repo | [`AGENTS.md`](AGENTS.md) — conventions, safety boundaries, and the probe/witness doctrine |
| the authorization topology | [`docs/architecture/authorization.md`](docs/architecture/authorization.md) |
| every route's gating posture | [`docs/architecture/endpoint_gating_manifest.yaml`](docs/architecture/endpoint_gating_manifest.yaml) |
| entitlements & grants | [`policy/README.md`](policy/) |
| what happened and why | `sessions/` — the dated narrative trail |
| the contracts | [`baml_shared/baml_src/contracts.baml`](baml_shared/baml_src/contracts.baml) |

---

## Learn more

[Dagster](https://docs.dagster.io/) · [BAML](https://docs.boundaryml.com/) ·
[Restate](https://docs.restate.dev/) · [smolagents](https://huggingface.co/docs/smolagents/) ·
[LangGraph](https://langchain-ai.github.io/langgraph/) · [DataHub](https://datahubproject.io/docs/) ·
[Weaviate](https://weaviate.io/developers/weaviate) · [Topaz](https://www.topaz.sh/docs)
