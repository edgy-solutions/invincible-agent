"""Engine O binds the caller's identity and grants from the VERIFIED caller, never the request body.

THE ORDER (architect, via Chris, 11-19): "In engine O the caller's identity and grants come from the
verified caller, never the request body, including `_input_declared_pool` scoped by the caller's
grant, with the test that naming another person's email learns nothing." Lane 1 added: the test must
include a forged or unsigned token.

The token path here is REAL: an RSA key pair is generated, the SDK's `verify_bearer` checks an RS256
token against a JWKS double (issuer and audience configured by env), and engine O is driven through
its own app with `TestClient`, so the SDK dependency publishes the caller exactly as it does in the
cluster. Only the directory (`_held_domains_of`) and the stores behind the routes are doubles.

Posture is OBSERVE fleet-wide, so a forged, unsigned or key-less token is ADMITTED with its CLAIMED
subject on `authz_id` and `verified=False`. Each such arm asserts that the claim IS visible to the
SDK (the control: the hazard is real) and that engine O still binds anonymous.

Run: LOCKED_SDK=no_overlay_venv_is_0920 .venv/Scripts/python.exe <locked_pytest.py> <log> tests/routing/test_engine_o_binds_the_verified_caller.py -q
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from iagent_mesh import transport_auth as ta
from iagent_mesh.transport_auth import CallerIdentity

from agent_fleet.ontology_service import caller_binding as cb
from agent_fleet.ontology_service import main as eo
from agent_fleet.ontology_service import where_used as w
from agent_fleet.ontology_service.sustainment_instance_match import component_iri

REPO = Path(__file__).resolve().parents[2]
ALICE, BOB = "alice@example.com", "bob@example.com"
ISS, AUD = "https://issuer.example/realm", "engine-o-test"
DIRECTORY = {ALICE: ("SUSTAINMENT", "FINANCE"), BOB: ("SUSTAINMENT", "PLANNING")}

_KEY_GOOD = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KEY_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(subject: str, key=_KEY_GOOD, *, alg: str = "RS256") -> str:
    claims = {"iss": ISS, "aud": AUD, "exp": int(time.time()) + 600,
              ta._entitlement_claim(): subject}
    if alg == "none":
        return jwt.encode(claims, key=None, algorithm="none")
    return jwt.encode(claims, key, algorithm=alg)


def _bearer(subject: str, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(subject, **kw)}"}


class _Jwks:
    def get_signing_key_from_jwt(self, token):  # the realm publishes ONLY the good key
        class _K:
            key = _KEY_GOOD.public_key()
        return _K()


class _Directory:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, subject):
        self.calls.append(subject)
        return DIRECTORY.get(subject, ())


@pytest.fixture(autouse=True)
def mesh(monkeypatch):
    monkeypatch.setenv("MESH_JWT_JWKS_URL", "https://jwks.invalid/certs")
    monkeypatch.setenv("MESH_JWT_ACCEPTED_ISSUERS", ISS)
    monkeypatch.setenv("MESH_JWT_ACCEPTED_AUDIENCES", AUD)
    monkeypatch.delenv("MESH_JWT_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("KEYCLOAK_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("TRANSPORT_AUTH_REQUIRED", raising=False)
    monkeypatch.setattr(ta, "_jwks_client_for", lambda url: _Jwks())
    ta._clear_jwks_client_cache()
    directory = _Directory()
    monkeypatch.setattr(eo, "_held_domains_of", directory)
    monkeypatch.setattr(cb, "_DEFAULT_CACHE", cb.GrantCache(ttl_s=0))
    return directory


@pytest.fixture()
def client():
    return TestClient(eo.app)  # no `with`: the lifespan (stores, registration) is not run


@pytest.fixture()
def directory(mesh):
    return mesh


# -- the where-used fixture: alice sees both end items, bob the one on their program ------------

_FIXTURE = yaml.safe_load((REPO / w.SHIPPED_LOCATOR).read_text(encoding="utf-8"))


def _program_grants() -> dict:
    programs = yaml.safe_load((REPO / "policy/program_members.yaml").read_text(encoding="utf-8"))["programs"]
    return {k: set(v.get("grant_to") or []) for k, v in programs.items()}


@pytest.fixture()
def program_gate(monkeypatch):
    monkeypatch.setattr(eo, "_notice_parts_can_view_program",
                        lambda program, caller: caller in _program_grants().get(program, set()))


def _part_iri() -> str:
    number = next(a["value"] for i in _FIXTURE["identities"] for a in i["aliases"]
                  if a["scheme"] == "notice_part_number")
    return component_iri(number)


def _where_used(client, headers=None, **body) -> "object":
    payload = {"params": {}, "resolved_instance_id": _part_iri(), **body}
    return client.post("/where_used", json=payload, headers=headers or {})


# =============================================================================================
# 1. NAMING ANOTHER PERSON'S EMAIL LEARNS NOTHING
# =============================================================================================

def test_naming_alices_email_with_bobs_verified_token_learns_nothing(client, program_gate, directory):
    named = _where_used(client, _bearer(BOB), user_email=ALICE,
                        entitled_domains=list(DIRECTORY[ALICE]))
    nobody = _where_used(client, _bearer(BOB))
    own = _where_used(client, _bearer(ALICE), user_email=ALICE,
                      entitled_domains=list(DIRECTORY[ALICE]))
    assert named.status_code == nobody.status_code == own.status_code == 200
    assert named.content == nobody.content, "the body's person changed bob's answer"
    # the control: the fixture DOES discriminate -- alice's own verified request sees more
    assert own.content != named.content
    assert len(own.json()["where_used"]) > len(named.json()["where_used"]) >= 1
    # and the directory was asked about the token's subject only, never the body's
    assert set(directory.calls) == {BOB, ALICE} and directory.calls.count(ALICE) == 1


# =============================================================================================
# 2. THE PROVIDER/GATE DOUBLE RECEIVES THE VERIFIED SUBJECT AND GRANT, NEVER THE BODY'S
# =============================================================================================

@pytest.fixture()
def resolve_instance_spy(monkeypatch):
    seen: list[dict] = []

    async def _rows(*a, **k):
        return []

    async def _filter(candidates, *, user_email, entitled_domains):
        seen.append({"user_email": user_email, "entitled_domains": entitled_domains})
        return candidates

    async def _chains(candidates):
        return candidates

    monkeypatch.setattr(eo, "execute_sparql", _rows)
    monkeypatch.setattr(eo, "_resolve_sustainment_candidates", lambda ident, rows: [{"instance_id": "i"}])
    monkeypatch.setattr(eo, "_filter_sustainment_candidates", _filter)
    monkeypatch.setattr(eo, "_attach_class_chains", _chains)
    return seen


def _resolve_instance(client, headers, **body):
    r = client.post("/resolve_instance", json={"identifier": "x", "query": "x", **body}, headers=headers)
    assert r.status_code == 200, r.text
    return r


def test_the_gate_receives_bobs_subject_and_grant_whatever_the_body_says(client, resolve_instance_spy):
    _resolve_instance(client, _bearer(BOB), user_email=ALICE, entitled_domains=list(DIRECTORY[ALICE]))
    (got,) = resolve_instance_spy
    assert got["user_email"] == BOB
    assert got["entitled_domains"] == ("SUSTAINMENT",)   # bob's grant ∩ what was asked; alice's FINANCE is gone


def test_the_body_cannot_widen_a_grant(client, resolve_instance_spy):
    _resolve_instance(client, _bearer(BOB), user_email=BOB,
                      entitled_domains=["SUSTAINMENT", "FINANCE", "PLANNING", "UNHELD"])
    assert resolve_instance_spy[-1]["entitled_domains"] == ("SUSTAINMENT", "PLANNING")


def test_the_body_may_narrow_a_grant(client, resolve_instance_spy):
    _resolve_instance(client, _bearer(BOB), entitled_domains=["PLANNING"])
    assert resolve_instance_spy[-1]["entitled_domains"] == ("PLANNING",)


def test_an_empty_ask_is_the_whole_held_grant_sorted(client, resolve_instance_spy):
    _resolve_instance(client, _bearer(BOB), entitled_domains=[])
    assert resolve_instance_spy[-1]["entitled_domains"] == ("PLANNING", "SUSTAINMENT")


def test_asking_only_for_what_one_does_not_hold_is_no_grant(client, resolve_instance_spy):
    _resolve_instance(client, _bearer(BOB), entitled_domains=["FINANCE"])
    assert resolve_instance_spy[-1]["entitled_domains"] == (cb.NO_GRANT,)


# =============================================================================================
# 3. FORGED, UNSIGNED, KEY-LESS: ANONYMOUS, THE SAME ANSWER AS NO TOKEN
# =============================================================================================

def _forged():
    return {"Authorization": f"Bearer {_token(ALICE, _KEY_OTHER)}"}


def _unsigned():
    return {"Authorization": f"Bearer {_token(ALICE, alg='none')}"}


@pytest.mark.parametrize("make", [_forged, _unsigned, dict], ids=["forged", "unsigned", "no-token"])
def test_a_token_that_does_not_verify_binds_anonymous(client, program_gate, directory, make):
    headers = make()
    if headers:
        got = ta.verify_bearer(headers["Authorization"].split(" ", 1)[1])
        assert got.verified is False
    named = _where_used(client, headers, user_email=ALICE, entitled_domains=list(DIRECTORY[ALICE]))
    plain = _where_used(client, {})
    assert named.status_code == 200 and named.json()["reason"] == "not_entitled"
    assert named.content == plain.content
    assert directory.calls == [], "the directory is never asked about an unverified claim"
    # the control: the same body with alice's REAL token is not refused
    assert _where_used(client, _bearer(ALICE), user_email=ALICE,
                       entitled_domains=list(DIRECTORY[ALICE])).json()["status"] == "ok"


def test_a_claim_with_no_verification_key_is_visible_to_the_sdk_and_still_anonymous(
        client, program_gate, directory, monkeypatch):
    monkeypatch.delenv("MESH_JWT_JWKS_URL")
    tok = _token(ALICE, _KEY_OTHER)
    seen = ta.verify_bearer(tok)
    assert (seen.authz_id, seen.verified, seen.reason) == (ALICE, False, "no-verification-key")
    r = _where_used(client, {"Authorization": f"Bearer {tok}"}, user_email=ALICE,
                    entitled_domains=list(DIRECTORY[ALICE]))
    assert r.json()["reason"] == "not_entitled"
    assert r.content == _where_used(client, {}).content
    assert directory.calls == []


def test_anonymous_naming_a_person_on_enumerate_is_no_person(client, directory):
    r = client.post("/enumerate_instances", headers=_forged(), json={
        "class_uri": "urn:x#C", "user_email": ALICE, "entitled_domains": list(DIRECTORY[ALICE])})
    assert r.status_code == 422 and r.json()["error"] == "no_person"
    assert directory.calls == []


# =============================================================================================
# 4. NO GRANT IS NOT UNSCOPED
# =============================================================================================

class _Row:
    def __init__(self, uri, domains):
        self.uri, self.domains = uri, domains


def _search_double(monkeypatch, calls: list):
    """predicate_hybrid_search as Weaviate answers it: an EMPTY scope is unscoped, a non-empty one
    keeps rows that share a domain or declare none."""
    def _row(iri, domains, score):
        return {"input_uri": "mro:in", "verb_type": "read", "verb_iri": iri, "endpoint": "/x",
                "output_uri": "mro:out", "owner_persona": "p", "domains": domains,
                "cost_class": "low", "requires_human_approval": False, "score": score}

    rows = [_row("mro:scoped", ["SUSTAINMENT"], 0.9), _row("mro:agnostic", [], 0.8)]

    async def _search(query, entitled_domains, limit=10, user_email="", verb_iris=None):
        calls.append({"entitled_domains": list(entitled_domains), "user_email": user_email})
        if not entitled_domains:
            return rows
        scope = {d.upper() for d in entitled_domains}
        return [r for r in rows if not r["domains"] or scope & set(r["domains"])]

    class _Collections:
        def exists(self, name):
            return True

    class _Weaviate:
        collections = _Collections()

    monkeypatch.setattr(eo, "predicate_hybrid_search", _search)
    monkeypatch.setattr(eo, "_WEAVIATE_CLIENT", _Weaviate())
    monkeypatch.setattr(eo, "_emit_routing_decision", lambda **k: None)
    return rows


def test_anonymous_search_is_scoped_to_nothing_not_to_everything(client, monkeypatch):
    calls: list = []
    _search_double(monkeypatch, calls)
    r = client.post("/search_predicates", headers=_forged(), json={
        "query": "q", "entitled_domains": ["SUSTAINMENT"], "user_email": ALICE})
    assert r.status_code == 200
    (call,) = calls
    assert [d.casefold() for d in call["entitled_domains"]] == [cb.NO_GRANT]   # the route upper-cases
    assert call["user_email"] == ""
    got = {c["verb_iri"] for c in r.json().get("candidates", [])}
    assert "mro:scoped" not in got, "a domain-scoped predicate reached a caller with no grant"
    # control: the double IS unscoped on an empty scope (the hazard NO_GRANT closes)
    unscoped = asyncio.run(eo.predicate_hybrid_search("q", []))
    assert {r["verb_iri"] for r in unscoped} == {"mro:scoped", "mro:agnostic"}
    kept = asyncio.run(eo.predicate_hybrid_search("q", [cb.NO_GRANT.upper()]))
    assert {r["verb_iri"] for r in kept} == {"mro:agnostic"}


def test_a_verified_search_carries_the_held_grant_and_the_verified_subject(client, monkeypatch):
    calls: list = []
    _search_double(monkeypatch, calls)
    client.post("/search_predicates", headers=_bearer(BOB), json={
        "query": "q", "entitled_domains": list(DIRECTORY[ALICE]), "user_email": ALICE})
    (call,) = calls
    assert call["entitled_domains"] == ["SUSTAINMENT"] and call["user_email"] == BOB


def test_the_weaviate_filter_is_built_for_a_no_grant_scope():
    """Against the real sync search: `[NO_GRANT]` builds a filter; `[]` builds none (unscoped)."""
    seen: list = []

    class _Q:
        def hybrid(self, **k):
            seen.append(k["filters"])
            return type("R", (), {"objects": []})()
        bm25 = hybrid

    class _C:
        query = _Q()

    class _Cols:
        def exists(self, n):
            return True

        def get(self, n):
            return _C()

    class _W:
        collections = _Cols()

    import pytest as _p
    mp = _p.MonkeyPatch()
    try:
        mp.setattr(eo, "_WEAVIATE_CLIENT", _W())
        mp.setattr(eo, "embed_query", lambda q: [0.0])
        eo._predicate_hybrid_search_sync("q", [cb.NO_GRANT], 5)
        eo._predicate_hybrid_search_sync("q", [], 5)
    finally:
        mp.undo()
    assert seen[0] is not None and seen[1] is None


# =============================================================================================
# 5. _input_declared_pool TAKES THE BOUND GRANT, BY KEYWORD, NEVER THE LEGACY `domain`
# =============================================================================================

def test_the_input_declared_pool_searches_and_serves_the_bound_grant(monkeypatch):
    got: dict = {}

    async def _search(*args, **kwargs):
        got["args"], got["kwargs"] = args, kwargs
        return []

    async def _served(domains, include_referents=False):
        got["served"] = list(domains)
        return set()

    monkeypatch.setattr(eo, "predicate_hybrid_search", _search)
    monkeypatch.setattr(eo, "_served_class_uris", _served)
    request = eo.ResolveRequest(query="q", user_email="bound@example.com", domains=["BOUND"])
    assert request.domain == "MAINTENANCE", "the legacy default is a grant nobody granted"
    asyncio.run(eo._input_declared_pool(request, ["BOUND"]))
    assert got["kwargs"]["entitled_domains"] == ["BOUND"]
    assert got["kwargs"]["user_email"] == "bound@example.com"
    assert "MAINTENANCE" not in json.dumps(got, default=str)
    assert got["served"] == ["BOUND"]


def test_resolve_calls_the_pool_with_the_bound_grant_not_request_domain():
    import ast
    src = Path(eo.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_input_declared_pool"]
    assert len(calls) == 1
    text = ast.unparse(calls[0])
    assert "request.domain" not in text.replace("request.domains", ""), text


# =============================================================================================
# 6. bind(): THE PURE RULE
# =============================================================================================

def _held(mapping):
    return lambda s: mapping.get(s, ())


def test_bind_each_kind():
    person = cb.bind(CallerIdentity(BOB, True, "verified"), held_of=_held(DIRECTORY),
                     cache=cb.GrantCache(0))
    assert (person.kind, person.subject, person.grants) == ("person", BOB, ("PLANNING", "SUSTAINMENT"))
    svc = cb.bind(CallerIdentity("svc:thing", True, "verified"), held_of=_held({"svc:thing": ["x"]}),
                  cache=cb.GrantCache(0))
    assert (svc.kind, svc.subject, svc.grants) == ("service", "svc:thing", ("X",))
    for c in (None, CallerIdentity(ALICE, False, "no-verification-key"),
              CallerIdentity(None, False, "absent"), CallerIdentity("", True, "verified")):
        anon = cb.bind(c, body_subject=ALICE, asked=["SUSTAINMENT"], held_of=_held(DIRECTORY),
                       cache=cb.GrantCache(0))
        assert (anon.kind, anon.subject, anon.grants, anon.body_identity) == (
            "anonymous", "", (cb.NO_GRANT,), "ignored")


def test_bind_narrows_never_widens_and_keeps_asked_order():
    c = CallerIdentity(ALICE, True, "verified")
    b = cb.bind(c, asked=["finance", "UNHELD", "sustainment", "FINANCE"], held_of=_held(DIRECTORY),
                cache=cb.GrantCache(0))
    assert b.grants == ("FINANCE", "SUSTAINMENT")
    assert cb.bind(c, asked=["UNHELD"], held_of=_held(DIRECTORY), cache=cb.GrantCache(0)).grants == (cb.NO_GRANT,)
    assert cb.bind(c, asked=None, held_of=_held(DIRECTORY), cache=cb.GrantCache(0)).grants == (
        "FINANCE", "SUSTAINMENT")


def test_bind_names_the_body_identity_and_never_uses_it():
    c = CallerIdentity(ALICE, True, "verified")
    h = _held(DIRECTORY)
    assert cb.bind(c, body_subject="", held_of=h, cache=cb.GrantCache(0)).body_identity == "absent"
    assert cb.bind(c, body_subject=ALICE.upper(), held_of=h, cache=cb.GrantCache(0)).body_identity == "same"
    other = cb.bind(c, body_subject=BOB, held_of=h, cache=cb.GrantCache(0))
    assert (other.body_identity, other.subject) == ("ignored", ALICE)


def test_bind_fails_closed_when_the_directory_raises(caplog):
    def boom(subject):
        raise RuntimeError("secret-host.internal exploded for " + subject)

    with caplog.at_level(logging.WARNING):
        b = cb.bind(CallerIdentity(ALICE, True, "verified"), held_of=boom, cache=cb.GrantCache(0))
    assert (b.kind, b.subject, b.grants) == ("person", ALICE, (cb.NO_GRANT,))
    assert ALICE not in caplog.text and "secret-host" not in caplog.text


def test_the_grant_cache_hits_expires_and_never_caches_a_failure():
    now = [100.0]
    calls: list = []

    def held(subject):
        calls.append(subject)
        return ["A"]

    cache = cb.GrantCache(ttl_s=30, clock=lambda: now[0])
    c = CallerIdentity(BOB, True, "verified")
    cb.bind(c, held_of=held, cache=cache)
    cb.bind(c, held_of=held, cache=cache)
    assert len(calls) == 1
    now[0] += 29.9
    cb.bind(c, held_of=held, cache=cache)
    assert len(calls) == 1
    now[0] += 0.2
    cb.bind(c, held_of=held, cache=cache)
    assert len(calls) == 2

    boom_calls: list = []

    def boom(subject):
        boom_calls.append(subject)
        raise RuntimeError("x")

    cache2 = cb.GrantCache(ttl_s=30, clock=lambda: now[0])
    cb.bind(c, held_of=boom, cache=cache2)
    cb.bind(c, held_of=boom, cache=cache2)
    assert len(boom_calls) == 2, "a failure was cached"
    off = cb.GrantCache(ttl_s=0, clock=lambda: now[0])
    cb.bind(c, held_of=held, cache=off)
    cb.bind(c, held_of=held, cache=off)
    assert len(calls) == 4, "ttl 0 disables the cache"


def test_a_failed_grant_lookup_is_no_grant_whatever_the_body_asked():
    """Fail CLOSED: a directory outage binds no grant. It never falls back to the body's ask.

    Gov's mutant P (#452, comment 7001875325) replaced the empty held set with the ask on a
    lookup failure, and it survived."""
    def boom(subject):
        raise RuntimeError("directory down")

    c = CallerIdentity(BOB, True, "verified")
    for asked in (["A"], ["SUSTAINMENT", "PLANNING"], ["a"], None, []):
        b = cb.bind(c, asked=asked, held_of=boom, cache=cb.GrantCache(ttl_s=30))
        assert b.grants == (cb.NO_GRANT,), f"a failed lookup granted {b.grants} for asked={asked!r}"
        assert (b.subject, b.kind) == (BOB, cb.PERSON)


def test_the_grant_cache_never_serves_one_subject_anothers_grant():
    """The cache is keyed by SUBJECT. Within one TTL, on one cache, Bob binds Bob's grant and
    Alice binds Alice's, in either order.

    Gov's mutant Q (#452, comment 7001875325) keyed the cache on a constant, and it survived."""
    held = {ALICE: ["A"], BOB: ["B"]}.__getitem__
    alice = CallerIdentity(ALICE, True, "verified")
    bob = CallerIdentity(BOB, True, "verified")
    for first, second, want in ((alice, bob, ("B",)), (bob, alice, ("A",))):
        cache = cb.GrantCache(ttl_s=30, clock=lambda: 100.0)
        cb.bind(first, held_of=held, cache=cache)
        assert cb.bind(second, held_of=held, cache=cache).grants == want
        assert cb.bind(first, held_of=held, cache=cache).grants == (("A",) if first is alice else ("B",))


