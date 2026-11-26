"""Engine O's /enumerate_instances fan-out carries the PERSON, as themselves (ruled 2026-11-19, Q2, architect).

THE RULING: for providers other than its own, engine O "relays the person's own verified bearer,
captured from the request it received. Conditions: relayed only to registered provider endpoints, for
that request; never logged, never stored; an expired token is refused by the provider and reported as
an expired session, never served as an anonymous answer." `/resolve`'s fan-out (`_call_resolver`) did
this; `/enumerate_instances` posted to the same kind of provider with NO headers, so the provider saw
no caller. THE PAIR: fin's bearer-first provider-side read lands with this change; this is the sender.

A provider's 401/403 on the relayed token is a refusal of the PERSON's session: the fan-out halts and
the route answers 401 `session_expired` / `caller_refused`, never folded into `declined`/`empty`/
`no_provider` and never answered from the other providers. (Engine O only, as ordered 11-25: the
BFF's handling of that 401 is not changed here.)

Arms 1-9 call the route function with an `httpx.MockTransport` that records every request, a set
`current_caller()` and the inbound-bearer ContextVar. Arm 10 is the real app with a real RS256 token.

Run: LOCKED_SDK=no_overlay_venv_is_0920 .venv/Scripts/python.exe <locked_pytest.py> <log> tests/routing/test_enumerate_fanout_carries_the_person.py -q
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import jwt
import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from iagent_mesh import transport_auth as ta
from iagent_mesh.transport_auth import CallerIdentity

from agent_fleet.ontology_service import main as eo

from tests.routing.test_engine_o_binds_the_verified_caller import (  # noqa: F401
    AUD, ISS, _KEY_GOOD, mesh,
)

ALICE, BOB, SVC = "alice@example.com", "bob@example.com", "svc:engine-a"
TOKEN = "tok-alice-0123456789-secret"
BOB_TOKEN = "tok-bob-9876543210-secret"
REAL_ASYNC_CLIENT = httpx.AsyncClient
URL_X, URL_Y = "http://provider-x.invalid/enumerate", "http://provider-y.invalid/enumerate"
ROW_X = {"provider": "provider_x", "endpoint_url": URL_X, "timeout_s": 2.0}
ROW_Y = {"provider": "provider_y", "endpoint_url": URL_Y, "timeout_s": 2.0}
MEMBER = {"instance_id": "http://x/i1", "label": "Thing"}
CLASS = "http://x/C"
EXPIRED_403 = {"detail": "transport auth failed: invalid: ExpiredSignatureError"}
AUDIENCE_403 = {"detail": "transport auth failed: invalid: InvalidAudienceError"}
PERSON = CallerIdentity(ALICE, True, "verified", {"exp": time.time() + 600})
BOB_ID = CallerIdentity(BOB, True, "verified", {"exp": time.time() + 600})


class _HttpxProxy:
    def __init__(self, handler, seen):
        def factory(*a, timeout=None, **kw):
            def record(request):
                seen.append(request)
                return handler(request)
            return REAL_ASYNC_CLIENT(transport=httpx.MockTransport(record), timeout=timeout)
        self.AsyncClient = factory

    def __getattr__(self, name):
        return getattr(httpx, name)


def _members_handler(request):
    return httpx.Response(200, json={"outcome": "members", "members": [MEMBER], "count": 1,
                                     "scoped_by": []})


def _empty_handler(request):
    return httpx.Response(200, json={"outcome": "empty", "members": [], "count": 0})


@pytest.fixture()
def world(monkeypatch):
    """`world(handler, rows)` -> (requests seen, discovery-call list). Stores are doubles."""
    def install(handler=_members_handler, rows=(ROW_X,)):
        seen: list = []
        calls: list = []
        monkeypatch.setattr(eo, "httpx", _HttpxProxy(handler, seen))
        monkeypatch.setattr(eo, "_discover_enumerate_providers",
                            lambda refresh=False: (calls.append(1), eo.MeshResult.answered(list(rows)))[1])

        async def _pass(candidates, *, user_email, entitled_domains):
            return candidates
        monkeypatch.setattr(eo, "_filter_sustainment_candidates", _pass)
        monkeypatch.setattr(eo, "_held_domains_of", lambda subject: ("D1",))
        return seen, calls
    return install


def _caller(monkeypatch, identity):
    monkeypatch.setattr(eo, "_current_caller", lambda: identity)


def _enum(*, bearer=TOKEN, user=ALICE):
    async def go():
        eo._INBOUND_BEARER.set(bearer)
        return await eo.enumerate_instances(
            eo.EnumerateInstancesRequest(class_uri=CLASS, user_email=user))
    out = asyncio.run(go())
    if isinstance(out, JSONResponse):
        return out.status_code, json.loads(out.body)
    return 200, out


# =========================================================================================
# 1-3. WHO RECEIVES THE BEARER
# =========================================================================================

def test_1_a_verified_person_is_relayed_as_themselves_and_the_body_is_unchanged(monkeypatch, world):
    seen, _ = world(rows=(ROW_X, ROW_Y), handler=_empty_handler)
    _caller(monkeypatch, PERSON)
    status, out = _enum()
    assert status == 200 and out["outcome"] == "empty"
    assert len(seen) == 2
    for req in seen:
        assert req.headers["Authorization"] == "Bearer " + TOKEN
        assert json.loads(req.content) == {"class_uri": CLASS, "bound_slots": {}, "user_email": ALICE,
                                           "entitled_domains": ["D1"]}


def test_2_a_verified_service_relays_nothing(monkeypatch, world):
    seen, _ = world()
    svc = CallerIdentity(SVC, True, "verified", {"exp": time.time() + 600})
    _caller(monkeypatch, svc)
    eo._INBOUND_BEARER.set(TOKEN)   # the service HAS a bearer in this request; it must still not relay
    assert eo._relay_authorization() == ("none", {})
    status, out = _enum(user=ALICE)
    # a service is never a person: _bound makes the subject the service, the route refuses
    assert status == 422 and out["error"] == "no_person"
    assert not seen, "no provider request, so no Authorization header can have been sent"


@pytest.mark.parametrize("identity", [None, CallerIdentity(None, False, "absent"),
                                      CallerIdentity(ALICE, False, "no-verification-key")])
def test_3_an_unverified_caller_binds_anonymous_and_relays_nothing(monkeypatch, world, identity):
    seen, calls = world()
    _caller(monkeypatch, identity)
    eo._INBOUND_BEARER.set(TOKEN)   # a bearer is present; an unverified caller still relays nothing
    assert eo._relay_authorization() == ("none", {})
    status, out = _enum(user=ALICE)
    assert status == 422 and out["error"] == "no_person"
    assert not seen and not calls


# =========================================================================================
# 4. A BODY NAMING A PERSON IS NOT A PERSON
# =========================================================================================

def test_4_a_body_naming_alice_with_no_bearer_and_no_caller_is_refused_and_asks_nobody(monkeypatch, world):
    seen, calls = world()
    _caller(monkeypatch, None)
    status, out = _enum(bearer="", user=ALICE)
    assert status == 422 and out["error"] == "no_person"
    assert not seen and not calls


def test_4b_bob_with_bobs_token_and_a_body_naming_alice_sends_bob_never_alice(monkeypatch, world):
    seen, _ = world()
    _caller(monkeypatch, BOB_ID)
    status, _out = _enum(bearer=BOB_TOKEN, user=ALICE)
    assert status == 200
    (req,) = seen
    assert req.headers["Authorization"] == "Bearer " + BOB_TOKEN
    body = json.loads(req.content)
    assert body["user_email"] == BOB
    assert ALICE not in req.content.decode() and TOKEN not in req.headers["Authorization"]


# =========================================================================================
# 5. AN EXPIRED SESSION MAKES NO CALL, NOT EVEN A REGISTRY READ
# =========================================================================================

def test_5_an_expired_person_is_a_401_with_no_registry_read_and_no_request(monkeypatch, world):
    seen, calls = world()
    _caller(monkeypatch, CallerIdentity(ALICE, True, "verified", {"exp": time.time() - 5}))
    status, out = _enum(user=ALICE)
    assert status == 401 and out["reason"] == "session_expired" and out["message"]
    assert not seen, "an expired session must reach no provider"
    assert not calls, "an expired session must not read the registry"


def test_5b_an_sdk_expired_token_is_a_401_session_expired_before_the_bind(monkeypatch, world):
    # The SDK leaves an expired token UNVERIFIED, so `_bound` alone would bind it anonymous and answer
    # 422 `no_person`. Ruled 11-19 Q2 (3): an expired token is reported as an expired session. The
    # route checks expiry before the bind, as `/resolve_instance` does.
    seen, calls = world()
    _caller(monkeypatch, CallerIdentity(None, False, "invalid: ExpiredSignatureError"))
    assert eo._relay_authorization() == ("expired", {})
    status, out = _enum(user=ALICE)
    assert status == 401 and out["reason"] == "session_expired"
    assert not seen and not calls


# =========================================================================================
# 6-7. A PROVIDER REFUSING THE RELAYED TOKEN HALTS THE FAN-OUT
# =========================================================================================

def _x_answers(status, body):
    """Provider X answers `status` with `body`; every other provider answers members, so a fan-out
    that went on past X's refusal would come back `members`, not the refusal."""
    def handler(request):
        if str(request.url) == URL_X:
            return httpx.Response(status, json=body)
        return _members_handler(request)
    return handler


