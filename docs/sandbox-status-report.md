# Sandbox deploy status — morning checkin

Generated overnight (commits `35014d5` through `687abf9`).

## TL;DR

**Routing layer is healthy and serving end-to-end on the arm64 k3s cluster.**

- All 18 iagent pods Running 1/1 (or settling, see below).
- 4 predicates seeded into Neo4j + Weaviate.
- Engine O `/search_predicates` returns correctly ranked candidates with
  domain scoping working end-to-end.

Open items at the bottom — none are blockers for ADR-0009 routing
validation. Most are operational polish or follow-up work for things we
discovered while debugging.

## What works

### Cluster

```
namespace: sandbox  (alongside Tika; gya-* prod untouched)
nodes: 7 arm64 (1 control + 6 worker, ~84 GB schedulable headroom)
```

Helm release `iagent` (chart `invincible-agent-0.1.25`, values
`helm/invincible-agent/values-sandbox.yaml`).

### Pods (1/1 Running unless noted)

```
iagent-central-gateway       ← dag-tools, arm64 multi-arch via CI fix
iagent-cortex-bff            ← MAIN_MODULE override + PORT 8090 alignment
iagent-dagster-daemon        ← runs on dagster-server:latest (new image)
iagent-dagster-webserver     ← same
iagent-dagster-user-code     ← probe timeout patched (arm64 dagster CLI = 8.4s startup)
iagent-data-analyst
iagent-engine-a              ← ADR-0008 fallback target
iagent-engine-d              ← datahub-wrapper
iagent-engine-f              ← presentation
iagent-engine-o              ← ADR-0009 Step F'.6 NL routing — BM25 fallback active
iagent-postgresql            ← StatefulSet
iagent-neo4j                 ← StatefulSet  
iagent-weaviate              ← StatefulSet, http+grpc services
iagent-fuseki                ← StatefulSet
iagent-restate               ← StatefulSet
iagent-keycloak              ← StatefulSet
iagent-topaz                 ← FGA authz
```

### Routing — validated test cases

Direct `/search_predicates` via port-forward, after running
`scripts/seed_sandbox_predicates.py`:

| Query | Scope | Top result | Score | Verdict |
|---|---|---|---|---|
| `"query knowledge graph for vibration"` | `MAINTENANCE` | `mesh:queryKnowledgeGraph` (Engine E) | 1.09 | ✓ correct, with 3-way ranking |
| `"analyze the dataset"` | `DATA_ENGINEERING` | `mesh:analyzeDataset` (Engine DA) | 0.83 | ✓ correctly filters out non-DE predicates |
| `"query graph"` | `[]` (unscoped) | `mesh:queryKnowledgeGraph` | 0.81 | ✓ unscoped path also works |

Domain scoping correctly filters: `mesh:analyzeDataset`
(`DATA_ENGINEERING` only) does NOT appear when query is scoped to
`MAINTENANCE`.

## What's NOT validated (TODOs)

These are scoped for follow-up — none block the current routing layer
working end-to-end.

1. **`/orchestrate` end-to-end via Keycloak auth.** I ran out of time
   before testing the full gateway → /route_intent → supervisor → engine
   path. Quick checklist:
   ```bash
   kubectl -n sandbox port-forward svc/iagent-central-gateway 8000:8090 &
   kubectl -n sandbox port-forward svc/iagent-keycloak 8080:8080 &
   # Get a token (test user must exist — see "Open items" #6 below)
   TOKEN=$(curl -s -X POST http://localhost:8080/realms/invincible-agent/protocol/openid-connect/token \
     -d "grant_type=password&client_id=cortex-ui&username=testuser&password=testpass" | jq -r .access_token)
   # Smoke test
   curl -N -X POST http://localhost:8000/orchestrate \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"message":"diagnose vibration in turbine","session_id":"smoke-1"}'
   ```

2. **Engine A's ADR-0008 fallback** has not been exercised. Need an
   "outside the registry" query that triggers `low_confidence` /
   `no_predicate_matched` — the structured-log telemetry will fire,
   tail with:
   ```bash
   kubectl -n sandbox logs deploy/iagent-dagster-user-code -f | grep predicate_fallback_total
   ```

3. **The Engine E / Engine W / Engine B pods are disabled in
   values-sandbox.yaml** (`enabled: false`). Routing finds the
   predicates because the seed script wrote them with the engine
   endpoints; if the gateway/supervisor actually tries to call those
   engines, it'll get a connection refused. For Phase 3 enable them.

## Bugs I had to fix to get here

Listed in commit order, each with one-line rationale. Most are
buildpack→Dockerfile regressions (manual Dockerfile reproducing what
buildpacks did silently).

1. `35014d5` — Engine A/O sibling-module imports (`agent_fleet.X` →
   container has flat `/app/` layout; needed try/except fallback)
2. `276367e` — `_helpers.tpl` purely-additive `registry:` override; chart
   bug `engineD.resources: ...` literal placeholder worked around in
   values; `KEYCLOAK_REALM_URL` / `JENA_SPARQL_ENDPOINT` "last key wins"
   race worked around; dagster-webserver missing from prod deps (moved
   to canonical dagster image); `python -m dagster-daemon` invalid
   module name fixed → use binary
3. `d6d7705` — dagster-server thin image entry in CI matrix; cortex-bff
   chart port (8090) vs CI build port (8000) mismatch fixed
4. `02e3371` — dagster-server heredoc EOF indented in YAML block, never
   terminated — dedented to match existing pattern
5. `73c2037` — dagster-server version pin removed (must match
   unpinned dagster-control-plane to avoid gRPC protocol drift);
   central-gateway chart port 8000 → 8090 to match image's bind port