def test_the_ttl_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("ENGINE_O_GRANT_TTL_S", "7")
    assert cb.GrantCache().ttl_s == 7.0
    monkeypatch.setenv("ENGINE_O_GRANT_TTL_S", "0")
    assert cb.GrantCache().ttl_s == 0.0


# =============================================================================================
# 7. THE LOG LINE NAMES NO PERSON AND NO DOMAIN
# =============================================================================================

def test_the_bound_log_line_carries_no_email_and_no_domain(client, resolve_instance_spy, caplog):
    with caplog.at_level(logging.INFO, logger="engine-o.caller_binding"):
        _resolve_instance(client, _bearer(BOB), user_email=ALICE, entitled_domains=list(DIRECTORY[ALICE]))
    lines = [r.getMessage() for r in caplog.records if r.name == "engine-o.caller_binding"]
    assert len(lines) == 1 and lines[0].startswith("caller bound route=resolve_instance kind=person")
    assert "grants=1" in lines[0] and "body_identity=ignored" in lines[0]
    for needle in (ALICE, BOB, "example.com", "SUSTAINMENT", "FINANCE", "PLANNING"):
        assert needle.casefold() not in lines[0].casefold()


# =============================================================================================
# 8. THE CALLERS FORWARD THE CALLER'S OWN BEARER (never minted); a service run sends none
# =============================================================================================

