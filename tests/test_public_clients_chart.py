"""Declared PUBLIC (PKCE) Keycloak clients, first member `training-workbench` (ruled 2026-10-24).

Run: uv run --frozen python -m pytest tests/test_public_clients_chart.py -v
"""
from __future__ import annotations

import json
import re
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

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_ID = "training-workbench"
# read from the sandbox values, never restated: the host is live configuration (ruled 10-17)
(_DECL,) = [c for c in yaml.safe_load(open(_SANDBOX[1], encoding="utf-8"))["keycloak"]["publicClients"] if c["clientId"] == _ID]
(_URI,) = _DECL["redirectUris"]
(_ORIGIN,) = _DECL["webOrigins"]
# the email claim cannot ride a sandbox broker, so the email arm renders the broker off too
_EMAIL = [*_SANDBOX, *_BROKER_OFF, *_set("keycloak.authzClaim", "email")]


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_SANDBOX, *_BROKER_OFF)


def _client(rendered: str, cid: str = _ID) -> list[dict]:
    return [c for c in _realm(rendered)["clients"] if c["clientId"] == cid]


#: ruled b5: the workbench api accepts a token only when `aud` names `training-workbench`. A public
#: client's stock access token carries at most `account`, so the client must put itself there.
_AUD = {"included.client.audience": _ID, "access.token.claim": "true", "id.token.claim": "false"}


def _mapper(c: dict, name: str) -> dict:
    (m,) = [m for m in c["protocolMappers"] if m["name"] == name]
    return m


def test_import_carries_exactly_one_public_client_with_every_property(sandbox):
    # the import is the fresh-realm path; every property here is one the BFF or the login depends on
    found = _client(sandbox)
    assert len(found) == 1
    c = found[0]
    assert c["enabled"] is True
    assert c["publicClient"] is True
    assert c["standardFlowEnabled"] is True
    assert c["implicitFlowEnabled"] is False
    assert c["directAccessGrantsEnabled"] is False
    assert c["serviceAccountsEnabled"] is False
    assert c["fullScopeAllowed"] is True
    assert c["redirectUris"] == [_URI]
    assert c["webOrigins"] == [_ORIGIN]
    assert c["attributes"]["pkce.code.challenge.method"] == "S256"
    assert c["attributes"]["post.logout.redirect.uris"] == _URI
    assert "secret" not in c
    assert sorted(m["name"] for m in c["protocolMappers"]) == ["audience-self", "authz-id-user"]
    aud = _mapper(c, "audience-self")
    assert aud["protocolMapper"] == "oidc-audience-mapper" and aud["config"] == _AUD
    m = _mapper(c, "authz-id-user")
    assert m["config"]["claim.name"] == "authz_id"
    assert m["config"]["user.attribute"] == "authz_id"
    # the mapper is identical to cortex-ui's, which is the mapper the BFF contract is written against
    (cui,) = _client(sandbox, "cortex-ui")
    assert m == cui["protocolMappers"][0]


def test_reconcile_creates_it_and_the_readback_fails_on_each_condition(sandbox):
    # a live realm never re-imports, so the job is the only path that can create or judge the client
    s = _script(sandbox)
    assert f'PCID="{_ID}"' in s
    assert '"publicClient": true' in s
    assert '"pkce.code.challenge.method": "S256"' in s
    assert '"authz-id-user"' in s
    assert 'echo "   created"' in s
    for needle in (
        f"FAIL $PCID: client absent after reconcile",
        "FAIL $PCID: not a public client",
        "FAIL $PCID: PKCE S256 is not required",
        "FAIL $PCID: password grant is enabled",
        "FAIL $PCID: fullScopeAllowed is not true",
        f"FAIL $PCID: redirectUri {_URI} is not on the live client",
        "FAIL $PCID: no mapper emits claim authz_id",
        f"FAIL $PCID: no mapper puts {_ID} in the access token's aud",
    ):
        assert needle in s, needle
    assert '"publicClient":true' in s and '"directAccessGrantsEnabled":false' in s
    assert '"audience-self"' in s and '"oidc-audience-mapper"' in s
    assert f"ok   $PCID public, pkce S256, emits authz_id, aud {_ID}" in s
    # never PUT the client: an existing client's settings are the operator's
    seg = s[s.index('echo "-- public client'):s.index("== readback ==")]
    assert "-X PUT" not in seg


