"""No pod's libraries call the public internet on their own account.

Four libraries do by default, from every engine that imports them:
- mem0 sends usage events to its vendor's analytics service (`MEM0_TELEMETRY`, default on);
- acryl-datahub uploads a usage event to its vendor's analytics service (`DATAHUB_TELEMETRY_ENABLED`,
  default on, and off on its own under a CI variable);
- huggingface_hub pings its hub and adds installed-framework versions to its user agent
  (`HF_HUB_DISABLE_TELEMETRY`, default on);
- LiteLLM fetches its model cost map from GitHub at import. With no route out, it waits for the
  handshake to time out, then uses the copy it ships with (`LITELLM_LOCAL_MODEL_COST_MAP`).

The chart's release ConfigMap turns all four off for every workload that loads it. These seals render
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
_KEYS = ("MEM0_TELEMETRY", "LITELLM_LOCAL_MODEL_COST_MAP", "DATAHUB_TELEMETRY_ENABLED",
         "HF_HUB_DISABLE_TELEMETRY")
# Cleared before every probe so the control behaves the same locally and in CI. acryl-datahub turns
# itself off when ANY of its `CI_ENV_VARS` is in the environment (datahub/telemetry/telemetry.py: the
# set of that name and the `any(var in os.environ ...)` test below it); that list is copied here. For
# huggingface_hub: `HF_HUB_DISABLE_TELEMETRY` is also true under `DISABLE_TELEMETRY` or `DO_NOT_TRACK`
# (huggingface_hub/constants.py), and telemetry is skipped when offline (`HF_HUB_OFFLINE`,
# `TRANSFORMERS_OFFLINE`).
_CI_STYLE = (
    "APPCENTER", "APPCIRCLE", "APPCIRCLEAZURE_PIPELINES", "APPVEYOR", "AZURE_PIPELINES", "BAMBOO",
    "BITBUCKET", "BITRISE", "BUDDY", "BUILDKITE", "BUILD_ID", "CI", "CIRCLE", "CIRCLECI", "CIRRUS",
    "CIRRUS_CI", "CI_NAME", "CODEBUILD", "CODEBUILD_BUILD_ID", "CODEFRESH", "CODESHIP", "CYPRESS_HOST",
    "DRONE", "DSARI", "EAS_BUILD", "GITHUB_ACTIONS", "GITLAB", "GITLAB_CI", "GOCD", "HEROKU_TEST_RUN_ID",
    "HUDSON", "JENKINS", "JENKINS_URL", "LAYERCI", "MAGNUM", "NETLIFY", "NEVERCODE", "RENDER", "SAIL",
    "SCREWDRIVER", "SEMAPHORE", "SHIPPABLE", "SOLANO", "STRIDER", "TASKCLUSTER", "TEAMCITY",
    "TEAMCITY_VERSION", "TF_BUILD", "TRAVIS", "VERCEL", "WERCKER_ROOT", "bamboo.buildKey",
    "DISABLE_TELEMETRY", "DO_NOT_TRACK", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
)
_CLEARED = frozenset(_KEYS) | frozenset(_CI_STYLE)

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
    """Run `code` in a fresh interpreter with the given env (every name in `_CLEARED` cleared first;
    HOME points into tmp_path so DataHub's client-id file never touches the real home)."""
    env = {k: v for k, v in os.environ.items() if k not in _CLEARED}
    home = str(tmp_path / "home")
    env.update({"MEM0_DIR": str(tmp_path / "mem0"), "HOME": home, "USERPROFILE": home, **env_over})
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
def test_EVERY_WORKLOAD_THAT_LOADS_THE_RELEASE_CONFIG_CARRIES_ALL_FOUR_SWITCHES(cluster):
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


# The upload itself, at the wire. Every HTTP request PostHog's client makes goes through
# `requests.Session.send`; the probe replaces it with a recorder that answers 200 and sends nothing.
# mem0 then records the event it sends when a Memory starts (`mem0.init`) and flushes its clients the
# way it does at exit. The hosts the probe saw are the uploads mem0 attempted.
_MEM0_UPLOAD = r"""
import json, types, requests
from urllib.parse import urlparse
seen = []
def _send(self, req, **kw):
    seen.append(urlparse(req.url).netloc)
    r = requests.Response(); r.status_code = 200; r._content = b"{}"; r.url = req.url; r.request = req
    return r
requests.Session.send = _send
from mem0.memory import telemetry as t
ns = types.SimpleNamespace
memory = ns(collection_name="mem0", api_version="v1.1", vector_store=object(), llm=object(),
            embedding_model=ns(config=ns(embedding_dims=3)))
t.capture_event("mem0.init", memory, {"sync_type": "sync"})
t._shutdown_oss_telemetry()
t.client_telemetry.close()
print(json.dumps({"hosts": sorted(set(seen)), "analytics_host": urlparse(t.HOST).netloc}))
"""


@needs_helm
def test_WITH_THE_RENDERED_SETTING_MEM0_ATTEMPTS_NO_UPLOAD(cluster, tmp_path):
    """The deployment log showed engines attempting an upload to mem0's analytics service. With the
    value the chart renders, mem0 makes no HTTP request at all: not to its analytics host, not anywhere."""
    pytest.importorskip("mem0")
    w = next(p.name for p in cluster.pods if _loads_release_config(cluster, p.name))
    got = _library_decision(_MEM0_UPLOAD, {"MEM0_TELEMETRY": cluster.env_of(w)["MEM0_TELEMETRY"]}, tmp_path)
    assert got["hosts"] == [], got


def test_CONTROL_WITHOUT_THE_SETTING_MEM0_UPLOADS_TO_ITS_ANALYTICS_HOST(tmp_path):
    """The same probe with the setting absent (mem0's default): the upload reaches the wire, to the
    analytics host mem0 itself names. So the subject above is not passing because the probe is deaf."""
    pytest.importorskip("mem0")
    got = _library_decision(_MEM0_UPLOAD, {}, tmp_path)
    assert got["analytics_host"] in got["hosts"], got


# acryl-datahub: `ping` hands the event to a mixpanel Consumer, which POSTs through
# `requests.Session`. The probe replaces `Session.send` with a recorder that answers mixpanel's
# success body and sends nothing. The telemetry client is built at import, so the env decides there.
_DATAHUB_UPLOAD = r"""
import json, requests
from urllib.parse import urlparse
seen = []
def _send(self, req, **kw):
    seen.append(urlparse(req.url).netloc)
    r = requests.Response(); r.status_code = 200; r._content = b'{"status": 1}'; r.url = req.url; r.request = req
    return r
requests.Session.send = _send
from datahub.telemetry import telemetry as t
t.telemetry_instance.ping("probe-event", {"k": "v"})
print(json.dumps({"hosts": sorted(set(seen)), "analytics_host": t.MIXPANEL_ENDPOINT.split("/")[0]}))
"""


@needs_helm
def test_WITH_THE_RENDERED_SETTING_DATAHUB_SENDS_NO_USAGE_EVENT(cluster, tmp_path):
    """With the value the chart renders, DataHub's `ping` makes no HTTP request at all."""
    pytest.importorskip("datahub")
    pytest.importorskip("mixpanel")
    w = next(p.name for p in cluster.pods if _loads_release_config(cluster, p.name))
    value = cluster.env_of(w)["DATAHUB_TELEMETRY_ENABLED"]
    got = _library_decision(_DATAHUB_UPLOAD, {"DATAHUB_TELEMETRY_ENABLED": value}, tmp_path)
    assert got["hosts"] == [], got


def test_CONTROL_WITHOUT_THE_SETTING_DATAHUB_UPLOADS_TO_ITS_ANALYTICS_HOST(tmp_path):
    """Same probe, key absent (and every CI variable cleared): the event reaches the wire, to the
    host DataHub itself names."""
    pytest.importorskip("datahub")
    pytest.importorskip("mixpanel")
    got = _library_decision(_DATAHUB_UPLOAD, {}, tmp_path)
    assert got["analytics_host"] in got["hosts"], got


# huggingface_hub: `send_telemetry` queues to a daemon thread that HEADs `<endpoint>/api/telemetry/..`
# through `requests.Session`. The probe records at `Session.send`, then waits for the queue to drain.
_HF_PING = r"""
import json, requests
from urllib.parse import urlparse
seen = []
def _send(self, req, **kw):
    seen.append(urlparse(req.url).netloc)
    r = requests.Response(); r.status_code = 200; r._content = b""; r.url = req.url; r.request = req
    return r
requests.Session.send = _send
from huggingface_hub import constants
from huggingface_hub.utils import _telemetry
_telemetry.send_telemetry("probe/topic", library_name="probe-lib", library_version="1.0")
_telemetry._TELEMETRY_QUEUE.join()
print(json.dumps({"hosts": sorted(set(seen)), "hub_host": urlparse(constants.ENDPOINT).netloc}))
"""

# The user agent the library builds. What telemetry adds to it is the versions of installed ML
# frameworks (torch, tensorflow, fastai, fastcore), which this venv does not install; the probe
# makes the library's own detection report two of them present, so the setting's effect is visible.
_HF_HEADERS = r"""
import json
from huggingface_hub.utils import _headers
_headers.is_torch_available = lambda: True
_headers.get_torch_version = lambda: "9.9.9"
_headers.is_fastai_available = lambda: True
_headers.get_fastai_version = lambda: "8.8.8"
ua = _headers.build_hf_headers(token=False, library_name="probe-lib", library_version="1.0")["user-agent"]
print(json.dumps({"ua": ua}))
"""


@needs_helm
def test_WITH_THE_RENDERED_SETTING_HF_HUB_SENDS_NO_TELEMETRY_REQUEST(cluster, tmp_path):
    pytest.importorskip("huggingface_hub")
    w = next(p.name for p in cluster.pods if _loads_release_config(cluster, p.name))
    value = cluster.env_of(w)["HF_HUB_DISABLE_TELEMETRY"]
    got = _library_decision(_HF_PING, {"HF_HUB_DISABLE_TELEMETRY": value}, tmp_path)
    assert got["hosts"] == [], got


def test_CONTROL_WITHOUT_THE_SETTING_HF_HUB_PINGS_ITS_HUB(tmp_path):
    pytest.importorskip("huggingface_hub")
    got = _library_decision(_HF_PING, {}, tmp_path)
    assert got["hub_host"] in got["hosts"], got


@needs_helm
def test_WITH_THE_RENDERED_SETTING_HF_HUB_HEADERS_CARRY_NO_USAGE_FIELDS(cluster, tmp_path):
    pytest.importorskip("huggingface_hub")
    w = next(p.name for p in cluster.pods if _loads_release_config(cluster, p.name))
    value = cluster.env_of(w)["HF_HUB_DISABLE_TELEMETRY"]
    got = _library_decision(_HF_HEADERS, {"HF_HUB_DISABLE_TELEMETRY": value}, tmp_path)
    assert "torch/" not in got["ua"] and "fastai/" not in got["ua"], got


def test_CONTROL_WITHOUT_THE_SETTING_HF_HUB_HEADERS_CARRY_USAGE_FIELDS(tmp_path):
    pytest.importorskip("huggingface_hub")
    got = _library_decision(_HF_HEADERS, {}, tmp_path)
    assert "torch/9.9.9" in got["ua"] and "fastai/8.8.8" in got["ua"], got
