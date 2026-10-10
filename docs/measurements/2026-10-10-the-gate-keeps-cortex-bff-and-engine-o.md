# The gate keeps cortex-bff and engine-o -- every configured egress flow evaluated, not read

Date: 2026-10-10. Lane 1 (`ia-01-netpol` / `lane/01-netpol`), measured at `ce19bef6`, chart 0.4.40 (rebased onto `3bae602d`). Nothing
rolled, no cluster touched, the gate stays OFF in `values-sandbox.yaml`.

The 10-08 measurement named the cuts by reading configuration against the templates. This one
EVALUATES the rendered policies: `tests/netpol_eval.py` implements NetworkPolicy semantics over
`helm template` output, `tests/test_networkpolicy_flows_survive.py` derives the flows from the render
and asks the evaluator about each.

## What the evaluator models

- A pod's egress is restricted iff some policy with `Egress` in `policyTypes` selects it; it is then
  allowed iff some egress rule matches (peer AND ports; empty `to` / `ports` = all). Likewise ingress
  on the destination. A flow passes iff both sides allow it. A pod may always reach itself.
- Peers: `podSelector` (policy namespace), `namespaceSelector` (the release namespace and
  `kube-system` carry `kubernetes.io/metadata.name`), both together (AND), `ipBlock` with `except`.
  Selectors: `matchLabels` and `matchExpressions`.
- Ports are matched against the DESTINATION POD's port: the Service's `targetPort`, numeric or a name
  resolved to the container port. Never the Service port.
- A host resolves by short name or `name.<ns>.svc[.cluster.local]` to a Service, to its selector, to
  the Deployment / StatefulSet pod templates whose labels match. A host that is not a Service in the
  render is off-cluster: allowed only by an egress `ipBlock` containing the test address assigned to it.
- Flows are derived, not listed: every env value of the workload (direct env, every ConfigMap and
  Secret it pulls in, `valueFrom` refs, `$(VAR)` expansion) that parses as a URL or `host:port`, plus a
  `<X>_HOST` with a sibling `<X>_PORT`, plus kube-dns UDP and TCP 53. An unplaceable URL raises; nothing
  is skipped quietly.

## What it does NOT model

- CNI enforcement details (whether egress is enforced at all, on which datapath, for host-network pods).
- Port-forward and node-local paths: the sandbox e2e probes use port-forwards, so a probe passing under
  the gate stays no evidence for a browser path.
- Hook Job and CronJob pods. The 10-08 addendum still applies in full: nine of ten Job templates carry
  no component label, so no `directCallers` entry can admit them. This work does not change that.
- Traffic. Flows are a configuration census (what the env points at), not what the pod opens.
- Policies in other namespaces, SCTP, `endPort` on named ports, pod IPs as `ipBlock` targets.

## Derived flows

| source | derived destinations (host:port, unique) | of which excluded as non-destinations | evaluated |
| --- | --- | --- | --- |
| cortex-bff | 35 | 4 keys | 31 |
| engine-o | 34 | 4 keys | 30 |

