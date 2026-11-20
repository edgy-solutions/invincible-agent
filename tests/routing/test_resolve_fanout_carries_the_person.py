"""Engine O's /resolve fan-out carries the PERSON, as themselves (ruled 2026-11-19, Q2, architect).

THE RULING: "Engine O answers its own provider in-process. For other providers it relays the person's
own verified bearer, captured from the request it received. Conditions: relayed only to registered
provider endpoints, for that request; never logged, never stored; an expired token is refused by the
provider and reported as an expired session, never served as an anonymous answer; FORWARD is retired
for bound routes with the header-drop seal. [...] Declared delegation stays for calls with no live
person token, as ruled in 1b."

Arms 1-8 drive `_call_resolver` / `_resolve_instance` with an `httpx.MockTransport` that records every
request, a set `current_caller()` and the inbound-bearer ContextVar. Arms 9-10 go through the real app
with real RS256 tokens (the harness of `test_engine_o_binds_the_verified_caller.py`). Arm 10 is the
end-to-end arm: the real fan-out, the in-process provider and the origin gate, with only the stores and
the registry as doubles. No existing route reaches `_resolve_instance` without a model call, so the
arm adds ONE probe route to the real app (same app-level dependencies, so the real SDK verification and
bearer capture run) that does what `/fill_slots` does first: `_bound`, then `_resolve_instance`.

Run: LOCKED_SDK=no_overlay_venv_is_0920 .venv/Scripts/python.exe <locked_pytest.py> <log> tests/routing/test_resolve_fanout_carries_the_person.py -q
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from iagent_mesh import transport_auth as ta
from iagent_mesh.transport_auth import CallerIdentity

from agent_fleet.ontology_service import main as eo

# The signed-token harness, REUSED (keys, issuer, audience, JWKS double; `mesh` is autouse there).
from tests.routing.test_engine_o_binds_the_verified_caller import (  # noqa: F401
    AUD, ISS, _KEY_GOOD, mesh,
)

ALICE, BOB, SVC = "alice@example.com", "bob@example.com", "svc:engine-a"
TOKEN = "tok-alice-0123456789-secret"
REAL_ASYNC_CLIENT = httpx.AsyncClient
URL_X, URL_Y = "http://provider-x.invalid/resolve_instance", "http://provider-y.invalid/resolve_instance"
ROW_X = {"provider": "provider_x", "endpoint_url": URL_X, "timeout_s": 2.0, "domains": []}
ROW_Y = {"provider": "provider_y", "endpoint_url": URL_Y, "timeout_s": 2.0, "domains": []}
ROW_SELF = {"provider": eo._SELF_RESOLVE_PROVIDER, "endpoint_url": "http://self.invalid/resolve_instance",
            "timeout_s": 2.0, "domains": []}
CAND = {"instance_id": "http://x/i1", "class_uri": "http://x/C", "label": "Thing", "score": 1.0,
        "matched_on": "id"}


# -- doubles ---------------------------------------------------------------------------------------

class _HttpxProxy:
    """`eo.httpx` with `AsyncClient` swapped for one on a MockTransport; everything else is real."""

    def __init__(self, handler, seen):
        def factory(*a, timeout=None, **kw):
            def record(request):
                seen.append(request)
                return handler(request)
            return REAL_ASYNC_CLIENT(transport=httpx.MockTransport(record), timeout=timeout)
        self.AsyncClient = factory

    def __getattr__(self, name):
        return getattr(httpx, name)


@pytest.fixture()
def net(monkeypatch):
    """`net(handler)` -> the list of requests the fan-out made."""
    def install(handler=lambda request: httpx.Response(200, json={"candidates": [CAND]})):
        seen: list = []
        monkeypatch.setattr(eo, "httpx", _HttpxProxy(handler, seen))
        return seen
    return install


def _caller(monkeypatch, identity):
    monkeypatch.setattr(eo, "_current_caller", lambda: identity)


PERSON = CallerIdentity(ALICE, True, "verified", {"exp": time.time() + 600})


def _run(coro_fn, *, bearer=TOKEN):
    async def go():
        eo._INBOUND_BEARER.set(bearer)
        return await coro_fn()
    return asyncio.run(go())


def _call(row, **kw):
    return _run(lambda: eo._call_resolver(row, "PN-1", "q", user_email=ALICE,
                                          entitled_domains=["SUSTAINMENT"]), **kw)


def _fanout(rows, monkeypatch, **kw):
    monkeypatch.setattr(eo, "_discover_instance_resolvers",
                        lambda refresh=False: eo.MeshResult.answered(list(rows)))
    return _run(lambda: eo._resolve_instance("PN-1", "q", ["SUSTAINMENT"], user_email=ALICE,
                                             entitled_domains=["SUSTAINMENT"]), **kw)


# =========================================================================================
# 1-3. WHO RECEIVES THE BEARER
# =========================================================================================

def test_1_a_verified_person_is_relayed_as_themselves_and_the_body_is_unchanged(monkeypatch, net):
    seen = net()
    _caller(monkeypatch, PERSON)
    out = _call(ROW_X)
    assert out.status == "ok" and [c.instance_id for c in out.candidates] == ["http://x/i1"]
    (req,) = seen
    assert str(req.url) == URL_X
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    import json
    assert json.loads(req.content) == {"identifier": "PN-1", "query": "q", "user_email": ALICE,
                                       "entitled_domains": ["SUSTAINMENT"]}


def test_2_a_verified_service_relays_nothing_declared_delegation_stays(monkeypatch, net):
    seen = net()
    _caller(monkeypatch, CallerIdentity(SVC, True, "verified", {"exp": time.time() + 600}))
    _call(ROW_X)
    (req,) = seen
    assert "authorization" not in req.headers, "a service's own token must not be relayed as a person's"


@pytest.mark.parametrize("identity", [
    None,
    CallerIdentity(None, False, "absent"),
    CallerIdentity(ALICE, False, "no-verification-key"),   # a CLAIMED person: unverified
    CallerIdentity(None, False, "invalid: InvalidSignatureError"),
])
def test_3_an_unverified_or_absent_caller_relays_nothing(monkeypatch, net, identity):
    seen = net()
    _caller(monkeypatch, identity)
    _call(ROW_X)
    (req,) = seen
    assert "authorization" not in req.headers


def test_3b_no_inbound_token_relays_nothing_even_for_a_verified_person(monkeypatch, net):
    seen = net()
    _caller(monkeypatch, PERSON)
    _call(ROW_X, bearer="")
    assert "authorization" not in seen[0].headers


# =========================================================================================
# 4. AN EXPIRED SESSION MAKES NO CALL AND IS NEVER ANSWERED ANONYMOUSLY
# =========================================================================================

EXPIRED_REASON = CallerIdentity(None, False, "invalid: ExpiredSignatureError")
EXPIRED_CLAIMS = CallerIdentity(ALICE, True, "verified", {"exp": time.time() - 5})


@pytest.mark.parametrize("identity", [EXPIRED_REASON, EXPIRED_CLAIMS], ids=["reason", "past-exp-claim"])
def test_4_an_expired_token_makes_no_http_request_and_reports_an_expired_session(monkeypatch, net, identity):
    seen = net()
    ran = []

    async def _self(request):
        ran.append(request)
        return {"candidates": []}

    monkeypatch.setattr(eo, "resolve_instance", _self)
    _caller(monkeypatch, identity)
    out = _call(ROW_X)
    assert out.status == "session_expired" and not seen
    prov = _fanout([ROW_X, ROW_Y, ROW_SELF], monkeypatch)[1]
    assert not seen and not ran, "an expired session must reach NO provider, engine O's own included"
    assert prov["instance_match"] == "session_expired" and prov["instance_resolved"] is False
    assert prov["instance_n"] == 0


# =========================================================================================
# 5. A PROVIDER'S 401 IS AN EXPIRED SESSION, AND THE OTHERS' ANSWERS ARE NOT USED
# =========================================================================================

def test_5_a_provider_401_is_session_expired_not_error_and_poisons_the_fanout(monkeypatch, net):
    def handler(request):
        if str(request.url) == URL_X:
            return httpx.Response(401, json={"reason": "session_expired"})
        return httpx.Response(200, json={"candidates": [CAND]})

    seen = net(handler)
    _caller(monkeypatch, PERSON)
    assert _call(ROW_X).status == "session_expired"
    assert _call(ROW_Y).status == "ok"                 # control: the other provider answers
    subject, prov = _fanout([ROW_X, ROW_Y], monkeypatch)
    assert {str(r.url) for r in seen} >= {URL_X, URL_Y}   # Y WAS asked and DID answer
    assert subject is None
    assert prov["instance_match"] == "session_expired" and prov["instance_resolved"] is False
    assert "instance_id" not in prov, "the other provider's candidate must not resolve anything"


def test_5b_a_500_stays_an_error(monkeypatch, net):
    net(lambda request: httpx.Response(500))
    _caller(monkeypatch, PERSON)
    assert _call(ROW_X).status == "error"


# =========================================================================================
# 6. ENGINE O ANSWERS ITS OWN PROVIDER IN-PROCESS
# =========================================================================================

def test_6_the_self_provider_is_called_in_process_with_the_person_bound(monkeypatch, net):
    seen = net()
    got = []

    async def _spy(request):
        got.append((eo._current_caller().authz_id, request.identifier, request.user_email,
                    request.entitled_domains))
        return {"candidates": [CAND]}

    monkeypatch.setattr(eo, "resolve_instance", _spy)
    _caller(monkeypatch, PERSON)
    out = _call(ROW_SELF)
    assert not seen, "engine O's own provider must not be called over HTTP"
    assert got == [(ALICE, "PN-1", ALICE, ("SUSTAINMENT",))]
    assert out.status == "ok" and out.provider == eo._SELF_RESOLVE_PROVIDER
    assert [c.instance_id for c in out.candidates] == ["http://x/i1"]


@pytest.mark.parametrize("exc, status", [
    (HTTPException(status_code=502, detail="store down"), "error"),
    (HTTPException(status_code=503, detail="visibility down"), "error"),
    (RuntimeError("boom"), "error"),
    (HTTPException(status_code=401, detail="expired"), "session_expired"),
])
def test_6b_an_exception_from_the_in_process_handler_never_escapes(monkeypatch, net, exc, status):
    seen = net()

    async def _boom(request):
        raise exc

    monkeypatch.setattr(eo, "resolve_instance", _boom)
    _caller(monkeypatch, PERSON)
    assert _call(ROW_SELF).status == status
    assert not seen


# =========================================================================================
# 7. NEVER LOGGED
# =========================================================================================

def test_7_the_token_is_in_no_output_when_a_relayed_call_errors_or_times_out(monkeypatch, net, capsys, caplog):
    caplog.set_level(0)
    _caller(monkeypatch, PERSON)

    def leaky_error(request):  # an exception whose TEXT carries the request headers
        raise httpx.ConnectError(f"connect failed for {dict(request.headers)}", request=request)

    def leaky_timeout(request):
        raise httpx.ReadTimeout(f"timed out for {dict(request.headers)}", request=request)

    for handler, want in ((leaky_error, "error"), (leaky_timeout, "timeout"),
                          (lambda r: httpx.Response(500, text=str(dict(r.headers))), "error")):
        net(handler)
        assert _call(ROW_X).status == want
    out = capsys.readouterr()
    assert out.out.strip(), "the control: the failure paths do print something"
    assert TOKEN not in out.out and TOKEN not in out.err
    assert all(TOKEN not in r.getMessage() for r in caplog.records)
    assert all(TOKEN not in str(r.__dict__) for r in caplog.records)


def test_7b_the_token_is_in_no_provenance(monkeypatch, net):
    net()
    _caller(monkeypatch, PERSON)
    subject, prov = _fanout([ROW_X], monkeypatch)
    assert TOKEN not in repr(prov) and TOKEN not in repr(subject)


# =========================================================================================
# 8-9. THROUGH THE REAL APP: PER REQUEST, AND THE PROVIDER'S OWN EXPIRY REFUSAL
# =========================================================================================

def _mint(subject, *, exp_in=600, key=_KEY_GOOD):
    return jwt.encode({"iss": ISS, "aud": AUD, "exp": int(time.time()) + exp_in,
                       ta._entitlement_claim(): subject}, key, algorithm="RS256")


def _auth(subject, **kw):
    return {"Authorization": f"Bearer {_mint(subject, **kw)}"}


@pytest.fixture()
def probe(monkeypatch):
    """ONE route added to the REAL app: reports what the fan-out would relay for this request."""
    async def relay_probe():
        mode, headers = eo._relay_authorization()
        return {"mode": mode, "authorization": headers.get("Authorization", "")}

    async def fanout_probe(body: dict):
        class _R(BaseModel):
            user_email: str = ""
            entitled_domains: list[str] = []
        req, _ = await eo._bound(_R(user_email=body.get("user_email", ""),
                                    entitled_domains=body.get("entitled_domains", [])),
                                 route="resolve_instance")
        subject, prov = await eo._resolve_instance(
            body["identifier"], "q", list(req.entitled_domains),
            user_email=req.user_email, entitled_domains=list(req.entitled_domains))
        return {"subject": subject, "prov": prov}

    eo.app.add_api_route("/__probe_relay", relay_probe, methods=["GET"])
    eo.app.add_api_route("/__probe_fanout", fanout_probe, methods=["POST"])
    added = eo.app.router.routes[-2:]
    yield TestClient(eo.app)
    for r in added:
        eo.app.router.routes.remove(r)


def test_8_the_bearer_is_per_request_the_next_request_relays_nothing(probe):
    first = probe.get("/__probe_relay", headers=_auth(ALICE))
    assert first.json()["mode"] == "relay"
    assert first.json()["authorization"].startswith("Bearer ey")
    second = probe.get("/__probe_relay")                         # no Authorization at all
    assert second.json() == {"mode": "none", "authorization": ""}
    third = probe.get("/__probe_relay", headers=_auth(BOB))
    assert third.json()["authorization"] != first.json()["authorization"]
    assert probe.get("/__probe_relay").json()["mode"] == "none"


def test_8b_an_expired_signed_token_is_reported_expired_by_the_real_chain(probe):
    r = probe.get("/__probe_relay", headers=_auth(ALICE, exp_in=-30))
    assert r.json() == {"mode": "expired", "authorization": ""}


def _stub_provider_stores(monkeypatch):
    reads = []

    async def _rows(*a, **k):
        reads.append(1)
        return []

    async def _filter(candidates, *, user_email, entitled_domains):
        return candidates

    async def _chains(candidates):
        return candidates

    monkeypatch.setattr(eo, "execute_sparql", _rows)
    monkeypatch.setattr(eo, "_resolve_sustainment_candidates", lambda ident, rows: [{"instance_id": "i"}])
    monkeypatch.setattr(eo, "_filter_sustainment_candidates", _filter)
    monkeypatch.setattr(eo, "_attach_class_chains", _chains)
    return reads


def test_9_resolve_instance_refuses_an_expired_token_before_any_read_never_anonymous(monkeypatch):
    reads = _stub_provider_stores(monkeypatch)
    client = TestClient(eo.app)
    expired = client.post("/resolve_instance", json={"identifier": "x", "query": "x"},
                          headers=_auth(ALICE, exp_in=-30))
    assert expired.status_code == 401
    assert expired.json()["reason"] == "session_expired" and expired.json()["message"]
    assert not reads, "an expired session must be refused BEFORE the store is read"
    ok = client.post("/resolve_instance", json={"identifier": "x", "query": "x"}, headers=_auth(ALICE))
    assert ok.status_code == 200 and ok.json()["candidates"]
    assert reads, "the control: a valid token reaches the read"
    # a request with NO token is not an expired session: it keeps its existing (anonymous) answer
    assert client.post("/resolve_instance", json={"identifier": "x", "query": "x"}).status_code == 200


# =========================================================================================
# 10. END TO END: the real fan-out, the in-process provider, the origin gate
# =========================================================================================

NB = "http://internal/sustainment/doc/"
NOTICE_CLASS = "http://internal/sustainment/pcn#ProductChangeNotice"
OWNER = "SUSTAINMENT"
DROPPER, OTHER = "dropper@example.com", "other@example.com"
DROP_ID, SEEDED_ID = "PCN-D1", "PCN-S1"


@pytest.fixture()
def world(monkeypatch):
    """Engine O's own provider over a drop-derived notice (visible only to its dropper) and a seeded
    one (visible to all); one OTHER provider on a MockTransport that answers only a call carrying a
    person's bearer. The registry is stubbed to those two rows."""
    from tests.security.test_service_identity_is_never_a_grant import (
        TABLE, _Driver, _Jena, _drop_row, _seeded_row)
    monkeypatch.setattr(eo, "_load_domain_consumption_for_notice_parts", lambda: TABLE)
    monkeypatch.setattr(eo, "_notice_parts_can_view_program", lambda program, caller: True)
    monkeypatch.setattr(eo, "execute_sparql", _Jena([
        {"s": NB + DROP_ID, "type": NOTICE_CLASS}, {"s": NB + SEEDED_ID, "type": NOTICE_CLASS}]))
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", _Driver({
        DROP_ID: _drop_row(DROP_ID, dropper=DROPPER), SEEDED_ID: _seeded_row(SEEDED_ID)}))
    monkeypatch.setattr(eo, "_held_domains_of", lambda subject: (OWNER,))
    seen: list = []

    def other_provider(request):
        return httpx.Response(200, json={"candidates": []})

    monkeypatch.setattr(eo, "httpx", _HttpxProxy(other_provider, seen))
    monkeypatch.setattr(eo, "_discover_instance_resolvers", lambda refresh=False: eo.MeshResult.answered(
        [dict(ROW_SELF, domains=[OWNER]), ROW_Y]))
    return seen