def test_default_values_render_no_public_client():
    # the base chart declares none, so neither the import nor the script mentions one
    r = _render()
    assert _client(r) == []
    assert "public client" not in _script(r)
    assert "PCID" not in _script(r)


def test_email_claim_has_no_authz_mapper_and_the_script_neither_adds_nor_reads_it_back():
    # under email the claim IS the email, which the stock token already carries: no mapper to add or
    # check. The audience is not the claim's business: the api refuses a token without it either way.
    r = _render(*_EMAIL)
    (c,) = _client(r)
    (aud,) = c["protocolMappers"]
    assert aud["name"] == "audience-self" and aud["config"] == _AUD
    seg = _script(r)
    pub = seg[seg.index('echo "-- public client'):seg.index("== readback ==")]
    assert "authz-id-user" not in pub
    assert '"audience-self"' in pub
    assert "no mapper emits claim" not in seg
    assert "in the access token's aud" in seg
    assert 'echo "-- public client' in seg


_BAD = [
    ("redirect_star", [{"clientId": "pc-a", "redirectUris": ["*"], "webOrigins": []}], "pc-a"),
    ("redirect_http", [{"clientId": "pc-b", "redirectUris": ["http://x/*"], "webOrigins": []}], "pc-b"),
    ("redirect_https_star", [{"clientId": "pc-f", "redirectUris": ["https://*"]}], "pc-f"),
    ("redirect_wild_host", [{"clientId": "pc-g", "redirectUris": ["https://*.example.com/*"]}], "pc-g"),
    ("duplicate", [{"clientId": "pc-c", "redirectUris": ["https://x/*"]},
                   {"clientId": "pc-c", "redirectUris": ["https://y/*"]}], "pc-c"),
    ("cortex_ui", [{"clientId": "cortex-ui", "redirectUris": ["https://x/*"]}], "cortex-ui"),
    ("service_client", [{"clientId": "iagent-engine-d", "redirectUris": ["https://x/*"]}], "iagent-engine-d"),
    ("empty_redirects", [{"clientId": "pc-d", "redirectUris": []}], "pc-d"),
    ("origin_star", [{"clientId": "pc-e", "redirectUris": ["https://x/*"], "webOrigins": ["*"]}], "pc-e"),
]


@pytest.mark.parametrize("name,clients,cid", _BAD, ids=[b[0] for b in _BAD])
def test_render_fails_naming_the_client(name, clients, cid):
    # a public client is protected only by its redirect set, so each unsafe shape must stop the render
    err = _render_fails(*_SANDBOX, *_BROKER_OFF, "--set-json", f"keycloak.publicClients={json.dumps(clients)}")
    assert cid in err
    assert "publicClients" in err


# ---------------------------------------------------------------- executed against the Keycloak double

import copy  # noqa: E402

from tests.test_oidc_broker_realm_roundtrip import _OFF, _run, _seeded  # noqa: E402


@pytest.fixture(scope="module")
def body() -> str:
    # create segment up to the local-human section, plus the readback from its PCID= through its closing fi
    s = _script(_render(*_SANDBOX, *_OFF))
    a = s.index(f'PCID="{_ID}"')
    create = s[a:s.index('echo "-- local human', a)]
    r = s.rindex(f'PCID="{_ID}"')
    ok = s.index("ok   $PCID", r)
    end = re.compile(r"\n *fi\b").search(s, ok).end()
    return create + "\n" + s[r:end]


_EMPTY = {"users": [], "clients": []}