(The count includes kube-dns TCP and UDP 53 as two entries. cortex-bff has no egress policy, so for it
only the destinations' ingress can cut; engine-o has both.) The recorded set is in the test (arm d).

Excluded keys, each with a reason and a freshness assertion (arm e): `DATAHUB_FRONTEND_URL` (public,
browser-facing link), `LANGGRAPH_SUPPORT_SVC_URL` and `SWARMS_SCRAPER_URL` (engine-b and engine-c are
disabled in sandbox, no Service rendered), `SUPERSET_URL` (values.yaml default for a Superset no
workload of this release provides).

## Cuts found, and the fix

First run, gate on, with the model endpoint, MinIO and DataHub GMS given ipBlock rules.

| source | flow (config key) | cut by | fix |
| --- | --- | --- | --- |
| cortex-bff | Weaviate 8080 / 50051 (`WEAVIATE_HTTP_HOST`, `WEAVIATE_GRPC_HOST`) | weaviate ingress | `directCallers.cortex-bff` + weaviate |
| cortex-bff | Fuseki 3030 (`JENA_SPARQL_ENDPOINT`, `JENA_UPDATE_ENDPOINT`) | fuseki ingress | + fuseki |
| cortex-bff | Topaz 9393 (`TOPAZ_DIRECTORY_URL`) | topaz ingress | + topaz |
| engine-o | Postgres 5432 (`DATABASE_URL`, `LANGGRAPH_POSTGRES_URI`, `BPMN_POSTGRES_HOST`) | engine-o egress | `directCallers.engine-o` + postgresql |
| engine-o | Keycloak 8080 (`KEYCLOAK_REALM_URL`) | engine-o egress | + keycloak |
| engine-o | central-gateway 8090 (`CENTRAL_GATEWAY_URL`) | engine-o egress | + central-gateway |
| engine-o | dagster-webserver 3000 (`DAGSTER_WEBSERVER_URL`) | engine-o egress | + dagster-webserver, **template change** (below) |

Every entry carries its `via` and `expires: "2026-12-14"`. All are admissions of a configured flow
that the 10-08 census had not predicted (cortex-bff's table B listed Postgres, Neo4j, Restate and
Keycloak only). Whether each is a flow the pod really opens is the traffic half and is not measured.

**The one template change.** `DAGSTER_WEBSERVER_URL` names a component that is neither a store (the
store table renders an ingress policy, which would fence dagster-webserver against every other caller)
nor an engine (no `.port` value). `directCallers` could not express it, so
`invincible-agent.networkPolicyEgressOnlyTargets` (`_helpers.tpl`) adds a target table that only the
engine egress template reads: an egress rule, and no ingress policy. Chart 0.4.38 -> 0.4.40 at measurement; renumbered 0.4.41 on 2026-10-10 (rev 186 takes 0.4.39, lane/01-oidc-roundtrip 0.4.40).

**Not cuts, but not nameable.** MinIO (`iagent-minio:9000`) and DataHub GMS (`datahub-datahub-gms:8080`)
are in-namespace in reality but not Services of this render, and no workload in it carries their
component label, so no `podSelector` can name them from this chart. The test overlay
(`tests/fixtures/netpol/values-flows.yaml`) models them, and the model endpoint, as `ipBlock`
`extraEgress` rules on RFC 5737 documentation addresses. For the roll, the same shape goes in the
untracked secret values file. engine-o is cut from both until it does: those two flows are the
open item the roll must close, since an in-cluster pod IP is what the ipBlock would have to name.

## Mutations

Each by hand, restored by copy from a backup, tree diff checked.

| mutant | result |
| --- | --- |
| remove engine-o's neo4j `directCallers` entry | `test_EVERY_ENGINE_O_FLOW_SURVIVES_THE_GATE` red, 11 others green |
| evaluator matches the Service port instead of the `targetPort` | **quiet, 12 passed.** No Service whose pod a policy selects remaps a port: every such Service has `port == targetPort` after the name is resolved (`http`, `bolt`, `grpc`, `tcp-pg`, `ingress`, `admin` all name the same number). The one remap in the chart is cortex-ui `80 -> 8080`, which no policy selects and no flow targets. This is a finding about the chart, not a hole to decorate: the arm that would bite needs a policy-covered Service that remaps, and there is none today. The store port table is therefore correct as typed. |
| evaluator ignores egress policies | `test_CONTROL_A_TARGET_OUTSIDE_ENGINE_O_DIRECT_CALLERS_IS_DENIED_BY_EGRESS` and `test_CONTROL_AN_UNLISTED_OFF_CLUSTER_ADDRESS_IS_DENIED` red |

Tests: flows-survive 12 passed; with the join, allowlist-by-component, exceptions-expire and
substrate-address-lint files 41 passed, 1 skipped (log `C:	mp
etpol-tests.log`).
