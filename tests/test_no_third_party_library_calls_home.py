"""No pod's libraries call the public internet on their own account.

Two libraries do by default, from every engine that imports them:
- mem0 sends usage events to its vendor's analytics service (`MEM0_TELEMETRY`, default on);
- LiteLLM fetches its model cost map from GitHub at import. With no route out, it waits for the
  handshake to time out, then uses the copy it ships with (`LITELLM_LOCAL_MODEL_COST_MAP`).

The chart's release ConfigMap turns both off for every workload that loads it. These seals render
the chart, then let each library read the rendered value and make its own decision: the rule
for what counts as "off" is the library's, never restated here.

Run: uv run pytest tests/test_no_third_party_library_calls_home.py -q
"""
from __future__ import annotations

import json
import os
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
_NAMESPACE = "sandbox"
_RELEASE = "iagent"
_KEYS = ("MEM0_TELEMETRY", "LITELLM_LOCAL_MODEL_COST_MAP")

needs_helm = pytest.mark.skipif(
    shutil.which("helm") is None,
    reason="the `helm` binary is not on PATH: a declared condition, not a probe of any cluster",
)


@pytest.fixture(scope="module")
def cluster() -> ne.Cluster:
    cmd = ["helm", "template", _RELEASE, str(_CHART), "--namespace", _NAMESPACE, "-f", str(_SANDBOX)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"helm template failed: {proc.stderr[-2000:]}"
    docs = [d for d in yaml.safe_load_all(proc.stdout) if isinstance(d, dict)]
    return ne.Cluster(docs, namespace=_NAMESPACE)


def _loads_release_config(cluster: ne.Cluster, workload: str) -> bool:
    d = cluster.workload_docs[workload]
    return any((ef.get("configMapRef") or {}).get("name") == f"{_RELEASE}-config"
               for c in d["spec"]["template"]["spec"].get("containers", [])
               for ef in c.get("envFrom") or [])


def _library_decision(code: str, env_over: dict[str, str], tmp_path: Path) -> dict:
    """Run `code` in a fresh interpreter with the given env (both keys cleared first)."""
    env = {k: v for k, v in os.environ.items() if k not in _KEYS}
    env.update({"MEM0_DIR": str(tmp_path / "mem0"), **env_over})
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=180, env=env, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


_MEM0 = ("import json; from mem0.memory import telemetry as t; "
         "print(json.dumps({'on': t.MEM0_TELEMETRY, 'client': t.client_telemetry.posthog is not None}))")
_LITELLM = ("import json, litellm; "
            "from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map_source_info; "
            "print(json.dumps(get_model_cost_map_source_info()))")


@needs_helm
def test_EVERY_WORKLOAD_THAT_LOADS_THE_RELEASE_CONFIG_CARRIES_BOTH_SWITCHES(cluster):
    loaders = [p.name for p in cluster.pods if _loads_release_config(cluster, p.name)]
    assert len(loaders) >= 10, f"too few workloads load the release config: {loaders}"
    missing = {w: [k for k in _KEYS if k not in cluster.env_of(w)] for w in loaders}
    assert {w: m for w, m in missing.items() if m} == {}


@needs_helm
def test_MEM0_READS_THE_RENDERED_VALUE_AS_OFF_AND_BUILDS_NO_ANALYTICS_CLIENT(cluster, tmp_path):
    pytest.importorskip("mem0")
    w = next(p.name for p in cluster.pods if _loads_release_config(cluster, p.name))
    got = _library_decision(_MEM0, {"MEM0_TELEMETRY": cluster.env_of(w)["MEM0_TELEMETRY"]}, tmp_path)
    assert got == {"on": False, "client": False}


@needs_helm
def test_LITELLM_READS_THE_RENDERED_VALUE_AS_USE_THE_LOCAL_MAP(cluster, tmp_path):
    pytest.importorskip("litellm")
    w = next(p.name for p in cluster.pods if _loads_release_config(cluster, p.name))
    value = cluster.env_of(w)["LITELLM_LOCAL_MODEL_COST_MAP"]
    got = _library_decision(_LITELLM, {"LITELLM_LOCAL_MODEL_COST_MAP": value}, tmp_path)
    assert got["source"] == "local" and got["is_env_forced"] is True, got


def test_CONTROL_UNSET_EACH_LIBRARY_CALLS_HOME(tmp_path):
    """Shares the subject's interpreter and probe, and differs only in the env: unset, mem0 builds
    its analytics client and LiteLLM tries the remote map. The proxy points at a closed local
    port, so the control itself reaches nothing; LiteLLM falls back without being forced."""
    pytest.importorskip("mem0")
    pytest.importorskip("litellm")
    closed = "http://127.0.0.1:9"
    no_route = {"HTTPS_PROXY": closed, "HTTP_PROXY": closed, "https_proxy": closed, "http_proxy": closed}
    assert _library_decision(_MEM0, no_route, tmp_path) == {"on": True, "client": True}
    got = _library_decision(_LITELLM, no_route, tmp_path)
    assert got["is_env_forced"] is False, got