def test_the_bff_enumerator_sends_the_callers_bearer(monkeypatch):
    from src.iagent import gateway as gw
    sent: list = []

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            sent.append((url, kw))
            return _Resp()

    monkeypatch.setattr(gw.httpx, "Client", _Client)
    gw._canvas_seed_enumerator(user_email=BOB, entitled_domains=["X"], bearer="tok-b")("urn:x#C")
    gw._canvas_seed_enumerator(user_email=BOB, entitled_domains=["X"])("urn:x#C")
    assert sent[0][1]["headers"] == {"Authorization": "Bearer tok-b"}
    assert not (sent[1][1].get("headers") or {}).get("Authorization")


def test_verb_lookup_sends_the_headers_it_is_given(monkeypatch):
    from iagent import verb_lookup as vl
    sent: list = []

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"verbs": []}

    monkeypatch.setattr(vl.requests, "post", lambda url, **kw: sent.append(kw) or _Resp())
    vl.find_compatible_verbs("urn:x#C", ["X"], ontology_url="http://o", on_behalf_of=BOB,
                             headers={"Authorization": "Bearer tok-b"})
    vl.find_compatible_verbs("urn:x#C", ["X"], ontology_url="http://o", on_behalf_of=BOB)
    assert sent[0]["headers"] == {"Authorization": "Bearer tok-b"}
    assert not sent[1].get("headers")


def test_the_gateway_route_intent_post_merges_the_callers_bearer():
    import ast
    src = (REPO / "src/iagent/gateway.py").read_text(encoding="utf-8")
    posts = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and any(isinstance(a, ast.JoinedStr) and "/route_intent" in ast.unparse(a) for a in n.args)]
    assert len(posts) == 1
    headers = next(k.value for k in posts[0].keywords if k.arg == "headers")
    text = ast.unparse(headers)
    assert "_trace_headers" in text and "Authorization" in text and "caller_token" in text, text
