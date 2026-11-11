"""The sandbox serves LANGFUSE_TRACING_ENVIRONMENT, equal to DEPLOY_ENV, to every pod that emits spans.

provenance-telemetry 0.2.0 stamps a boundary span from DEPLOY_ENV and the Langfuse SDK stamps every
child from LANGFUSE_TRACING_ENVIRONMENT; unset, the children land in "default". From 0.2.1 the boundary
reads the SDK's setting too. The architect (2026-11-10): "set per deployment in helm values (sandbox:
"sandbox")". The pods that emit spans are the engines that pin the leaf (derived from their pyprojects,
mapped to images by the build matrix) and cortex-bff.

Run: uv run --frozen python -m pytest tests/perf/test_the_sandbox_tags_spans_with_its_environment_chart.py -v
"""
from __future__ import annotations

import shutil

import pytest
import yaml

from tests.test_oidc_broker_chart import _BROKER_OFF, _CHART, _REPO, _SANDBOX, _docs, _render, _set

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_KEY = "LANGFUSE_TRACING_ENVIRONMENT"
_CONFIG = "t-config"
_SB = yaml.safe_load(open(_SANDBOX[1], encoding="utf-8"))
_LEAF = "provenance-telemetry"


def _leaf_images() -> set[str]:
    """Image names of the engines whose pyproject pins the leaf, via the build matrix's path -> service."""
    dirs = {p.parent.as_posix().removeprefix(_REPO.as_posix() + "/")
            for p in (_REPO / "agent_fleet").glob("*/pyproject.toml") if _LEAF in p.read_text(encoding="utf-8")}
    wf = yaml.safe_load(open(_REPO / ".github/workflows/build-containers.yml", encoding="utf-8"))
    rows = [r for job in wf["jobs"].values() for r in (job.get("strategy", {}).get("matrix", {}).get("include") or [])]
    by_path = {r["path"]: r["service"] for r in rows if "path" in r and "service" in r}
    assert dirs and dirs <= set(by_path), f"leaf engines missing from the build matrix: {sorted(dirs - set(by_path))}"
    return {by_path[d] for d in dirs}


def _config(rendered: str) -> dict:
    found = [d for d in _docs(rendered) if d["kind"] == "ConfigMap" and d["metadata"]["name"] == _CONFIG]
    assert len(found) == 1, f"expected one {_CONFIG} ConfigMap, found {len(found)}"
    return found[0]["data"]


def _emitters(rendered: str) -> dict[str, dict]:
    """component -> its first container, for cortex-bff and every Deployment running a leaf image."""
    images = _leaf_images()
    out: dict[str, dict] = {}
    for d in _docs(rendered):
        if d["kind"] != "Deployment":
            continue
        comp = d["metadata"]["labels"]["app.kubernetes.io/component"]
        c = d["spec"]["template"]["spec"]["containers"][0]
        name = c["image"].rsplit("/", 1)[-1].split("@")[0].split(":")[0]
        if comp == "cortex-bff" or name in images:
            out[comp] = c
    return out


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_SANDBOX, *_BROKER_OFF)


def test_the_sandbox_sets_the_key_equal_to_deploy_env(sandbox):
    deploy_env = _SB["agentFleet"]["env"]["DEPLOY_ENV"]
    assert deploy_env, "values-sandbox.yaml sets no DEPLOY_ENV"
    assert _config(sandbox).get(_KEY) == deploy_env


def test_control_a_different_value_is_what_the_config_carries():
    """The equality above reads the render: a sandbox that diverges from DEPLOY_ENV shows up there."""
    rendered = _render(*_SANDBOX, *_BROKER_OFF, *_set(f"agentFleet.env.{_KEY}", "default"))
    assert _config(rendered)[_KEY] == "default" != _SB["agentFleet"]["env"]["DEPLOY_ENV"]


def test_every_span_emitter_mounts_the_config_and_nothing_overrides_the_key(sandbox):
    emitters = _emitters(sandbox)
    assert "cortex-bff" in emitters
    assert len(emitters) == len(_leaf_images()) + 1, f"leaf engines not rendered: {sorted(emitters)}"
    for comp, c in emitters.items():
        refs = [(e.get("configMapRef") or {}).get("name") for e in c.get("envFrom") or []]
        assert _CONFIG in refs, f"{comp} does not mount {_CONFIG}"
        assert not [e for e in c.get("env") or [] if e.get("name") == _KEY], f"{comp} overrides {_KEY}"
