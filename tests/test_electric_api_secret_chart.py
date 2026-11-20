"""The Electric API secret: by reference only, one Secret for both halves, and insecure mode off by default.

Three seals (gov's checks, PR 1 of the sync-service exposure fixes):

1. `ELECTRIC_SECRET` (Electric) and `ELECTRIC_SHAPE_SECRET` (the BFF) are `secretKeyRef`s in every
   rendered pod, never a `value:` literal.
2. Both reference the SAME Secret and key, and that Secret is rendered by the chart.
3. `electric.insecure` defaults false in values.yaml (read from the file), a bare render gives
   `ELECTRIC_INSECURE=false`, and values-sandbox.yaml does not override it back to true.

Every census has a positive control (the env exists) so an absence cannot pass on an empty render.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_SECRET_ENVS = ("ELECTRIC_SECRET", "ELECTRIC_SHAPE_SECRET")

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _render(*extra: str) -> list[dict]:
    r = subprocess.run(["helm", "template", "r", str(_CHART), *extra], capture_output=True,
                       text=True, cwd=str(_REPO), timeout=300)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _containers(doc: dict):
    spec = (doc.get("spec") or {})
    pod = (spec.get("template") or {}).get("spec") or {}
    for c in list(pod.get("containers") or []) + list(pod.get("initContainers") or []):
        yield c


def _secret_envs(docs: list[dict]) -> list[tuple[str, str, dict]]:
    """(workload name, env name, env entry) for every ELECTRIC secret env in every rendered pod."""
    out = []
    for d in docs:
        for c in _containers(d):
            for e in c.get("env") or []:
                if e.get("name") in _SECRET_ENVS:
                    out.append((d["metadata"]["name"], e["name"], e))
    return out


def _literals(docs: list[dict]) -> list[tuple[str, str]]:
    """The census: every secret env that carries a literal value or lacks a secretKeyRef."""
    return [(w, n) for w, n, e in _secret_envs(docs)
            if "value" in e or not (e.get("valueFrom") or {}).get("secretKeyRef")]


def _refs(docs: list[dict]) -> dict[str, tuple[str, str]]:
    return {n: (e["valueFrom"]["secretKeyRef"]["name"], e["valueFrom"]["secretKeyRef"]["key"])
            for _, n, e in _secret_envs(docs)}


# -- 1. by reference only -----------------------------------------------------------------------

def test_control_both_secret_envs_are_rendered():
    envs = {n for _, n, _ in _secret_envs(_render())}
    assert envs == set(_SECRET_ENVS)


def test_no_rendered_pod_carries_an_electric_secret_as_a_literal():
    docs = _render()
    assert _secret_envs(docs), "vacuous: no secret env rendered"
    assert _literals(docs) == []


def test_the_census_sees_a_literal():
    # the seal's own mutant, in memory: a pod that carries the secret as a value is reported
    doc = {"metadata": {"name": "x"}, "spec": {"template": {"spec": {"containers": [
        {"env": [{"name": "ELECTRIC_SECRET", "value": "abc"}]}]}}}}
    assert _literals([doc]) == [("x", "ELECTRIC_SECRET")]


# -- 2. one Secret for both halves ----------------------------------------------------------------

def test_the_server_and_the_bff_name_the_same_secret_and_key_and_the_chart_renders_it():
    docs = _render()
    refs = _refs(docs)
    assert refs["ELECTRIC_SECRET"] == refs["ELECTRIC_SHAPE_SECRET"]
    name, key = refs["ELECTRIC_SECRET"]
    secrets = [d for d in docs if d.get("kind") == "Secret" and d["metadata"]["name"] == name]
    assert len(secrets) == 1
    assert key in secrets[0]["data"] and secrets[0]["data"][key]
    assert "stringData" not in secrets[0]


def test_a_named_premade_secret_is_referenced_and_not_rendered():
    docs = _render("--set", "electric.apiSecret.name=premade", "--set", "electric.apiSecret.key=k")
    assert set(_refs(docs).values()) == {("premade", "k")}
    assert not [d for d in docs if d.get("kind") == "Secret" and d["metadata"]["name"] == "premade"]


# -- 3. insecure mode cannot come back through a default ------------------------------------------

def _electric_insecure(docs: list[dict]) -> list[str]:
    return [e["value"] for d in docs for c in _containers(d) for e in c.get("env") or []
            if e.get("name") == "ELECTRIC_INSECURE"]


def test_values_default_is_false_and_a_bare_render_follows_it():
    default = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))["electric"]["insecure"]
    assert default is False
    rendered = _electric_insecure(_render())
    assert rendered == [str(default).lower()]          # derived from the artifact's value


def test_the_sandbox_overlay_does_not_turn_insecure_back_on():
    sandbox = yaml.safe_load((_CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
    assert (sandbox.get("electric") or {}).get("insecure") is not True
    assert _electric_insecure(_render("-f", str(_CHART / "values-sandbox.yaml"))) == ["false"]


def test_with_a_premade_secret_named_the_chart_renders_no_electric_api_secret_at_all():
    # a GitOps/`helm template` deploy names its own Secret; the chart must then render NO Secret for it
    # (neither the named one nor the generated `<release>-electric-api`): the Secret set is the default set
    # minus the generated one, exactly.
    def secrets(*extra):
        return {d["metadata"]["name"] for d in _render(*extra) if d.get("kind") == "Secret"}
    default = secrets()
    assert "r-electric-api" in default                       # control: it is rendered without a name
    assert secrets("--set", "electric.apiSecret.name=premade") == default - {"r-electric-api"}


# -- Electric must not log the secret ----------------------------------------------------------------
# Electric 1.0.13 takes the secret only as a query param and logs the query string at `info`
# (serve_shape_plug.ex:27); its log level defaults to info. The chart sets ELECTRIC_LOG_LEVEL from values.

def _electric_log_levels(docs: list[dict]) -> list[str]:
    return [e["value"] for d in docs for c in _containers(d) for e in c.get("env") or []
            if e.get("name") == "ELECTRIC_LOG_LEVEL"]


def test_electric_logs_below_the_level_that_prints_the_query_string():
    default = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))["electric"]["logLevel"]
    assert default not in ("info", "debug")
    levels = _electric_log_levels(_render())
    assert levels == [default]                                      # present, derived from the artifact
    assert levels[0] not in ("info", "debug")
    sandbox = yaml.safe_load((_CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
    assert (sandbox.get("electric") or {}).get("logLevel") not in ("info", "debug")
    assert _electric_log_levels(_render("-f", str(_CHART / "values-sandbox.yaml"))) == [default]


def test_the_generated_secret_is_kept_when_the_release_forgets_it():
    docs = _render()
    (name, _key) = _refs(docs)["ELECTRIC_SECRET"]
    (secret,) = [d for d in docs if d.get("kind") == "Secret" and d["metadata"]["name"] == name]
    assert secret["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