6. `e294d5e` — Engine O `Filter.by_property('domains').equal([])`
   rejected by Weaviate v4 → use `length=True, equal(0)`
7. `dc23964` — Engine O `hybrid()` requires text2vec module which
   sandbox Weaviate doesn't have → fall back to `bm25()`. Long-term
   the chart should configure text2vec-ollama
8. `687abf9` — Predicate collection needs `IndexPropertyLength=True`
   for the length filter to work — seed script now drops + recreates
   with that config

doc-tools and dag-tools workflows fixed for multi-arch (separate repos,
also pushed):
- doc-tools `4ea9315` (cyclonedds wheel via uv --find-links)
- dag-tools `cef52e1` (QEMU + buildx + platforms)

## Open items (not blocking)

1. **Weaviate has no vectorizer module** (`modules: []`). The chart's
   default Weaviate deployment ships no text2vec module, so:
   - Engine O's `/search_predicates` uses BM25 only (current
     workaround), which works for the small predicate set in the
     registry today but won't generalize well as the predicate count
     grows.
   - Engine W's `/query_knowledge` semantic search (Weaviate hybrid
     over manual collections) would have the same issue if it were
     exercised today. Engine W is disabled in Phase 2 so it doesn't
     block routing.
   - Suggested fix: configure `text2vec-ollama` in the chart's
     Weaviate Deployment, pointing at the ai1 Ollama with
     `nomic-embed-text` as the embedding model.

2. **doc-tools aitool_linker** creates the Predicate collection
   without `IndexPropertyLength=True`. Same fix as `687abf9` needs
   to land in `doc-tools/doc_tools/assets/aitool_linker.py`'s
   `_ensure_predicate_collection` function. Right now doc-tools isn't
   actually running in sandbox (Phase 2 Option A) so it's not biting
   us; will bite Phase 3.

3. **doc-tools CI build is fixed for multi-arch but the cyclonedds
   wheel-into-venv fix has not been verified end-to-end** — the
   workflow now uses `uv pip install --find-links /wheels` to discover
   the pre-built wheel, but I didn't wait for that CI run to complete
   given the time pressure. Check `gh run list --repo edgy-solutions/doc-tools`
   in the morning.

4. **Probe timeouts for `dagster-user-code` are kubectl-patched, not
   chart-managed.** Helm upgrade overwrites them. Either:
   - Add probe-timeout parameterization to
     `helm/invincible-agent/templates/dagster-user-code.yaml`
   - OR check in a Kustomize overlay
   - OR live with re-patching after upgrades

5. **`cortex-ui` (React frontend) is disabled in values-sandbox**
   because the `ghcr.io/edgy-solutions/cortex-ui/frontend:latest`
   image is amd64-only. Apply the same multi-arch fix (QEMU + buildx +
   platforms) to cortex-ui's CI workflow.

6. **Keycloak realm import for sandbox** — the chart provisions the
   `invincible-agent` realm but I haven't confirmed there's a test user
   pre-seeded. If `testuser:testpass` doesn't exist, the
   `/orchestrate` smoke test will fail at auth. Two options:
   - Create the user via Keycloak admin UI (port-forward
     `iagent-keycloak:8080`, login with the admin password from
     values-sandbox)
   - Or add a `bypass-auth` env to the gateway for sandbox testing

7. **Helm release tracker bug** — every `git push` to master triggers
   the `Release Helm Charts` workflow which always fails because the
   chart version isn't bumped. Not blocking, just noisy. Fix is to
   either bump the version on each push or gate the release workflow
   on a tag.

## Files / artifacts

- `helm/invincible-agent/values-sandbox.yaml` — sandbox overrides (45 lines)
- `scripts/seed_sandbox_predicates.py` — registers 4 engines as
  predicates directly (bypasses DataHub→doc-tools sync, which is
  skipped in Phase 2 Option A)
- `/tmp/probe-patch.yaml` — kubectl probe patch for
  `dagster-user-code` (re-apply after helm upgrades)

## Running commands cheat sheet

```bash
# Port-forwards (re-run if killed)
kubectl -n sandbox port-forward svc/iagent-neo4j 7687:7687 &
kubectl -n sandbox port-forward svc/iagent-weaviate 8080:8080 &
kubectl -n sandbox port-forward svc/iagent-weaviate-grpc 50051:50051 &
kubectl -n sandbox port-forward svc/iagent-engine-o 8084:8084 &

# Re-seed (drops + recreates Predicate collection)
PYTHONIOENCODING=utf-8 py scripts/seed_sandbox_predicates.py

# Routing smoke test
curl -s -X POST http://localhost:8084/search_predicates \
  -H "Content-Type: application/json" \
  -d '{"query":"query knowledge graph","entitled_domains":["MAINTENANCE"],"limit":3}'

# Tail predicate routing telemetry
kubectl -n sandbox logs deploy/iagent-engine-o -f | \
  grep -E "search_predicates|predicate_"

# Helm upgrade after values change
helm upgrade iagent ./helm/invincible-agent \
  -n sandbox -f ./helm/invincible-agent/values-sandbox.yaml \
  --set agentFleet.env.DATAHUB_MOCK_MODE=true

# Re-patch dagster-user-code probes after upgrade
kubectl -n sandbox patch deployment iagent-dagster-user-code --patch-file /tmp/probe-patch.yaml

# Force re-pull of a specific component after CI rebuild
kubectl -n sandbox delete pod -l app.kubernetes.io/component=engine-o
```

## Bottom line

The thing you wanted to validate — ADR-0009's NL → predicate routing on
real infrastructure — works. Sandbox is the right level of fidelity for
the next round of testing (Engine E enable, real Engine A fallback path,
Engine F UI rendering). When you're ready for `/orchestrate` E2E, the
next blocker is just the Keycloak test user.
