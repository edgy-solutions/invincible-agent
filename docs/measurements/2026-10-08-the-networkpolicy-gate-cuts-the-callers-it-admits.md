# The NetworkPolicy gate cuts the callers it admits — measured cut list, and the first gate-on roll

Date: 2026-10-08. Lane 1 (`ia-01-roll21` / `lane/01-roll21`), master at `5b66fdc3`, sandbox helm revision 177.

## Ruling (Chris, 2026-10-08)

> Roll without the gate. […] the first gate-on roll admits today's direct callers explicitly (per-pod
> egress to the stores each is measured to use, engine↔engine, Restate/Topaz/MinIO/Redis, the LLM
> endpoint from the secret values), and the ban tightens as each caller migrates onto the Mesh\*
> services. A perimeter that cuts production paths on day one is a perimeter that gets turned off.
>
> Roll #21 = SDK v0.9.8 + promotion fix + cortex pin, engine-o first. Gate-on is its own roll next week.

So `lane/01-np-on@cac1d07b` (`values-sandbox.yaml: networkPolicy.enabled: true`) is **not** merged
for roll #21. This document is the proposal the gate-on roll builds from.

## How it was measured

1. **Render.** `helm template iagent helm/invincible-agent -f values-sandbox.yaml --set
   networkPolicy.enabled=true` at `5b66fdc3`: 20 NetworkPolicies, 14 egress (one per enabled engine) and
   6 ingress (one per store).
2. **Selection.** Each policy's selector (`app.kubernetes.io/name=invincible-agent`,
   `app.kubernetes.io/component=<c>`) was run against the live namespace. Every store selector and the
   engine-o and cortex-bff selectors match exactly one pod. The policies are not inert: they would
   take effect.
