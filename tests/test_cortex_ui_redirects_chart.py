"""The cortex-ui client's redirect set is literal, never `*` (ruled 2026-10-24, the architect).

Run: uv run --frozen python -m pytest tests/test_cortex_ui_redirects_chart.py -v
"""
from __future__ import annotations

import copy
import json
import shutil

import pytest
import yaml

from tests.test_oidc_broker_chart import (
    _BROKER_OFF,
    _SANDBOX,
    _realm,
    _render,
    _render_fails,
    _script,
    _set,
)
from tests.test_oidc_broker_realm_roundtrip import _OFF, _run, _seeded

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

# read from the sandbox values, never restated: the host is live configuration (ruled 10-17)
_H = yaml.safe_load(open(_SANDBOX[1], encoding="utf-8"))["cortexUi"]["ingress"]["tls"][0]["hosts"][0]
_CUI_ID = "11111111-aaaa-4bbb-8ccc-222222222222"


def _cui(rendered: str) -> dict:
    (c,) = [c for c in _realm(rendered)["clients"] if c["clientId"] == "cortex-ui"]
    return c


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_SANDBOX, *_BROKER_OFF)


def test_sandbox_import_carries_the_literal_origin_set_and_keeps_every_other_field(sandbox):
    # the sandbox derives its set from cortexUi.ingress; nothing is declared in values-sandbox.yaml
    c = _cui(sandbox)
    assert c["redirectUris"] == [f"https://{_H}", f"https://{_H}/"]
    assert c["webOrigins"] == [f"https://{_H}"]
    assert c["attributes"] == {"post.logout.redirect.uris": f"https://{_H}/"}
    assert "*" not in json.dumps([c["redirectUris"], c["webOrigins"], c["attributes"]])
    # the rest of the client is untouched (literal values, as on master)
    assert c["publicClient"] is True and c["directAccessGrantsEnabled"] is True and c["enabled"] is True
    (m,) = c["protocolMappers"]
    assert m["name"] == "authz-id-user" and m["protocolMapper"] == "oidc-usermodel-attribute-mapper"
    assert m["config"]["claim.name"] == "authz_id" and m["config"]["user.attribute"] == "authz_id"


def test_default_values_emit_no_redirect_at_all():
    # nothing declared and no ingress to derive from: fail closed, with no post-logout attribute either
    c = _cui(_render())
    assert c["redirectUris"] == [] and c["webOrigins"] == []
    assert "attributes" not in c
    assert c["publicClient"] is True and c["directAccessGrantsEnabled"] is True


def test_declared_set_wins_over_derivation():
    # an operator's explicit list replaces the derived one, key by key
    r = _render(*_SANDBOX, *_BROKER_OFF,
                *_set("keycloak.cortexUiClient.redirectUris", ["https://declared.example.com"]),
                *_set("keycloak.cortexUiClient.webOrigins", ["https://declared.example.com"]),
                *_set("keycloak.cortexUiClient.postLogoutRedirectUris", ["https://declared.example.com/bye"]))
    c = _cui(r)
    assert c["redirectUris"] == ["https://declared.example.com"]
    assert c["webOrigins"] == ["https://declared.example.com"]
    assert c["attributes"]["post.logout.redirect.uris"] == "https://declared.example.com/bye"


_BAD = [
    ("star", "redirectUris", ["*"]),
    ("https_star", "redirectUris", ["https://*"]),
    ("http", "redirectUris", ["http://h.example.com"]),
    ("path_star", "redirectUris", ["https://h.example.com/case/*"]),
    ("logout_star", "postLogoutRedirectUris", ["https://h.example.com/*"]),
    ("origin_star", "webOrigins", ["*"]),
    ("origin_path", "webOrigins", ["https://h.example.com/app"]),
]


@pytest.mark.parametrize("name,key,value", _BAD, ids=[b[0] for b in _BAD])
def test_render_fails_naming_cortex_ui(name, key, value):
    # a public client is protected only by its redirect set, so each unsafe shape stops the render
    err = _render_fails(*_SANDBOX, *_BROKER_OFF, *_set(f"keycloak.cortexUiClient.{key}", value))
    assert "cortex-ui" in err
    assert f"cortexUiClient.{key}" in err


# ---------------------------------------------------------------- executed against the Keycloak double



@pytest.fixture(scope="module")
def script() -> str:
    return _script(_render(*_SANDBOX, *_OFF))