def _resolve_as(probe, subject, identifier, *, claimed=None):
    headers = _auth(subject)
    r = probe.post("/__probe_fanout", json={"identifier": identifier, "user_email": claimed or subject},
                   headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["prov"], headers["Authorization"]


def test_10_a_person_resolves_their_own_drop_and_a_service_claiming_them_does_not(probe, world):
    mine, auth_mine = _resolve_as(probe, DROPPER, DROP_ID)
    assert mine["instance_resolved"] is True and mine["instance_id"] == NB + DROP_ID
    # THE HOLE FORWARD LEFT: a service that merely CLAIMS the dropper in the body. The verified
    # caller is a service, so no dropper exemption holds and no bearer is relayed.
    n = len(world)
    forged, _ = _resolve_as(probe, SVC, DROP_ID, claimed=DROPPER)
    assert forged["instance_resolved"] is False, "a body-claimed person must not resolve the drop"
    assert "authorization" not in world[n].headers, "a service's token is not relayed as a person's"
    # the control: seeded content is visible to the person and to the service through the same chain
    seeded, _ = _resolve_as(probe, DROPPER, SEEDED_ID)
    assert seeded["instance_resolved"] is True and seeded["instance_id"] == NB + SEEDED_ID
    # the OTHER provider was reached over HTTP carrying the person's OWN bearer, and only there
    assert world[0].headers.get("authorization") == auth_mine
    assert {str(r.url) for r in world} == {URL_Y}, "engine O's own provider must not be called over HTTP"
    # a person with an EXPIRED session resolves nothing, from either provider, and nothing is called
    n = len(world)
    r = probe.post("/__probe_fanout", json={"identifier": DROP_ID, "user_email": DROPPER},
                   headers=_auth(DROPPER, exp_in=-30))
    assert r.json()["prov"]["instance_match"] == "session_expired" and len(world) == n


# =========================================================================================
# G1-G5. A PROVIDER'S 403 ON A RELAYED TOKEN (gov hold 2026-11-20, Q2 condition 3)
# =========================================================================================

EXPIRED_403 = {"detail": "transport auth failed: invalid: ExpiredSignatureError"}
AUDIENCE_403 = {"detail": "transport auth failed: invalid: InvalidAudienceError"}


def _x_refuses(body, status=403):
    def handler(request):
        if str(request.url) == URL_X:
            return httpx.Response(status, json=body)
        return httpx.Response(200, json={"candidates": [CAND]})
    return handler


def test_g1_a_provider_403_naming_expiry_is_session_expired_and_poisons_the_fanout(monkeypatch, net):
    seen = net(_x_refuses(EXPIRED_403))
    _caller(monkeypatch, PERSON)
    assert _call(ROW_X).status == "session_expired"
    subject, prov = _fanout([ROW_X, ROW_Y], monkeypatch)
    assert {str(r.url) for r in seen} >= {URL_X, URL_Y}   # Y WAS asked and DID answer
    assert subject is None
    assert prov["instance_match"] == "session_expired" and prov["instance_resolved"] is False
    assert "instance_id" not in prov


def test_g2_any_other_relayed_403_is_caller_refused_and_halts_the_fanout(monkeypatch, net):
    seen = net(_x_refuses(AUDIENCE_403))
    _caller(monkeypatch, PERSON)
    assert _call(ROW_X).status == "caller_refused"
    subject, prov = _fanout([ROW_X, ROW_Y], monkeypatch)
    assert {str(r.url) for r in seen} >= {URL_X, URL_Y}
    assert subject is None and "instance_id" not in prov
    assert prov["instance_match"] == "caller_refused"
    assert prov["instance_detail"] == "a provider refused the person's token; sign in again"
    assert prov["instance_resolved"] is False and prov["instance_n"] == 0


def test_g2b_session_expired_wins_when_both_reasons_are_present(monkeypatch, net):
    def handler(request):
        if str(request.url) == URL_X:
            return httpx.Response(403, json=AUDIENCE_403)
        return httpx.Response(401, json={})
    net(handler)
    _caller(monkeypatch, PERSON)
    _, prov = _fanout([ROW_X, ROW_Y], monkeypatch)
    assert prov["instance_match"] == "session_expired"


def test_g3_control_a_service_caller_403_is_an_error_and_the_fanout_resolves_from_y(monkeypatch, net):
    seen = net(_x_refuses(EXPIRED_403))
    _caller(monkeypatch, CallerIdentity(SVC, True, "verified", {"exp": time.time() + 600}))
    assert _call(ROW_X, bearer="").status == "error"
    subject, prov = _fanout([ROW_X, ROW_Y], monkeypatch, bearer="")
    assert {str(r.url) for r in seen} >= {URL_X, URL_Y}
    assert prov["instance_match"] not in eo._PERSON_TOKEN_REFUSALS
    outcomes = {o["provider"]: o["status"] for o in prov["instance_provider_outcomes"]}
    assert outcomes == {"provider_x": "error", "provider_y": "ok"}
    assert prov["instance_n"] == 1, "Y's candidate is used, as for any error"


def test_g4_both_reasons_are_unknown_on_resolve_and_a_401_on_fill_slots():
    import ast
    for reason in eo._PERSON_TOKEN_REFUSALS:
        prov = eo._person_token_refusal_provenance(reason)
        r = eo._session_expired_resolution(prov, None)
        assert r.resolved_uri == "UNKNOWN" and r.provenance["instance_match"] == reason
        assert r.reasoning == eo._PERSON_TOKEN_REFUSAL_DETAIL[reason]
    assert (eo._session_expired_resolution(eo._person_token_refusal_provenance("caller_refused"), None).reasoning
            != eo._session_expired_resolution(eo._person_token_refusal_provenance("session_expired"), None).reasoning)
    # Driving /resolve and /fill_slots end to end needs the whole class-recall harness: the sites are
    # read by AST instead. Every `instance_match` comparison in engine O is against the tuple.
    src = open(eo.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    cmp_sites = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)
                 and any(isinstance(c, ast.Constant) and c.value == "session_expired" for c in n.comparators)
                 and "instance_match" in ast.dump(n.left) + ast.dump(n)]
    assert not cmp_sites, "a site compares instance_match to the single reason"
    resolve_sites = src.count('instance_provenance.get("instance_match") in _PERSON_TOKEN_REFUSALS')
    assert resolve_sites == 2, "both /resolve sites compare against the tuple"
    fill = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "fill_slots")
    seg = ast.get_source_segment(src, fill)
    assert "if outcome in _PERSON_TOKEN_REFUSALS" in seg and '"reason": outcome' in seg
    assert "status_code=401" in seg