def test_6_a_provider_401_is_session_expired_halts_and_is_never_no_provider_or_empty(monkeypatch, world):
    seen, _ = world(handler=_x_answers(401, {"reason": "session_expired"}), rows=(ROW_X, ROW_Y))
    _caller(monkeypatch, PERSON)
    status, out = _enum()
    assert status == 401 and out["reason"] == "session_expired"
    assert out["message"] == eo._PERSON_TOKEN_REFUSAL_DETAIL["session_expired"]
    assert "outcome" not in out
    assert [str(r.url) for r in seen] == [URL_X], "the second provider must never be asked"


def test_7_a_provider_403_on_the_relayed_token_is_caller_refused_or_expired(monkeypatch, world):
    seen, _ = world(handler=_x_answers(403, AUDIENCE_403), rows=(ROW_X, ROW_Y))
    _caller(monkeypatch, PERSON)
    status, out = _enum()
    assert status == 401 and out["reason"] == "caller_refused"
    assert out["message"] == eo._PERSON_TOKEN_REFUSAL_DETAIL["caller_refused"]
    assert [str(r.url) for r in seen] == [URL_X]
    seen2, _ = world(handler=_x_answers(403, EXPIRED_403), rows=(ROW_X, ROW_Y))
    status, out = _enum()
    assert status == 401 and out["reason"] == "session_expired"
    assert [str(r.url) for r in seen2] == [URL_X]