def _stored(state: dict) -> dict:
    (c,) = [c for c in state["clients"] if c["clientId"] == _ID]
    return c


def _puts(run) -> list[str]:
    return [c["p"] for c in run.calls if c["m"] == "PUT"]


def _client_posts(run) -> list[str]:
    return [p for p in run.posts() if p.startswith("/clients")]


def _created(body):
    run = _run(body, _seeded(_EMPTY))
    assert run.rc == 0, run.out + run.err
    return run


def test_exec_creates_into_an_empty_realm_and_the_readback_passes(body):
    # the live-realm path: create from nothing, then judge what was stored
    run = _created(body)
    assert "created" in run.out and "ok   training-workbench" in run.out
    c = _stored(run.state)
    assert c["publicClient"] is True and c["directAccessGrantsEnabled"] is False
    assert c["attributes"]["pkce.code.challenge.method"] == "S256"
    assert _URI in c["redirectUris"]
    assert _mapper(c, "authz-id-user")["config"]["claim.name"] == "authz_id"
    assert _mapper(c, "audience-self")["config"] == _AUD
    assert f"aud {_ID}" in run.out


def test_exec_second_run_is_idempotent(body):
    # create-if-absent: a second run must neither POST nor PUT nor change the state
    first = _created(body)
    again = _run(body, first.state)
    assert again.rc == 0, again.out + again.err
    assert "present" in again.out and "created" not in again.out
    assert _client_posts(again) == [] and _puts(again) == []
    assert again.state == first.state


def _seed_variant(body, mutate, *, drop_mappers=False):
    st = copy.deepcopy(_created(body).state)
    c = _stored(st)
    if drop_mappers:
        c["protocolMappers"] = []
    mutate(c)
    return _run(body, st)


def _drop(*names):
    def go(c):
        c["protocolMappers"] = [m for m in c["protocolMappers"] if m["name"] not in names]
    return go


@pytest.mark.parametrize("missing", [("authz-id-user",), ("audience-self",), ("authz-id-user", "audience-self")],
                         ids=["authz", "audience", "both"])
def test_exec_existing_client_gets_one_mapper_post_per_missing_mapper(body, missing):
    # a client imported before a mapper existed is repaired by adding that mapper, never by rewriting
    # it; the live workbench client was created before audience-self, so "audience" is the 208 case
    run = _seed_variant(body, _drop(*missing))
    assert run.rc == 0, run.out + run.err
    posts = _client_posts(run)
    assert len(posts) == len(missing) and all(p.endswith("/protocol-mappers/models") for p in posts)
    assert _puts(run) == []
    c = _stored(run.state)
    assert sorted(m["name"] for m in c["protocolMappers"]) == ["audience-self", "authz-id-user"]
    assert _mapper(c, "audience-self")["config"] == _AUD
    assert f"ok   training-workbench public, pkce S256, emits authz_id, aud {_ID}" in run.out


def test_exec_password_grant_is_refused_by_the_readback_not_overwritten(body):
    # the job never PUTs an existing client; the readback is what refuses a weakened one
    run = _seed_variant(body, lambda c: c.update(directAccessGrantsEnabled=True))
    assert run.rc == 1 and "password grant" in run.out
    assert _puts(run) == []


def test_exec_missing_declared_redirect_is_refused(body):
    # a client whose redirect set lost the declared URI would break the login
    run = _seed_variant(body, lambda c: c.update(redirectUris=["https://elsewhere.example/*"]))
    assert run.rc == 1 and _URI in run.out and "redirectUri" in run.out
    assert _puts(run) == []


def test_exec_missing_pkce_attribute_is_refused(body):
    # without S256 a public client's code can be replayed
    run = _seed_variant(body, lambda c: c["attributes"].pop("pkce.code.challenge.method"))
    assert run.rc == 1 and "PKCE" in run.out
    assert _puts(run) == []


