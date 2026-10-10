"""The gate keeps cortex-bff and engine-o: every configured egress flow SURVIVES the rendered policies.

The sibling arms check the two halves of an admission against EACH OTHER (the join) and the store
policies against an allowlist. None of them asks the question the gate-on roll lives or dies on:
does the pod's actual configuration still work once the policies apply? This file answers it by
EVALUATING the rendered policies (tests/netpol_eval.py, a dry-run NetworkPolicy evaluator) against
flows DERIVED from the render -- every URL / host:port in the env of the cortex-bff and engine-o
Deployments (direct env + every ConfigMap / Secret they pull in), plus kube-dns.

  a  every derived cortex-bff flow is allowed
  b  every derived engine-o flow is allowed
  c  the evaluator's own controls: a target outside engine-o's directCallers is DENIED by egress,
     a caller outside postgresql's ingress is DENIED by ingress, an unlisted off-cluster address
     is DENIED, and with the gate off everything is allowed
  d  the derived destination set equals a recorded set (a derivation that finds nothing, or
     silently loses a flow, cannot pass)
  e  the exclusion list is fresh: every excluded key still exists, and still means what its
     reason says

The off-cluster model endpoint, MinIO and DataHub GMS are not chart components, so no podSelector
can name them; the overlay tests/fixtures/netpol/values-flows.yaml carries them as ipBlock rules
on RFC 5737 documentation addresses (the shape a local values file would take). The gate stays
OFF in values-sandbox.yaml. Hook-Job pods, CNI enforcement and port-forward paths are not modelled.

Run: uv run pytest tests/test_networkpolicy_flows_survive.py -v
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tests"))
import netpol_eval as ne  # noqa: E402

_CHART = _REPO / "helm" / "invincible-agent"
_SANDBOX = _CHART / "values-sandbox.yaml"
_OVERLAY = _REPO / "tests" / "fixtures" / "netpol" / "values-flows.yaml"
_FQDN = ".default.svc.cluster.local"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None,
    reason="the `helm` binary is not on PATH: a declared condition, not a probe of any cluster",
)

BFF, ENGINE_O = "iagent-cortex-bff", "iagent-engine-o"

# Hosts that are not Services of this render but ARE destinations: the test gives each a
# documentation-range IP and the overlay's extraEgress an ipBlock for it.
EXTERNAL_HOSTS = {"iagent-minio": "192.0.2.20", "datahub-datahub-gms": "192.0.2.30"}

# Values that are NOT destinations. key -> (kind, reason). `unrendered` also asserts the host is
# still not a Service of the render; `public` asserts it is a dotted name outside the cluster.
EXCLUDED = {
    "DATAHUB_FRONTEND_URL": ("public", "the public, browser-facing DataHub UI link; no pod calls it"),
    "LANGGRAPH_SUPPORT_SVC_URL": ("unrendered", "engine-b is disabled in sandbox; its Service is not rendered"),
    "SWARMS_SCRAPER_URL": ("unrendered", "engine-c is disabled in sandbox; its Service is not rendered"),
    "SUPERSET_URL": ("unrendered", "values.yaml default for a Superset no workload of this release provides"),
}

# The destination set of both sources (host without the namespace suffix, port), printed once from
# the render and recorded. cortex-bff additionally carries ELECTRIC_UPSTREAM_URL.
_COMMON = {
    ("192.0.2.10", 11434), ("datahub-datahub-gms", 8080), ("datahub.edgy-solutions.com", 443),
    ("iagent-central-gateway", 8090), ("iagent-cortex-bff", 8090), ("iagent-dagster", 3000),
    ("iagent-data-analyst", 8089), ("iagent-engine-a", 8081), ("iagent-engine-b", 8082),
    ("iagent-engine-c", 8083), ("iagent-engine-cost", 8097), ("iagent-engine-d", 8085),
    ("iagent-engine-docs", 8100), ("iagent-engine-e", 8086), ("iagent-engine-f", 8087),
    ("iagent-engine-fin", 8096), ("iagent-engine-lg", 8098), ("iagent-engine-o", 8084),
    ("iagent-engine-p", 8095), ("iagent-engine-safety", 8099), ("iagent-engine-w", 8088),
    ("iagent-fuseki", 3030), ("iagent-keycloak", 8080), ("iagent-mesh-registrar", 8090),
    ("iagent-minio", 9000), ("iagent-neo4j", 7687), ("iagent-postgresql", 5432),
    ("iagent-restate", 8080), ("iagent-weaviate", 8080), ("iagent-weaviate-grpc", 50051),
    ("kube-dns", 53), ("superset", 8088), ("topaz-svc", 9393),
}
EXPECTED = {BFF: _COMMON | {("iagent-electric", 3000)}, ENGINE_O: _COMMON}


def _render(*extra: str) -> list[dict]:
    cmd = ["helm", "template", "iagent", str(_CHART), "-f", str(_SANDBOX), "-f", str(_OVERLAY), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"helm template failed: {proc.stderr[-2000:]}"
    return [d for d in yaml.safe_load_all(proc.stdout) if isinstance(d, dict)]


@pytest.fixture(scope="module")
def on() -> ne.Cluster:
    return ne.Cluster(_render("--set", "networkPolicy.enabled=true"), external_hosts=EXTERNAL_HOSTS)


@pytest.fixture(scope="module")
def off() -> ne.Cluster:
    return ne.Cluster(_render("--set", "networkPolicy.enabled=false"), external_hosts=EXTERNAL_HOSTS)


def _short(host: str) -> str:
    return host[: -len(_FQDN)] if host.endswith(_FQDN) else host


def _live_flows(cluster: ne.Cluster, src: str) -> list[ne.Flow]:
    return [f for f in ne.derive_flows(cluster, src) if f.key not in EXCLUDED]


def _cut(cluster: ne.Cluster, src: str) -> list[str]:
    out = []
    for f in _live_flows(cluster, src):
        v = cluster.evaluate(f)
        if not v.allowed:
            out.append(f"{f.key or 'dns'} -> {f.host}:{f.port}/{f.proto}: {v.reason}")
    return out


def _direct_callers() -> dict:
    return yaml.safe_load(_SANDBOX.read_text(encoding="utf-8"))["networkPolicy"]["directCallers"]


# ---------------------------------------------------------------------------------------------
# a, b. every derived flow survives
# ---------------------------------------------------------------------------------------------
def test_EVERY_CORTEX_BFF_FLOW_SURVIVES_THE_GATE(on):
    cut = _cut(on, BFF)
    assert not cut, "the gate cuts cortex-bff flows its configuration names:\n  " + "\n  ".join(cut)


def test_EVERY_ENGINE_O_FLOW_SURVIVES_THE_GATE(on):
    cut = _cut(on, ENGINE_O)
    assert not cut, "the gate cuts engine-o flows its configuration names:\n  " + "\n  ".join(cut)


# ---------------------------------------------------------------------------------------------
# c. the evaluator's own controls
# ---------------------------------------------------------------------------------------------
def test_CONTROL_A_TARGET_OUTSIDE_ENGINE_O_DIRECT_CALLERS_IS_DENIED_BY_EGRESS(on):
    listed = {e["store"] for e in _direct_callers()["engine-o"]}
    assert "dag-tools-broker" not in listed and "weaviate" in listed
    v = on.evaluate(ne.Flow(ENGINE_O, "iagent-dag-tools-broker", 8000))
    assert not v.allowed and "egress of iagent-engine-o" in v.reason, v
    assert on.evaluate(ne.Flow(ENGINE_O, "iagent-weaviate", 8080)).allowed  # the listed twin


def test_CONTROL_A_CALLER_OUTSIDE_POSTGRESQL_INGRESS_IS_DENIED_BY_INGRESS(on):
    # cortex-ui has no egress policy, so egress cannot be what denies it; it has no postgresql entry.
    assert not any(e["store"] == "postgresql" for e in _direct_callers()["cortex-ui"])
    assert not on._selecting(on.pod("iagent-cortex-ui"), "Egress")
    v = on.evaluate(ne.Flow("iagent-cortex-ui", "iagent-postgresql", 5432))
    assert not v.allowed and "ingress of iagent-postgresql" in v.reason, v
    assert on.evaluate(ne.Flow(BFF, "iagent-postgresql", 5432)).allowed  # the listed twin


def test_CONTROL_AN_UNLISTED_OFF_CLUSTER_ADDRESS_IS_DENIED(on):
    assert not on.evaluate(ne.Flow(ENGINE_O, "192.0.2.99", 11434)).allowed
    assert not on.evaluate(ne.Flow(ENGINE_O, "192.0.2.10", 8080)).allowed  # right host, wrong port
    assert on.evaluate(ne.Flow(ENGINE_O, "192.0.2.10", 11434)).allowed


def test_CONTROL_WITH_THE_GATE_OFF_EVERYTHING_IS_ALLOWED(off):
    assert not off.policies
    for src in (BFF, ENGINE_O):
        assert not _cut(off, src)
    assert off.evaluate(ne.Flow(ENGINE_O, "iagent-dag-tools-broker", 8000)).allowed


def test_CONTROL_THE_NAMED_TARGET_PORT_IS_RESOLVED_NOT_THE_SERVICE_PORT(on):
    # weaviate-grpc: Service port 50051 -> targetPort `grpc` (a name) -> containerPort 50051
    svc = on.service_for_host("iagent-weaviate-grpc")
    assert on.resolve_target_port(svc, 50051, on.backends(svc)) == 50051
    assert on.resolve_target_port(svc, 9999, on.backends(svc)) is None


# ---------------------------------------------------------------------------------------------
# d. the population is the recorded one
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("src", [BFF, ENGINE_O])
def test_THE_DERIVED_DESTINATION_SET_IS_THE_RECORDED_SET(on, src):
    got = {(_short(f.host), f.port) for f in ne.derive_flows(on, src)}
    assert got == EXPECTED[src], (
        f"derivation drifted for {src}: gained {sorted(got - EXPECTED[src])}, "
        f"lost {sorted(EXPECTED[src] - got)}"
    )
    assert len(_live_flows(on, src)) >= 30


# ---------------------------------------------------------------------------------------------
# e. the exclusion list cannot go stale silently
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("src", [BFF, ENGINE_O])
def test_EVERY_EXCLUDED_KEY_STILL_EXISTS_AND_MEANS_WHAT_ITS_REASON_SAYS(on, src):
    env = on.env_of(src)
    for key, (kind, reason) in EXCLUDED.items():
        assert key in env, f"excluded key {key} ({reason}) is gone from {src}'s env: delete the exclusion"
        host, _port = ne.parse_destination(env[key])
        if kind == "unrendered":
            assert on.service_for_host(host) is None, f"{key}: {host} IS a Service now; evaluate it"
        elif kind == "public":
            assert "." in host and not host.endswith(".local") and on.service_for_host(host) is None


def test_EVERY_EXTERNAL_HOST_IS_REALLY_NOT_A_SERVICE_AND_IS_REFERENCED(on):
    for host in EXTERNAL_HOSTS:
        assert on.service_for_host(host) is None, f"{host} became a Service: name it by podSelector instead"
        assert host in {_short(f.host) for f in ne.derive_flows(on, ENGINE_O)}, f"{host} no longer referenced"
