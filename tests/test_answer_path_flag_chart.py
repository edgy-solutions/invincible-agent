"""The BFF's answer path is a chart key, refused when mistyped or when durable has no supervisor.

Ruled 2026-11-24 (architect, ADR-0072 section 4): `cortexBff.answerPath`, unset by default; any value
other than "dagster" / "durable" refuses; "durable" refuses unless `supervisorService.enabled`.
Renders stay in memory: nothing is written to disk or printed.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parent.parent
_CHART = _REPO / "helm" / "invincible-agent"
_VAR = "IAGENT_ANSWER_PATH"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_SUP = ["--set", "supervisorService.enabled=true", "--set", "supervisorService.queueMax=4"]


def _helm(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["helm", "template", "t", str(_CHART), *args],
                          capture_output=True, text=True, encoding="utf-8", timeout=300)


def _render(*args: str) -> list[dict]:
    r = _helm(*args)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-1500:]}"
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    assert docs, "helm rendered nothing and reported success"
    return docs


def _fails(*args: str) -> str:
    r = _helm(*args)
    assert r.returncode != 0, "expected the render to FAIL, but it succeeded"
    return r.stderr


def _env(dep: dict) -> dict:
    out = {}
    for c in dep["spec"]["template"]["spec"].get("containers", []):
        for e in c.get("env") or []:
            if e["name"] == _VAR:
                out.setdefault(c["name"], []).append(e.get("value"))
    return out


def _deployments(docs):
    return [d for d in docs if d["kind"] == "Deployment"]


def _bff(docs) -> dict:
    found = [d for d in _deployments(docs) if d["metadata"]["name"].endswith("-cortex-bff")]
    assert len(found) == 1
    return found[0]


def _in_configmaps(docs) -> bool:
    return any(_VAR in (d.get("data") or {}) for d in docs if d["kind"] == "ConfigMap")


def test_default_renders_no_answer_path_anywhere():
    docs = _render()
    assert _bff(docs)
    assert all(not _env(d) for d in _deployments(docs))
    assert not _in_configmaps(docs)


def test_dagster_lands_on_the_bff_only():
    docs = _render("--set", "cortexBff.answerPath=dagster")
    bff = _bff(docs)
    assert list(_env(bff).values()) == [["dagster"]]
    assert all(not _env(d) for d in _deployments(docs) if d is not bff)
    assert not _in_configmaps(docs)


def test_durable_with_the_supervisor_renders():
    docs = _render("--set", "cortexBff.answerPath=durable", *_SUP)
    assert list(_env(_bff(docs)).values()) == [["durable"]]


def test_durable_without_the_supervisor_refuses():
    assert "supervisorService.enabled" in _fails("--set", "cortexBff.answerPath=durable")


@pytest.mark.parametrize("bad", ["Durable", "durabel"])
def test_a_bad_value_refuses(bad):
    assert "cortexBff.answerPath" in _fails("--set", f"cortexBff.answerPath={bad}", *_SUP)


@pytest.mark.parametrize("key", ["cortexBff.env", "agentFleet.env"])
def test_the_flag_in_an_env_map_refuses(key):
    err = _fails("--set", f"{key}.{_VAR}=durable", *_SUP)
    assert "cortexBff.answerPath" in err
