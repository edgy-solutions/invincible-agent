# sandbox_e2e — end-to-end mesh tests through cortex-bff

These tests exercise the deployed agent mesh in the **sandbox** Kubernetes
cluster. Unlike the mock-heavy unit suites in `tests/`, every request here
flows through the real cortex-bff `/orchestrate` endpoint, gets a real JWT
from Keycloak, and lands on the actual engine pods.

## Prereqs

- A working sandbox cluster (`kubectl -n sandbox get pods` is healthy).
- `uv` on the runner host.
- Two port-forwards open in the background:

```bash
kubectl -n sandbox port-forward svc/iagent-keycloak  18083:8080 &
kubectl -n sandbox port-forward svc/iagent-cortex-bff 18090:8090 &
```

The helpers in `mesh_client.py` default to `localhost:18083` (Keycloak) and
`localhost:18090` (cortex-bff) so the same scripts work from any host that
can reach the cluster API.

## What's here

- `mesh_client.py` — shared helper: fetches a Keycloak JWT for
  `agent-user / password`, opens an SSE stream against
  `/orchestrate`, prints status events, returns the final payload.
- `test_engine_w_knowledge.py` — fires a maintenance-domain
  knowledge-retrieval query and asserts the response cites a manual.
- `test_engine_d_datahub_suite.py` — fires the DataHub-style query
  suite (ownership, freshness, lineage, schema, downstream impact)
  via Engine A's `search_datahub` tool.

## Running

```bash
uv run tests/sandbox_e2e/test_engine_w_knowledge.py
uv run tests/sandbox_e2e/test_engine_d_datahub_suite.py
```

Each test is self-contained (uv inline-script header) so you don't need
the full repo env installed.
