"""Every engine pod is served the BFF's accepted issuers and audiences, the realm's JWKS, and the posture.

The SDK's transport_auth (v0.9.20+) reads MESH_JWT_ACCEPTED_ISSUERS / MESH_JWT_ACCEPTED_AUDIENCES /
MESH_JWT_JWKS_URL / REQUIRE_TRANSPORT_AUTH. The chart renders them last in each engine container's env, from
`cortexBff.auth` (one copy), so a hand-set agentFleet.env value cannot widen them.

Run: uv run --frozen python -m pytest tests/security/test_engines_are_served_the_bff_token_lists_chart.py -v
"""
from __future__ import annotations

import re
import shutil

import pytest

from tests.test_oidc_broker_chart import _BROKER_OFF, _CHART, _REPO, _SANDBOX, _docs, _render, _render_fails, _set

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_NAMES = ("MESH_JWT_ACCEPTED_ISSUERS", "MESH_JWT_ACCEPTED_AUDIENCES", "MESH_JWT_JWKS_URL")
_CERTS = "/protocol/openid-connect/certs"
_SDK_DEFAULT_EXEMPT = ("/health", "/healthz", "/livez", "/readyz")  # transport_auth.DEFAULT_EXEMPT_PATHS
_REQUIRE = _set("agentFleet.transportAuth.require", True)


def _resolve_posture(env: dict) -> str:
    """transport_auth.resolve_posture, restated: REQUIRE only for true/1/yes."""
    return "REQUIRE" if (env.get("REQUIRE_TRANSPORT_AUTH") or "").lower() in ("true", "1", "yes") else "OBSERVE"


_ENGINES_TPL = (_REPO / _CHART / "templates" / "engines.yaml").read_text(encoding="utf-8")
# DERIVED from the template, never typed: every (key, component) the engines range lists, plus the registrar.
_KEYS = re.findall(r'\(dict "key" "(\w+)" "component" "([\w-]+)"', _ENGINES_TPL)
_OWNER = {"username": "registrar-owner", "email": "registrar-owner@example.invalid"}
_ALL_ON = [*(a for k, _ in _KEYS for a in _set(f"{k}.enabled", True)), *_set("meshRegistrar.enabled", True)]
# the registrar refuses to render without a named owner; the sandbox file has one, the base values do not
_BASE_OWNER = [*_set("keycloak.nonInteractiveUsers", [_OWNER]), *_set("meshRegistrar.onBehalfOfUser", _OWNER["username"])]


def _engines(rendered: str) -> dict[str, dict]:
    """component -> {env (effective: configmap, then container env, last wins), ctr} for every engine Deployment."""
    docs = _docs(rendered)
    config = next(d["data"] for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-config")
    wanted = {f"t-{c}" for _, c in _KEYS} | {"t-mesh-registrar"}
    out: dict[str, dict] = {}
    for d in docs:
        if d["kind"] != "Deployment" or d["metadata"]["name"] not in wanted:
            continue
        (ctr,) = d["spec"]["template"]["spec"]["containers"]
        env = dict(config)
        for e in ctr.get("env", []):
            if "value" in e:
                env[e["name"]] = e["value"]
        out[d["metadata"]["name"]] = {"env": env, "ctr": ctr}
    return out


def _bff_env(rendered: str) -> dict:
    (dep,) = [d for d in _docs(rendered) if d["kind"] == "Deployment" and d["metadata"]["name"].endswith("cortex-bff")]
    (ctr,) = [c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "cortex-bff"]
    return {e["name"]: e["value"] for e in ctr["env"] if "value" in e}


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_SANDBOX, *_BROKER_OFF, *_ALL_ON)


@pytest.fixture(scope="module")
def base() -> str:
    return _render(*_BROKER_OFF, *_ALL_ON, *_BASE_OWNER)


def _served(rendered: str) -> dict[str, dict]:
    eng = _engines(rendered)
    served = {n: e for n, e in eng.items() if "MESH_JWT_JWKS_URL" in e["env"]}
    assert set(served) == {f"t-{c}" for _, c in _KEYS} | {"t-mesh-registrar"}, sorted(set(eng) ^ set(served))
    assert len(served) >= 16, f"derived only {len(served)} engines: {sorted(served)}"
    assert any(n.endswith("mesh-registrar") for n in served), "mesh-registrar is not among the derived engines"
    return served