3. **Consumers.** For every Deployment and StatefulSet, the store addresses its env carries: direct
   `env`, plus the shared `iagent-config` ConfigMap that most workloads load with `envFrom`.
   **This is a CONFIGURATION census, not a traffic census.** A workload that carries an address may
   never open it, and a workload could reach a store through an address it builds at runtime. The
   flag-on census (the worker's `25c6f934`, which names a cut flow rather than reading it as parity)
   is the traffic half, and it runs on the gate-on roll.

## What the gate as built cuts

### A. Engine egress: every engine gets the same four rules

`templates/networkpolicy-engines.yaml` gives each of the 14 engines exactly:

| rule | target | sandbox reality |
| --- | --- | --- |
| 1 | kube-dns 53 | ok |
| 2 | cortex-bff 8090 | ok |
| 3 | mesh-registrar 8090 | ok |
| 4 | litellm 4000 | **selects no pod**: litellm is disabled in sandbox (09-28 measurement §6) |
| 5 | `extraEgress` (verbatim) | empty by default |

The flows that `iagent-config` points engines at, all of which these rules deny:

| flow | config key(s) |
| --- | --- |
| engine-o → Neo4j 7687, Fuseki 3030, Weaviate 8080/50051 | `NEO4J_URI`, `JENA_*_ENDPOINT`, `WEAVIATE_*_HOST` |
| every engine → engine-o 8084 | `ONTOLOGY_SERVICE_URL`, `ONTOLOGY_RESOLVE_URL`, `ENUMERATE_INSTANCES_URL` |
| engine → engine | `ENGINE_*_PUBLIC_URL`, `PRESENTATION_AGENT_SVC_URL`, `RESTATE_ANALYST_URL`, `*_EXPERT_SVC_URL`, `DATAHUB_WRAPPER_URL` |
| engine → Restate ingress 8080 | `RESTATE_INGRESS_URL` |
| engine → Topaz 9393 | `TOPAZ_DIRECTORY_URL` |
| engine → MinIO 9000 | `MINIO_ENDPOINT_URL`: **in-cluster** in sandbox, so a podSelector rule can name it, contrary to the template comment's "not in this chart" |
| engine → Redis 6379 | `REDIS_URL` |
| engine → the model/embedding endpoint | `LLM_BASE_URL`, `OLLAMA_BASE_URL`, `MEM0_OLLAMA_BASE_URL`: an **off-cluster** host, so `extraEgress` (secret values) is the only rule that can reach it |

### B. Store ingress admits six components

`templates/networkpolicy-stores.yaml` admits `engine-o, mesh-registrar, engine-a, engine-w, engine-e,
engine-f` to all six stores. Configured consumers that are **not** admitted:

| store | not admitted, but configured to reach it |
| --- | --- |
| Postgres 5432 | cortex-bff (human tasks, ingest status, decision ledger), dagster-daemon, dagster-user-code, dagster-webserver, projector, electric, engine-lg, dag-tools, pub-tools, datahub-gms, and engine-b (`LANGGRAPH_POSTGRES_URI`) |
| Neo4j 7687 | cortex-bff (the gateway's own artifact and lineage reads) |
| Restate 8080 | cortex-bff (`ReviewStarter` and workflow ingress), and every engine that calls Restate ingress |
| Keycloak 8080 | cortex-bff (token validation), cortex-ui, data-analyst, doc-tools, and every browser login through the ingress controller |
| Weaviate 8080/50051 | doc-tools |

Keycloak's own database is `dev-file`, so the Postgres policy does not take Keycloak down. Its
port-8080 ingress policy does cut every login that does not arrive by port-forward.

### C. The join: the two halves disagree about the six they both name

The store side admits engine-o, engine-a, engine-w, engine-e and engine-f, and the engine side denies
each of those five every store. engine-o, the ontology service, would be admitted to Neo4j, Fuseki and
Weaviate by their ingress policies and refused by its own egress policy. Each template passes its own
arms (09-28 measurement: 23 passed). No arm asserts that the egress side admits what the ingress side
admits, which is exactly the class in which every endpoint is verified and the join is not.

## Proposal for the gate-on roll (per the ruling)

1. **One population, two renderings.** Replace the literal `$admitted` list and the uniform engine
   egress with a single values-level map, `networkPolicy.directCallers: {<component>: [<store>, …]}`.
   The store template admits exactly the components listing it, and each engine's egress gains a rule
   to exactly the stores it lists. The join then holds by construction, and an arm asserts it on the
   render.
2. **Seed the map from this census**, one entry per row of tables A and B, each carrying a comment
   that names the config key that put it there. Every entry is an explicit admission of a direct
   caller. The ban tightens by deleting entries as callers move onto the Mesh\* services, and the
   existing `tests/test_substrate_allowlist_exceptions_expire.py` discipline (an expiry per exception)
   should apply to these entries too.
3. **Fleet-internal egress for every engine**: engine-o 8084, the engine ports the `ENGINE_*` keys name,
   Restate ingress 8080, Topaz 9393, Redis 6379 and MinIO 9000, all by podSelector because all are
   in-cluster in sandbox.
4. **The model endpoint** goes in `extraEgress` in the untracked `values-sandbox.secret.yaml` (an
   ipBlock with port 11434). Its address is never committed.
5. **Keycloak** admits the ingress controller's namespace. Without it, the gate-on roll breaks login.
6. **Non-engine workloads** (cortex-bff, Dagster, projector, electric, doc-tools, dag-tools, pub-tools)
   have no egress policy at all today (09-28 §7). The first gate-on roll changes only their *ingress*
   reachability, through table B, so adding them to `directCallers` is what keeps them working.
7. **Run order on the roll:** render diff → roll → the worker's flag-on census ×3 → the walk census.
   A cut that the census names and this list did not predict is a new row, not a rollback, unless it
   is login or the promote path.

## Not measured

- Traffic. Every consumer above comes from configuration, and the flag-on census is the traffic half.
- Whether the cluster's policy controller enforces egress on port-forwarded connections. The
  sandbox e2e probes use port-forwards, so a probe passing under the gate is not evidence that a
  browser path passes.
- Workloads outside this chart's namespace (doc-tools' own release is in the same namespace and is
  counted; other namespaces are not).

## Addendum 2026-10-08 (after `directCallers` landed, 75879d32): the hook Jobs are callers nobody listed

Tables A and B cover long-running workloads. The chart also runs ten Job and CronJob templates, and
**nine of them put no `app.kubernetes.io/component` label on the pod template**. Several carry it on
the Job object, which a podSelector never sees. No `directCallers` entry can admit a pod that has
no label to select. Eight of those nine are helm hooks.

The table below is a census of **mentions**, not measured connections. It records which store
names appear anywhere in the template (`grep -o -i`).

| template | pod label | helm hook | stores mentioned |
| --- | --- | --- | --- |
| prime-substrate-job | no | yes | dagster, fuseki, minio, neo4j, postgres, restate, weaviate |
| jobs | no | yes | neo4j, postgres, redis, restate, weaviate |
| demo-seed-job | no | yes | dagster, neo4j, weaviate |
| ontology-seed-job | no | yes | dagster, neo4j, weaviate |
| engine-reregister-job | no | yes | dagster, neo4j |
| minio-bucket-init-job | no | yes | minio |
| realm-reconcile-job | no | yes | keycloak, restate, topaz |
| task-grant-sync-job | no | yes | keycloak, restate, topaz |
| topaz-manifest-load-job | no | yes | restate, topaz |
| topaz-seed-cronjob | **yes** (`topaz-seed`) | no | topaz |

**Consequence if the gate turns on as seeded:** `prime-substrate` is a post-upgrade hook, and a
failed hook fails the release (roll #21's rev 178 is the precedent). So the gate-on roll would
most likely cut its own prime and record `failed`. The grant-sync, manifest-load and seed jobs
would also lose Topaz, so grants would stop reconciling.

**Preconditions for the gate-on roll, added to the proposal:**
1. Every Job and CronJob pod template carries a component label.
2. Every such component that reaches a store gets `directCallers` entries. Derive them from the
   job's real connections (its env and config keys), never from this mention census.
3. Extend the seals' population to Job pods. The component-reality arm
   (`tests/test_networkpolicy_direct_callers_join.py:172`) collects components from `Deployment`
   and `StatefulSet` only, and that is why its green could not see this.