def test_7b_control_with_nothing_relayed_a_provider_403_is_not_the_persons_refusal(monkeypatch, world):
    seen, _ = world(handler=_x_answers(403, AUDIENCE_403), rows=(ROW_X, ROW_Y))
    _caller(monkeypatch, PERSON)
    monkeypatch.setattr(eo, "_relay_authorization", lambda: ("none", {}))
    status, out = _enum()
    assert status == 200 and out["outcome"] == "members"
    assert {str(r.url) for r in seen} == {URL_X, URL_Y}


# =========================================================================================
# 8. THE TOKEN NEVER LEAKS
# =========================================================================================

def test_8_the_token_is_in_no_output_log_or_body(monkeypatch, world, capsys, caplog):
    caplog.set_level(0)
    _caller(monkeypatch, PERSON)
    returned = []
    for handler in (_members_handler,
                    lambda r: httpx.Response(401, json={"echo": r.headers.get("authorization")}),
                    lambda r: httpx.Response(403, text=r.headers.get("authorization", "")
                                             + " transport auth failed: invalid: InvalidAudienceError")):
        world(handler=handler, rows=(ROW_X, ROW_Y))
        returned.append(_enum())

    def boom(request):
        raise httpx.ConnectError("connect failed carrying " + request.headers["authorization"])
    world(handler=boom, rows=(ROW_X,))
    returned.append(_enum())
    assert TOKEN not in repr(returned)
    cap = capsys.readouterr()
    assert TOKEN not in cap.out and TOKEN not in cap.err
    assert all(TOKEN not in r.getMessage() and TOKEN not in str(r.__dict__) for r in caplog.records)


# =========================================================================================
# 9. ONLY REGISTERED ENDPOINTS, PER REQUEST
# =========================================================================================

def test_9_only_registered_endpoints_and_nothing_is_cached_between_requests(monkeypatch, world):
    seen, _ = world(handler=_empty_handler, rows=(ROW_X, ROW_Y))
    _caller(monkeypatch, PERSON)
    _enum()
    assert {str(r.url) for r in seen} == {URL_X, URL_Y}
    assert all("authorization" in r.headers for r in seen)
    n = len(seen)
    _caller(monkeypatch, PERSON)
    _enum(bearer="")
    assert len(seen) > n
    assert all("authorization" not in r.headers for r in seen[n:]), "a bearer was kept from the last request"


# =========================================================================================
# 10. END TO END THROUGH THE REAL APP, REAL RS256 TOKEN
# =========================================================================================

def _mint(subject, *, exp_in=600):
    return jwt.encode({"iss": ISS, "aud": AUD, "exp": int(time.time()) + exp_in,
                       ta._entitlement_claim(): subject}, _KEY_GOOD, algorithm="RS256")


def test_10_the_real_app_relays_exactly_the_signed_bearer_it_received(monkeypatch, world):
    seen, calls = world()
    header = "Bearer " + _mint(ALICE)
    r = TestClient(eo.app).post("/enumerate_instances", json={"class_uri": CLASS, "user_email": ALICE},
                                headers={"Authorization": header})
    assert r.status_code == 200 and r.json()["outcome"] == "members"
    (req,) = seen
    assert req.headers["Authorization"] == header
    assert json.loads(req.content)["user_email"] == ALICE
    n = len(seen)
    expired = TestClient(eo.app).post("/enumerate_instances", json={"class_uri": CLASS, "user_email": ALICE},
                                      headers={"Authorization": "Bearer " + _mint(ALICE, exp_in=-30)})
    # (see 5b: a real expired token reaches the person as an expired session, not as no person)
    assert expired.status_code == 401 and expired.json()["reason"] == "session_expired"
    assert len(seen) == n