def test_the_sandbox_serves_every_engine_the_bffs_lists_and_the_realm_jwks(sandbox):
    bff = _bff_env(sandbox)
    # control: the BFF's lists are non-empty, so equality below is not vacuous
    assert bff["BFF_JWT_ACCEPTED_ISSUERS"] and bff["BFF_JWT_ACCEPTED_AUDIENCES"]
    for name, e in _served(sandbox).items():
        env = e["env"]
        assert env["MESH_JWT_ACCEPTED_ISSUERS"] == bff["BFF_JWT_ACCEPTED_ISSUERS"], name
        assert env["MESH_JWT_ACCEPTED_AUDIENCES"] == bff["BFF_JWT_ACCEPTED_AUDIENCES"], name
        assert env["KEYCLOAK_REALM_URL"], name
        assert env["MESH_JWT_JWKS_URL"] == env["KEYCLOAK_REALM_URL"].rstrip("/") + _CERTS, name


def test_base_values_serve_both_lists_present_and_empty(base):
    for name, e in _served(base).items():
        assert e["env"]["MESH_JWT_ACCEPTED_ISSUERS"] == "", name
        assert e["env"]["MESH_JWT_ACCEPTED_AUDIENCES"] == "", name


def test_a_hand_set_env_cannot_widen_the_lists(sandbox):
    bff = _bff_env(sandbox)
    # control: without the override the render succeeds (the sandbox fixture) and serves the BFF's list
    widened = _render(*_SANDBOX, *_BROKER_OFF, *_ALL_ON, *_set("agentFleet.env.MESH_JWT_ACCEPTED_AUDIENCES", "anything"),
                      *_set("engineO.env.MESH_JWT_ACCEPTED_ISSUERS", "https://evil.example"))
    for name, e in _served(widened).items():
        assert e["env"]["MESH_JWT_ACCEPTED_AUDIENCES"] == bff["BFF_JWT_ACCEPTED_AUDIENCES"], name
        assert e["env"]["MESH_JWT_ACCEPTED_ISSUERS"] == bff["BFF_JWT_ACCEPTED_ISSUERS"], name
        assert "anything" not in e["env"]["MESH_JWT_ACCEPTED_AUDIENCES"], name


def test_the_posture_follows_the_switch_and_nothing_else(sandbox):
    on = _render(*_SANDBOX, *_BROKER_OFF, *_ALL_ON, *_REQUIRE)
    off, on_eng = _served(sandbox), _served(on)
    assert set(off) == set(on_eng)
    for name in off:
        assert _resolve_posture(off[name]["env"]) == "OBSERVE", name
        assert _resolve_posture(on_eng[name]["env"]) == "REQUIRE", name
        a = {k: v for k, v in off[name]["env"].items() if k != "REQUIRE_TRANSPORT_AUTH"}
        b = {k: v for k, v in on_eng[name]["env"].items() if k != "REQUIRE_TRANSPORT_AUTH"}
        assert a == b, name  # control: the two renders differ only in the posture


def test_under_require_every_probe_path_is_exempt():
    on = _render(*_SANDBOX, *_BROKER_OFF, *_ALL_ON, *_REQUIRE)
    seen = 0
    for name, e in _served(on).items():
        raw = e["env"].get("TRANSPORT_AUTH_EXEMPT_PATHS")
        exempt = _SDK_DEFAULT_EXEMPT if raw is None else tuple(p.strip() for p in raw.split(",") if p.strip())
        for probe in ("readinessProbe", "livenessProbe"):
            http = e["ctr"].get(probe, {}).get("httpGet")
            if http:  # a tcpSocket probe sends no request
                seen += 1
                assert http["path"] in exempt, f"{name} {probe} {http['path']} is not exempt: {exempt}"
    assert seen >= 16, "control: too few HTTP probes were checked"
