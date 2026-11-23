"""The chart serves the BFF's accepted issuers and audiences, and the realm stamps the audience.

src/iagent/auth.py `verified_claims` reads BFF_JWT_ACCEPTED_ISSUERS / BFF_JWT_ACCEPTED_AUDIENCES per call;
an empty list refuses every token. The chart must serve both, and the realm must put the audience in the
access token of every client meant to call the BFF, or the roll locks everyone out.

Run: uv run --frozen python -m pytest tests/security/test_the_bff_accepts_only_served_issuers_and_audiences_chart.py -v
"""
from __future__ import annotations

import json
import shutil

import pytest
import yaml

from tests.test_oidc_broker_chart import (
    _BROKER_OFF,
    _CHART,
    _REPO,
    _SANDBOX,
    _docs,
    _realm,
    _render,
    _render_fails,
    _script,
    _set,
)

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_SB = yaml.safe_load(open(_SANDBOX[1], encoding="utf-8"))
_BASE = yaml.safe_load(open(_REPO / _CHART / "values.yaml", encoding="utf-8"))
_AUDIENCE = _SB["cortexBff"]["auth"]["realmAudience"]
_IN_CLUSTER = _SB["agentFleet"]["env"]["KEYCLOAK_REALM_URL"]
_SERVICE = [c["clientId"] for c in [*_BASE["keycloak"]["serviceClients"], *(_BASE["keycloak"].get("extraServiceClients") or []),
                                    *_SB["keycloak"].get("serviceClients", []), *(_SB["keycloak"].get("extraServiceClients") or [])]]
_DELEGATES = [c["clientId"] for c in (_SB["keycloak"].get("extraServiceClients") or []) if c.get("kind") == "delegate"]
_PUBLIC_CONTROL = "training-workbench"
_AUD_NAMES = ("ISSUERS", "AUDIENCES")


def _gateway_issuer() -> str:
    """GATEWAY_JWT_ISSUER from whichever values block of the sandbox file declares it (never typed here)."""
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "GATEWAY_JWT_ISSUER" and isinstance(v, str):
                    found.append(v)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(_SB)
    assert found, "values-sandbox.yaml declares no GATEWAY_JWT_ISSUER"
    return found[0]


def _bff_env(rendered: str) -> list[dict]:
    (dep,) = [d for d in _docs(rendered) if d["kind"] == "Deployment" and d["metadata"]["name"].endswith("cortex-bff")]
    (ctr,) = [c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "cortex-bff"]
    return ctr["env"]


def _last(env: list[dict], name: str):
    hits = [e for e in env if e["name"] == name]
    assert hits, f"{name} not in the container env"
    return hits[-1]["value"]


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_SANDBOX, *_BROKER_OFF)


def test_the_sandbox_serves_both_lists_from_the_values_file(sandbox):
    env = _bff_env(sandbox)
    assert _last(env, "BFF_JWT_ACCEPTED_AUDIENCES") == _AUDIENCE
    issuers = _last(env, "BFF_JWT_ACCEPTED_ISSUERS").split(",")
    assert issuers == [_gateway_issuer(), _IN_CLUSTER]
    # control: the two are different strings, so a list serving one of them twice would fail above
    assert issuers[0] != issuers[1]


def test_base_values_serve_both_lists_present_and_empty():
    env = _bff_env(_render(*_BROKER_OFF))
    for suffix in _AUD_NAMES:
        name = f"BFF_JWT_ACCEPTED_{suffix}"
        assert [e["value"] for e in env if e["name"] == name] == [""], f"{name} must be present and empty"
    # control: the sandbox render, same template, is NOT empty
    assert _last(_bff_env(_render(*_SANDBOX, *_BROKER_OFF)), "BFF_JWT_ACCEPTED_AUDIENCES") != ""


def test_a_hand_set_env_cannot_widen_the_served_value(sandbox):
    env = _bff_env(_render(*_SANDBOX, *_BROKER_OFF, *_set("cortexBff.env.BFF_JWT_ACCEPTED_AUDIENCES", "anything")))
    values = [e["value"] for e in env if e["name"] == "BFF_JWT_ACCEPTED_AUDIENCES"]
    assert "anything" in values, "control: the hand-set value is rendered, so the order is what is tested"
    assert values[-1] == _AUDIENCE
    # control: without the hand-set env there is exactly one occurrence
    assert len([e for e in _bff_env(sandbox) if e["name"] == "BFF_JWT_ACCEPTED_AUDIENCES"]) == 1


def _aud_mappers(client: dict) -> list[dict]:
    return [m for m in client.get("protocolMappers", []) if m["config"].get("included.custom.audience") == _AUDIENCE]


def test_the_realm_import_stamps_the_audience_on_every_calling_client(sandbox):
    clients = {c["clientId"]: c for c in _realm(sandbox)["clients"]}
    assert _SERVICE, "no service clients derived from the values files"
    assert _DELEGATES and set(_DELEGATES) <= set(_SERVICE), "the delegates (the walk's callers) must be covered"
    for cid in ("cortex-ui", *_SERVICE):
        assert cid in clients, f"{cid} is not in the realm import"
        mappers = _aud_mappers(clients[cid])
        assert mappers, f"{cid} has no mapper putting {_AUDIENCE} in aud"
        assert all(m["config"]["access.token.claim"] == "true" for m in mappers), cid
    # control: a public client the BFF does not serve does not carry it
    assert _aud_mappers(clients[_PUBLIC_CONTROL]) == []


def test_realm_audience_must_be_an_accepted_audience():
    err = _render_fails(*_SANDBOX, *_BROKER_OFF, *_set("cortexBff.auth.realmAudience", "not-accepted"))
    assert "realmAudience" in err and "acceptedAudiences" in err
    # control: the same render with an accepted value succeeds
    _render(*_SANDBOX, *_BROKER_OFF, *_set("cortexBff.auth.realmAudience", _AUDIENCE))


def test_the_reconcile_repairs_the_audience_keyed_on_what_a_mapper_emits(sandbox):
    script = _script(sandbox)
    key = f'"included.custom.audience":"{_AUDIENCE}"'
    assert script.count(key) >= 2 + len(_SERVICE)
    assert "audience-bff mapper absent -> adding" in script
    assert "-- cortex-ui audience mapper" in script
    # the service-client repair sits in the loop, which every delegate passes through
    for cid in _DELEGATES:
        assert f'CID="{cid}"' in script, cid
    # control: with no realmAudience, the job carries no audience-bff at all
    off = _render(*_SANDBOX, *_BROKER_OFF, *_set("cortexBff.auth.realmAudience", ""))
    assert "audience-bff" not in _script(off)
    assert "audience-bff" not in json.dumps(_realm(off))