def test_g5_the_token_is_in_no_output_for_a_refused_relayed_call(monkeypatch, net, capsys, caplog):
    caplog.set_level(0)
    _caller(monkeypatch, PERSON)
    for body in (EXPIRED_403, AUDIENCE_403):
        # the provider's body echoes the token: it must be neither printed nor kept
        net(lambda r, b=body: httpx.Response(403, json={**b, "echo": r.headers.get("authorization")}))
        _call(ROW_X)
        _fanout([ROW_X], monkeypatch)
    out = capsys.readouterr()
    assert TOKEN not in out.out and TOKEN not in out.err
    assert all(TOKEN not in r.getMessage() and TOKEN not in str(r.__dict__) for r in caplog.records)


def test_g11_sdk_tripwire_the_real_require_refusal_of_an_expired_token_is_classified_expired(monkeypatch):
    # The SDK has no structured code: REQUIRE raises HTTPException(403, "transport auth failed:
    # <reason>") with reason "invalid: <ExceptionName>". Engine O reads expiry from that text, so an
    # SDK rewording must turn this red. The structured code belongs to a later SDK release.
    from fastapi import Depends, FastAPI
    monkeypatch.setenv("REQUIRE_TRANSPORT_AUTH", "true")
    app = FastAPI()

    @app.get("/x", dependencies=[Depends(ta.make_transport_auth_dependency("g11"))])
    async def x():
        return {"ok": True}

    c = TestClient(app)
    ok = c.get("/x", headers=_auth(ALICE))
    assert ok.status_code == 200, "the control: a live signed token passes the same app"
    r = c.get("/x", headers=_auth(ALICE, exp_in=-30))
    assert r.status_code == 403
    assert r.json() == {"detail": "transport auth failed: invalid: ExpiredSignatureError"}
    assert eo._relayed_refusal_reason(r.status_code, r.text) == "session_expired"
    assert eo._relayed_refusal_reason(403, '{"detail": "transport auth failed: invalid: InvalidAudienceError"}') \
        == "caller_refused"