def _converge(s: str) -> str:
    a = s.index("# ── cortex-ui REDIRECT SET")
    return s[a:s.index("# ── end cortex-ui redirect set", a)]


def _readback(s: str) -> str:
    end = s.index("# ── end cortex-ui redirect readback")
    return s[s.rindex("CUI=$(curl", 0, end):end]


_MAPPER = {"name": "authz-id-user", "protocol": "openid-connect",
           "protocolMapper": "oidc-usermodel-attribute-mapper", "id": "m-1",
           "config": {"user.attribute": "authz_id", "claim.name": "authz_id"}}


def _live(**over) -> dict:
    c = {"id": _CUI_ID, "clientId": "cortex-ui", "enabled": True, "publicClient": True,
         "directAccessGrantsEnabled": True, "redirectUris": ["*"], "webOrigins": ["*"],
         "attributes": {"pkce.code.challenge.method": "S256"}, "protocolMappers": [copy.deepcopy(_MAPPER)]}
    c.update(over)
    return c


def _state(client: dict) -> dict:
    return _seeded({"users": [], "clients": [client]})


def _stored(run) -> dict:
    (c,) = [c for c in run.state["clients"] if c["clientId"] == "cortex-ui"]
    return c


def _puts(run) -> list[str]:
    return [c["p"] for c in run.calls if c["m"] == "PUT"]


def _want_literals(run) -> None:
    c = _stored(run)
    assert c["redirectUris"] == [f"https://{_H}", f"https://{_H}/"]
    assert c["webOrigins"] == [f"https://{_H}"]
    assert c["attributes"]["post.logout.redirect.uris"] == f"https://{_H}/"


def test_exec_wildcard_client_is_converged_by_one_put_and_nothing_else_changes(script):
    # the live shape: wildcard sets, password grant on, an unrelated attribute, the authz mapper
    run = _run(_converge(script) + "\n" + _readback(script), _state(_live()))
    assert run.rc == 0, run.out + run.err
    assert _puts(run) == [f"/clients/{_CUI_ID}"]
    _want_literals(run)
    c = _stored(run)
    # the double's PUT replaces the client with the body, so a dropped field would show here
    assert c["directAccessGrantsEnabled"] is True and c["publicClient"] is True
    assert c["attributes"]["pkce.code.challenge.method"] == "S256"
    assert c["protocolMappers"] == [_MAPPER]
    assert "converged" in run.out and "ok   cortex-ui redirects 2 literal, no wildcard" in run.out


def test_exec_second_run_is_as_declared_and_writes_nothing(script):
    # idempotent: a converged client is compared, never rewritten
    body = _converge(script)
    first = _run(body, _state(_live()))
    again = _run(body, first.state)
    assert again.rc == 0, again.out + again.err
    assert "as declared" in again.out and _puts(again) == []
    assert again.state == first.state


def test_exec_existing_post_logout_key_is_replaced_not_duplicated(script):
    # a live client holding the key with another value gets that value replaced exactly once
    live = _live(attributes={"post.logout.redirect.uris": "https://old.example.com/", "pkce.code.challenge.method": "S256"})
    run = _run(_converge(script), _state(live))
    assert run.rc == 0, run.out + run.err
    _want_literals(run)
    assert _stored(run)["attributes"]["pkce.code.challenge.method"] == "S256"
    assert json.dumps(run.state).count("post.logout.redirect.uris") == 1


def test_exec_client_without_an_attributes_object_gets_one(script):
    # no attributes key at all: it is added, and every other field survives
    live = _live()
    del live["attributes"]
    run = _run(_converge(script), _state(live))
    assert run.rc == 0, run.out + run.err
    _want_literals(run)
    c = _stored(run)
    assert c["directAccessGrantsEnabled"] is True and c["publicClient"] is True
    assert c["protocolMappers"] == [_MAPPER]


def test_exec_client_with_empty_attributes_gets_the_key_without_a_stray_comma(script):
    # `"attributes":{}` must not become `{"k":"v",}`: the double parses the PUT body as JSON
    run = _run(_converge(script), _state(_live(attributes={})))
    assert run.rc == 0, run.out + run.err
    _want_literals(run)