def test_exec_confidential_client_is_refused(body):
    # a client flipped to confidential would make the workbench's secret-less login fail
    run = _seed_variant(body, lambda c: c.update(publicClient=False))
    assert run.rc == 1 and "not a public client" in run.out
    assert _puts(run) == []


def test_exec_narrowed_scope_is_refused(body):
    # without fullScopeAllowed a user's realm and cortex-ui roles do not ride the token
    run = _seed_variant(body, lambda c: c.update(fullScopeAllowed=False))
    assert run.rc == 1 and "fullScopeAllowed" in run.out
    assert _puts(run) == []


def test_exec_mapper_named_right_but_emitting_another_claim_is_refused(body):
    # the repair keys on the mapper's name, so only the readback sees a mapper that emits the wrong claim
    def wrong_claim(c):
        _mapper(c, "authz-id-user")["config"]["claim.name"] = "email"
    run = _seed_variant(body, wrong_claim)
    assert run.rc == 1 and "no mapper emits claim authz_id" in run.out
    assert _client_posts(run) == [] and _puts(run) == []


_NO_AUD = f"no mapper puts {_ID} in the access token's aud"


def test_exec_audience_kept_out_of_the_access_token_is_refused_not_rewritten(body):
    # the repair keys on what the mapper emits, so a mapper naming the client but off the access token
    # is left alone (an existing mapper is the operator's) and the readback refuses it
    run = _seed_variant(body, lambda c: _mapper(c, "audience-self")["config"].update({"access.token.claim": "false"}))
    assert run.rc == 1 and _NO_AUD in run.out
    assert _client_posts(run) == [] and _puts(run) == []


def test_exec_access_flag_on_another_mapper_does_not_satisfy_the_audience(body):
    # the audience and its flag must be judged on ONE mapper: authz-id-user carries access.token.claim
    # true, so a check over the whole mapper list would pass a client whose aud never reaches the token
    run = _seed_variant(body, lambda c: _mapper(c, "audience-self")["config"].pop("access.token.claim"))
    assert run.rc == 1 and _NO_AUD in run.out
    assert _puts(run) == []


def test_exec_audience_naming_another_client_is_refused(body):
    # a same-named mapper putting someone else in aud: the repair's POST collides on the name, and the
    # readback refuses the client either way
    run = _seed_variant(body, lambda c: _mapper(c, "audience-self")["config"].update(
        {"included.client.audience": "cortex-ui"}))
    assert run.rc == 1 and _NO_AUD in run.out
    assert _puts(run) == []
    assert _mapper(_stored(run.state), "audience-self")["config"]["included.client.audience"] == "cortex-ui"


def test_exec_an_audience_under_another_name_is_not_duplicated(body):
    # the repair keys on what a mapper EMITS: an operator's mapper already putting the client in aud,
    # under its own name, satisfies it. A repair keyed on the name would POST a second audience mapper.
    def rename(c):
        _mapper(c, "audience-self")["name"] = "operator-made-aud"
    run = _seed_variant(body, rename)
    assert run.rc == 0, run.out + run.err
    assert _client_posts(run) == [] and _puts(run) == []
    assert [m["name"] for m in _stored(run.state)["protocolMappers"] if m["protocolMapper"] == "oidc-audience-mapper"] \
        == ["operator-made-aud"]


def test_exec_readback_does_not_depend_on_the_order_keycloak_serves_config_in(body):
    # Keycloak holds a mapper's config as a map, so its key order is Keycloak's, not the POST's. The
    # double saves with sort_keys and serves the order it loaded; a read-only run never re-saves, so
    # storing the audience mapper's config reversed serves it reversed, and that must still pass.
    st = copy.deepcopy(_created(body).state)
    m = _mapper(_stored(st), "audience-self")
    before = list(m["config"])
    m["config"] = dict(reversed(list(m["config"].items())))
    assert list(m["config"]) != before and len(before) == 3  # the fixture differs from what a create stores
    run = _run(body, st)
    assert run.rc == 0, run.out + run.err
    assert f"aud {_ID}" in run.out and _client_posts(run) == []
