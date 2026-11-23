"""The central gateway accepts exactly the BFF's issuers and audiences, and the sandbox enforces.

dag-tools v0.14.0 reads GATEWAY_JWT_ISSUERS then GATEWAY_JWT_ISSUER (and the same for audiences), comma-split
and de-duplicated, and an empty list refuses everything. The chart renders the plurals last in the gateway
container's env from `cortexBff.auth` (the BFF's one copy) and refuses a hand-set name that would widen them.
The verdicts below are dag-tools' OWN readers (`accepted_issuers`, `accepted_audiences`, `announce`) run over
the rendered env, so the restatement cannot drift from the code. The architect (2026-11-11): serve the lists
matching the BFF's, sandbox to enforce in the same roll, post-roll `announce()` reads enforce_ready=yes.

Run: uv run --frozen python -m pytest tests/security/test_the_gateway_is_served_the_bff_token_lists_chart.py -v
"""
from __future__ import annotations

import shutil

import pytest

identity = pytest.importorskip("dag_tools.central_gateway.identity")

from tests.test_oidc_broker_chart import _BROKER_OFF, _SANDBOX, _docs, _render, _render_fails, _set  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_OWNER = {"username": "registrar-owner", "email": "registrar-owner@example.invalid"}
_BASE_OWNER = [*_set("keycloak.nonInteractiveUsers", [_OWNER]), *_set("meshRegistrar.onBehalfOfUser", _OWNER["username"])]
_READ = (*identity.ISSUERS_ENV, *identity.AUDIENCES_ENV, *identity.KEY_ENV, "GATEWAY_IDENTITY_POSTURE")


def _gateway_env(rendered: str) -> dict:
    """The gateway container's effective env: the configmap (envFrom), then the container env, last wins."""
    docs = _docs(rendered)
    env = dict(next(d["data"] for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-config"))
    (dep,) = [d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-central-gateway"]
    (ctr,) = dep["spec"]["template"]["spec"]["containers"]
    for e in ctr.get("env", []):
        if "value" in e:
            env[e["name"]] = e["value"]
    return env


def _bff_env(rendered: str) -> dict:
    (dep,) = [d for d in _docs(rendered) if d["kind"] == "Deployment" and d["metadata"]["name"].endswith("cortex-bff")]
    (ctr,) = [c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "cortex-bff"]
    return {e["name"]: e["value"] for e in ctr["env"] if "value" in e}


def _as_gateway(env: dict, monkeypatch, fn):
    """Run one of dag-tools' readers with exactly the names it reads taken from `env`."""
    for name in _READ:
        monkeypatch.delenv(name, raising=False)
        if name in env:
            monkeypatch.setenv(name, env[name])
    return fn()


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_SANDBOX, *_BROKER_OFF)


def test_the_sandbox_gateway_accepts_exactly_the_bffs_lists(sandbox, monkeypatch):
    bff, gw = _bff_env(sandbox), _gateway_env(sandbox)
    # control: the BFF's lists are non-empty, so the equality is not vacuous
    assert bff["BFF_JWT_ACCEPTED_ISSUERS"] and bff["BFF_JWT_ACCEPTED_AUDIENCES"]
    assert _as_gateway(gw, monkeypatch, identity.accepted_issuers) == bff["BFF_JWT_ACCEPTED_ISSUERS"].split(",")
    assert _as_gateway(gw, monkeypatch, identity.accepted_audiences) == bff["BFF_JWT_ACCEPTED_AUDIENCES"].split(",")


def test_the_sandbox_gateway_enforces_and_is_ready_to(sandbox, monkeypatch):
    line = _as_gateway(_gateway_env(sandbox), monkeypatch, identity.announce)
    assert "posture=enforce " in line and "enforce_ready=yes" in line and "unset=" not in line, line


def test_control_without_the_lists_enforce_would_not_be_ready(sandbox, monkeypatch):
    """The readiness above comes from the plurals: drop them and dag-tools names what is unset."""
    gw = {k: v for k, v in _gateway_env(sandbox).items() if k not in ("GATEWAY_JWT_ISSUERS", "GATEWAY_JWT_AUDIENCES")}
    line = _as_gateway(gw, monkeypatch, identity.announce)
    assert "enforce_ready=no" in line and "GATEWAY_JWT_AUDIENCES" in line, line


def test_the_gateway_follows_the_bffs_audiences(monkeypatch):
    rendered = _render(*_SANDBOX, *_BROKER_OFF, *_set("cortexBff.auth.acceptedAudiences", ["cortex-bff", "other-aud"]))
    assert _as_gateway(_gateway_env(rendered), monkeypatch, identity.accepted_audiences) == ["cortex-bff", "other-aud"]


@pytest.mark.parametrize("src", ["centralGateway.env", "agentFleet.env"])
@pytest.mark.parametrize("name", ["GATEWAY_JWT_ISSUERS", "GATEWAY_JWT_AUDIENCES", "GATEWAY_JWT_AUDIENCE"])
def test_a_hand_set_list_name_is_refused(src, name):
    # control: the sandbox renders without it (the module fixture)
    err = _render_fails(*_SANDBOX, *_BROKER_OFF, *_set(f"{src}.{name}", "https://evil.example"))
    assert name in err and "widen" in err, err


def test_a_singular_issuer_the_bff_refuses_is_refused():
    err = _render_fails(*_SANDBOX, *_BROKER_OFF, *_set("agentFleet.env.GATEWAY_JWT_ISSUER", "https://evil.example"))
    assert "must be one of cortexBff.auth.acceptedIssuers" in err, err


def test_base_values_serve_empty_lists_and_stay_in_observe(monkeypatch):
    gw = _gateway_env(_render(*_BROKER_OFF, *_BASE_OWNER))
    assert gw["GATEWAY_JWT_ISSUERS"] == "" and gw["GATEWAY_JWT_AUDIENCES"] == ""
    line = _as_gateway(gw, monkeypatch, identity.announce)
    assert "posture=observe " in line and "enforce_ready=no" in line, line