def test_exec_readback_refuses_an_extra_redirect_and_names_cortex_ui(script):
    # readback only (convergence cannot fix it): one entry beyond the literal set is a failure
    live = _live(redirectUris=[f"https://{_H}", f"https://{_H}/", "https://evil.example.com"],
                 webOrigins=[f"https://{_H}"], attributes={"post.logout.redirect.uris": f"https://{_H}/"})
    run = _run(_readback(script), _state(live))
    assert run.rc == 1 and "cortex-ui" in run.out and "redirectUris" in run.out
    assert _puts(run) == []


def test_exec_readback_refuses_a_wildcard_origin_a_wrong_logout_and_a_confidential_client(script):
    # each remaining readback condition fails on its own line
    live = _live(redirectUris=[f"https://{_H}", f"https://{_H}/"], publicClient=False)
    run = _run(_readback(script), _state(live))
    assert run.rc == 1
    assert "webOrigins" in run.out and "post.logout.redirect.uris" in run.out and "not a public client" in run.out


def test_exec_empty_derived_set_warns_on_a_wildcard_and_writes_nothing():
    # nothing declared and nothing derivable: the live client is left alone, loudly
    s = _script(_render(*_SANDBOX, *_OFF, *_set("cortexUi.ingress.enabled", False)))
    assert "WANT_RA=" not in s and "cortex-ui redirects" not in s
    run = _run(_converge(s), _state(_live()))
    assert run.rc == 0, run.out + run.err
    assert "undeclared, live client unchanged" in run.out
    assert "WARN cortex-ui: live redirectUris holds a wildcard" in run.out
    assert _puts(run) == [] and _stored(run)["redirectUris"] == ["*"]


# Keycloak holds redirectUris / webOrigins as sets and serves them in its own order: 0.4.69's
# readback failed on a correct realm because it compared the array text (rev 217). The double
# serves those fields reversed (tests/fake_keycloak_curl.py), so an order-dependent compare reds here.
_FINAL = {"webOrigins": [f"https://{_H}"], "attributes": {"post.logout.redirect.uris": f"https://{_H}/"}}


@pytest.mark.parametrize("order", [[f"https://{_H}", f"https://{_H}/"], [f"https://{_H}/", f"https://{_H}"]],
                         ids=["declared_order", "reversed"])
def test_exec_readback_accepts_the_declared_set_in_either_order(script, order):
    run = _run(_readback(script), _state(_live(redirectUris=order, **_FINAL)))
    assert run.rc == 0, run.out + run.err
    assert "ok   cortex-ui redirects 2 literal, no wildcard" in run.out


def test_exec_readback_refuses_a_missing_member(script):
    # a set compare, not a subset one: one literal short is still a failure
    run = _run(_readback(script), _state(_live(redirectUris=[f"https://{_H}/"], **_FINAL)))
    assert run.rc == 1 and "FAIL cortex-ui: live" in run.out and "redirectUris" in run.out


@pytest.mark.parametrize("order", [[f"https://{_H}", f"https://{_H}/"], [f"https://{_H}/", f"https://{_H}"]],
                         ids=["declared_order", "reversed"])
def test_exec_converge_treats_the_declared_set_in_either_order_as_declared(script, order):
    # the live realm after 0.4.69 holds the declared literals in its own order: no PUT
    run = _run(_converge(script), _state(_live(redirectUris=order, **_FINAL)))
    assert run.rc == 0, run.out + run.err
    assert "as declared" in run.out and _puts(run) == []


_A, _B = "https://a.example.com", "https://b.example.com"


@pytest.fixture(scope="module")
def two_origins() -> str:
    # the sandbox derives ONE origin, so only a declared pair exercises the webOrigins set compare
    return _script(_render(*_SANDBOX, *_OFF, *_set("keycloak.cortexUiClient.redirectUris", [_A, _B]),
                           *_set("keycloak.cortexUiClient.webOrigins", [_A, _B]),
                           *_set("keycloak.cortexUiClient.postLogoutRedirectUris", [f"{_A}/"])))


@pytest.mark.parametrize("order", [[_A, _B], [_B, _A]], ids=["declared_order", "reversed"])
def test_exec_two_declared_origins_converge_once_and_read_back_in_either_order(two_origins, order):
    live = _live(redirectUris=order, webOrigins=order, attributes={"post.logout.redirect.uris": f"{_A}/"})
    run = _run(_converge(two_origins) + "\n" + _readback(two_origins), _state(live))
    assert run.rc == 0, run.out + run.err
    assert "as declared" in run.out and _puts(run) == []
    assert "ok   cortex-ui redirects 2 literal, no wildcard" in run.out
