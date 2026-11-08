"""INVARIANT 1 lives at the HTTP boundary, so it is tested there.

The vault's own tests prove the mechanism. This file proves the SURFACE — the part that
actually dispenses credentials over a network, where "locked to the supervisor's service
identity" either holds or does not.

WHY A SEPARATE FILE FROM THE VAULT'S: these two have different failure modes and different
blast radii. A vault bug loses a seed; an endpoint bug hands alice's token to whoever asked.
Keeping them apart means the second set can never be weakened by accident while someone is
adjusting the first.

Run:  uv run --frozen python -m pytest tests/identity/test_redemption_endpoint.py -q
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402

ALICE = "alice@example.com"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE-PING-ROOTED.signature"
RUN = "0f1e2d3c-run"


def _as(authz_id: str):
    """A caller identity, bypassed at the DEPENDENCY rather than by disabling auth — the
    route keeps its Depends(get_current_user), so removing that dependency stays a visible
    diff instead of a silently passing test."""
    return type("U", (), {
        "authz_id": authz_id, "id": authz_id, "sub": authz_id, "email": authz_id,
        "persona": None, "entitled_domains": [], "entitlement_source": "none",
    })()


@pytest.fixture
def client():
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fresh_vault():
    """A clean vault per test. Shared state between these tests would let a replay from one
    test read as a legitimate first redemption in another — the exact confusion invariant 2
    exists to prevent, reproduced in the harness."""
    from src.iagent.identity_vault import IdentityVault
    original = gateway.VAULT
    gateway.VAULT = IdentityVault()
    yield gateway.VAULT
    gateway.VAULT = original


def _login(authz_id: str):
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _as(authz_id)


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 1 — locked to the SUPERVISOR'S service identity, specifically
# ══════════════════════════════════════════════════════════════════════════════════

def test_the_supervisor_redeems_the_caller_token(client, fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:supervisor")

    r = client.post("/internal/identity/redeem", json={"run_id": RUN, "call_id": "c1"})

    assert r.status_code == 200
    assert r.json()["token"] == TOKEN, "what comes back must be alice's OWN token"


@pytest.mark.parametrize("impostor", [
    "svc:review-starter",   # another service — the sideways leak this pin names
    "svc:projector",
    ALICE,                  # even the token's OWN subject may not pull it back out
    "",                     # unidentified
])
def test_a_non_supervisor_caller_is_refused(client, fresh_vault, impostor):
    """NOT 'any authenticated service'. A second service redeeming a reference is the vault
    leaking sideways, and a generic is-authenticated check would permit exactly that.

    ``svc:review-starter`` is in this list on purpose: this repo has ALREADY shipped one
    confused deputy where a generally-named mint gave the supervisor that identity. If the
    gate were ever written as "a service account", that same client would pass it.
    """
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login(impostor)

    r = client.post("/internal/identity/redeem", json={"run_id": RUN, "call_id": "c1"})

    assert r.status_code == 403
    assert TOKEN not in r.text, "a refusal must not leak the credential in its body"


def test_a_refused_caller_does_NOT_consume_the_reference(client, fresh_vault):
    """An impostor must not be able to deny alice her seed by burning the reference.

    Invariant 1 is a gate on WHO, and it has to fail before invariant 2's single-use is
    reached — otherwise any unauthorized caller becomes a denial-of-service on the phrase
    path just by guessing run ids.
    """
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)

    _login("svc:review-starter")
    assert client.post("/internal/identity/redeem", json={"run_id": RUN, "call_id": "c1"}).status_code == 403

    _login("svc:supervisor")
    ok = client.post("/internal/identity/redeem", json={"run_id": RUN, "call_id": "c1"})
    assert ok.status_code == 200 and ok.json()["token"] == TOKEN


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 2 across the wire — a replay is a DIFFERENT status code, not a 404
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_replayed_call_is_409_and_a_miss_is_404(client, fresh_vault):
    """The discrimination the vault makes must survive the HTTP translation.

    Collapsing both into 404 at this layer would throw away, one hop from where it was
    carefully made, the single signal that distinguishes a compromised supervisor from a
    late retry.
    """
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:supervisor")

    assert client.post("/internal/identity/redeem", json={"run_id": RUN, "call_id": "c1"}).status_code == 200

    replay = client.post("/internal/identity/redeem", json={"run_id": RUN, "call_id": "c1"})
    miss = client.post("/internal/identity/redeem", json={"run_id": "never-stashed", "call_id": "c1"})

    assert replay.status_code == 409
    assert miss.status_code == 404
    assert replay.json()["detail"]["error"] == "already_redeemed"
    assert miss.json()["detail"]["error"] == "not_found"


def test_a_launcher_mismatch_is_refused_over_the_wire(client, fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:supervisor")

    r = client.post("/internal/identity/redeem",
                    json={"run_id": RUN, "call_id": "c1", "claimed_launcher": "mallory@example.com"})

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "launcher_mismatch"
    assert TOKEN not in r.text


def test_the_matching_launcher_passes_the_cross_check(client, fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:supervisor")

    r = client.post("/internal/identity/redeem",
                    json={"run_id": RUN, "call_id": "c1", "claimed_launcher": ALICE})

    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 6 — audited, including the refusals
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_refused_redemption_is_logged_loudly(client, fresh_vault, caplog):
    """A refused redemption is the MOST interesting line this endpoint can write."""
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:review-starter")

    with caplog.at_level(logging.INFO):
        client.post("/internal/identity/redeem", json={"run_id": RUN, "call_id": "c1"})

    assert "svc:review-starter" in caplog.text
    assert RUN in caplog.text


def test_no_response_or_log_leaks_the_token_on_any_refusal(client, fresh_vault, caplog):
    """One assertion over every refusal path at once. A credential that escapes through an
    error body or a log line is the same disclosure this design was built to avoid, arriving
    through a door nobody was watching."""
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)

    with caplog.at_level(logging.DEBUG):
        _login("svc:review-starter")
        bodies = [client.post("/internal/identity/redeem", json={"run_id": RUN, "call_id": "c1"}).text]
        _login("svc:supervisor")
        bodies.append(client.post("/internal/identity/redeem",
                                  json={"run_id": RUN, "call_id": "c1",
                                        "claimed_launcher": "mallory@x.com"}).text)
        bodies.append(client.post("/internal/identity/redeem",
                                  json={"run_id": RUN, "call_id": "c1"}).text)              # replay
        bodies.append(client.post("/internal/identity/redeem",
                                  json={"run_id": "nope", "call_id": "c1"}).text)           # miss

    for b in bodies:
        assert TOKEN not in b
    assert TOKEN not in caplog.text


# ══════════════════════════════════════════════════════════════════════════════════
# RULED 2026-11-03 — one reference per run, redeemed per CALL, no 600 s bound
# ══════════════════════════════════════════════════════════════════════════════════
import asyncio  # noqa: E402
import base64  # noqa: E402
import json  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from urllib.parse import parse_qs  # noqa: E402

import httpx  # noqa: E402

from src.iagent import identity_exchange  # noqa: E402
from src.iagent.identity_vault import IdentityVault  # noqa: E402

_NOW = 1_800_000_000.0


def _jwt(email: str = ALICE, exp: float = _NOW + 3600, tag: str = "x") -> str:
    def b(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    return f"{b({'alg': 'none'})}.{b({'email': email, 'sub': 'sub-' + email, 'exp': exp, 'jti': tag})}.sig"


def _redeem(client, call_id, run=RUN, **kw):
    return client.post("/internal/identity/redeem",
                       json={"run_id": run, "call_id": call_id, **kw})


def test_two_calls_with_two_ids_both_get_the_token_and_one_id_twice_is_409(
        client, fresh_vault, caplog):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:supervisor")
    assert _redeem(client, "plan/1").json()["token"] == TOKEN
    assert _redeem(client, "resolve/2").json()["token"] == TOKEN
    with caplog.at_level(logging.INFO):
        again = _redeem(client, "plan/1")
    assert again.status_code == 409 and again.json()["detail"]["error"] == "already_redeemed"
    assert any(r.levelno >= logging.ERROR and "plan/1" in r.getMessage() for r in caplog.records)
    assert TOKEN not in again.text and TOKEN not in caplog.text


def test_a_call_without_a_call_id_is_422_and_the_reference_is_untouched(client, fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:supervisor")
    assert client.post("/internal/identity/redeem", json={"run_id": RUN}).status_code == 422
    assert client.post("/internal/identity/redeem",
                       json={"run_id": RUN, "call_id": "  "}).status_code == 422
    assert _redeem(client, "c1").status_code == 200


def test_every_redemption_writes_one_audit_line_refusals_included(client, fresh_vault, caplog):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    with caplog.at_level(logging.DEBUG):
        _login("svc:supervisor")
        _redeem(client, "c1", leg="dispatch")
        _redeem(client, "c1", leg="dispatch")
        _redeem(client, "c2", run="absent")
        _login("svc:projector")
        _redeem(client, "c3")
    lines = [r.getMessage() for r in caplog.records
             if "identity_vault: redemption" in r.getMessage()
             or "REFUSED redemption" in r.getMessage()]
    assert sum("outcome=ok" in m for m in lines) == 1
    assert sum("outcome=already_redeemed" in m for m in lines) == 1
    assert sum("outcome=not_found" in m for m in lines) == 1
    assert sum("REFUSED redemption" in m for m in lines) == 1
    assert TOKEN not in caplog.text


def test_a_run_older_than_600s_still_redeems_on_an_injected_clock(client):
    t = [1000.0]
    v = IdentityVault(clock=lambda: t[0], wall_clock=lambda: _NOW)
    gateway.VAULT = v
    v.stash(RUN, TOKEN, subject=ALICE)
    t[0] += 3000.0
    _login("svc:supervisor")
    assert _redeem(client, "c1").status_code == 200


@pytest.fixture
def seam_unset(monkeypatch):
    for k in ("IDENTITY_EXCHANGE_TOKEN_URL", "IDENTITY_EXCHANGE_CLIENT_ID",
              "IDENTITY_EXCHANGE_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)


def _near_expiry_vault(token):
    v = IdentityVault(wall_clock=lambda: _NOW, refresh_margin_seconds=60)
    gateway.VAULT = v
    v.stash(RUN, token, subject=ALICE)
    return v


def test_near_expiry_with_the_seam_unset_pauses_and_never_returns_the_token(
        client, seam_unset, caplog, monkeypatch):
    monkeypatch.setattr(identity_exchange.time, "time", lambda: _NOW)
    old = _jwt(exp=_NOW + 10, tag="old")
    v = _near_expiry_vault(old)
    _login("svc:supervisor")
    with caplog.at_level(logging.DEBUG):
        r = _redeem(client, "c1")
    assert r.status_code == 409 and r.json()["detail"]["error"] == "awaiting_reauth"
    assert old not in r.text and old not in caplog.text
    assert v.state(RUN) == "awaiting_reauth"


@pytest.fixture
def keycloak_double(monkeypatch):
    """A real httpx client over a MockTransport: the handler answers with a real
    httpx.Response. ``box['answer']`` is what the realm says; ``box['seen']`` is every
    request form."""
    monkeypatch.setenv("IDENTITY_EXCHANGE_TOKEN_URL", "http://realm.invalid/token")
    monkeypatch.setenv("IDENTITY_EXCHANGE_CLIENT_ID", "gw")
    monkeypatch.setenv("IDENTITY_EXCHANGE_CLIENT_SECRET", "not-a-real-secret")
    monkeypatch.setattr(identity_exchange.time, "time", lambda: _NOW)
    box = {"seen": [], "answer": None, "status": 200}

    async def handler(request: httpx.Request) -> httpx.Response:
        box["seen"].append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        await asyncio.sleep(0.15)  # long enough for a second redeem to arrive meanwhile
        return httpx.Response(box["status"], json={"access_token": box["answer"]})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        identity_exchange.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return box


def test_two_concurrent_redeems_make_one_exchange_and_both_get_the_new_token(
        client, keycloak_double):
    old = _jwt(exp=_NOW + 10, tag="old")
    fresh = _jwt(exp=_NOW + 3600, tag="fresh")
    keycloak_double["answer"] = fresh
    _near_expiry_vault(old)
    _login("svc:supervisor")
    with ThreadPoolExecutor(2) as ex:
        futs = [ex.submit(_redeem, client, "c1"), ex.submit(_redeem, client, "c2")]
        a, b = [f.result() for f in futs]
    assert a.status_code == b.status_code == 200
    assert a.json()["token"] == b.json()["token"] == fresh
    assert len(keycloak_double["seen"]) == 1, "single flight: ONE exchange for two redeems"
    form = keycloak_double["seen"][0]
    assert form["subject_token"] == old
    assert "requested_subject" not in form, "impersonation is ruled out"
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"


@pytest.mark.parametrize("answer_kw", [
    dict(email="mallory@example.com", exp=_NOW + 3600),   # a different person
    dict(email=ALICE, exp=_NOW + 5),                       # does not outlive the old one
])
def test_a_wrong_subject_or_no_later_exp_is_refused_into_awaiting_reauth(
        client, keycloak_double, answer_kw):
    old = _jwt(exp=_NOW + 10, tag="old")
    keycloak_double["answer"] = _jwt(tag="bad", **answer_kw)
    v = _near_expiry_vault(old)
    _login("svc:supervisor")
    r = _redeem(client, "c1")
    assert r.status_code == 409 and r.json()["detail"]["error"] == "awaiting_reauth"
    assert keycloak_double["answer"] not in r.text
    assert v.state(RUN) == "awaiting_reauth"


def test_a_failed_exchange_is_awaiting_reauth_not_a_token(client, keycloak_double):
    keycloak_double["status"], keycloak_double["answer"] = 400, None
    old = _jwt(exp=_NOW + 10)
    _near_expiry_vault(old)
    _login("svc:supervisor")
    r = _redeem(client, "c1")
    assert r.status_code == 409 and old not in r.text


# ── the reauth door ─────────────────────────────────────────────────────────────────

def _reauth_as(authz_id, token):
    _login(authz_id)
    gateway.app.dependency_overrides[gateway.oauth2_scheme] = lambda: token


def test_the_reauth_door_resumes_a_paused_run_and_never_echoes_the_token(
        client, seam_unset, monkeypatch, caplog):
    monkeypatch.setattr(identity_exchange.time, "time", lambda: _NOW)
    v = _near_expiry_vault(_jwt(exp=_NOW + 10, tag="old"))
    _login("svc:supervisor")
    assert _redeem(client, "c1").status_code == 409
    fresh = _jwt(exp=_NOW + 3600, tag="fresh")
    _reauth_as(ALICE, fresh)
    with caplog.at_level(logging.DEBUG):
        r = client.post(f"/orchestrate/{RUN}/reauth")
    assert r.status_code == 200 and r.json() == {"state": "live"}
    assert fresh not in r.text and fresh not in caplog.text
    _login("svc:supervisor")
    assert _redeem(client, "c2").json()["token"] == fresh
    assert v.state(RUN) == "live"


def test_the_wrong_person_and_an_absent_run_answer_identically(client, fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _reauth_as("mallory@example.com", _jwt(email="mallory@example.com"))
    wrong = client.post(f"/orchestrate/{RUN}/reauth")
    absent = client.post("/orchestrate/no-such-run/reauth")
    assert wrong.status_code == absent.status_code == 404
    assert wrong.json() == absent.json()
    _login("svc:supervisor")  # and the run still holds ALICE's token
    assert _redeem(client, "c1").json()["token"] == TOKEN


def test_a_service_token_is_refused_at_the_reauth_door(client, fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _reauth_as("svc:supervisor", "svc-token")
    assert client.post(f"/orchestrate/{RUN}/reauth").status_code == 403
    _login("svc:supervisor")
    assert _redeem(client, "c1").json()["token"] == TOKEN
