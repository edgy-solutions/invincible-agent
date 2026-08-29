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

    r = client.post("/internal/identity/redeem", json={"run_id": RUN})

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

    r = client.post("/internal/identity/redeem", json={"run_id": RUN})

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
    assert client.post("/internal/identity/redeem", json={"run_id": RUN}).status_code == 403

    _login("svc:supervisor")
    ok = client.post("/internal/identity/redeem", json={"run_id": RUN})
    assert ok.status_code == 200 and ok.json()["token"] == TOKEN


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 2 across the wire — a replay is a DIFFERENT status code, not a 404
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_replay_is_409_and_a_miss_is_404(client, fresh_vault):
    """The discrimination the vault makes must survive the HTTP translation.

    Collapsing both into 404 at this layer would throw away, one hop from where it was
    carefully made, the single signal that distinguishes a compromised supervisor from a
    late retry.
    """
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:supervisor")

    assert client.post("/internal/identity/redeem", json={"run_id": RUN}).status_code == 200

    replay = client.post("/internal/identity/redeem", json={"run_id": RUN})
    miss = client.post("/internal/identity/redeem", json={"run_id": "never-stashed"})

    assert replay.status_code == 409
    assert miss.status_code == 404
    assert replay.json()["detail"]["error"] == "already_redeemed"
    assert miss.json()["detail"]["error"] == "not_found"


def test_a_launcher_mismatch_is_refused_over_the_wire(client, fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:supervisor")

    r = client.post("/internal/identity/redeem",
                    json={"run_id": RUN, "claimed_launcher": "mallory@example.com"})

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "launcher_mismatch"
    assert TOKEN not in r.text


def test_the_matching_launcher_passes_the_cross_check(client, fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:supervisor")

    r = client.post("/internal/identity/redeem",
                    json={"run_id": RUN, "claimed_launcher": ALICE})

    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 6 — audited, including the refusals
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_refused_redemption_is_logged_loudly(client, fresh_vault, caplog):
    """A refused redemption is the MOST interesting line this endpoint can write."""
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    _login("svc:review-starter")

    with caplog.at_level(logging.INFO):
        client.post("/internal/identity/redeem", json={"run_id": RUN})

    assert "svc:review-starter" in caplog.text
    assert RUN in caplog.text


def test_no_response_or_log_leaks_the_token_on_any_refusal(client, fresh_vault, caplog):
    """One assertion over every refusal path at once. A credential that escapes through an
    error body or a log line is the same disclosure this design was built to avoid, arriving
    through a door nobody was watching."""
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)

    with caplog.at_level(logging.DEBUG):
        _login("svc:review-starter")
        bodies = [client.post("/internal/identity/redeem", json={"run_id": RUN}).text]
        _login("svc:supervisor")
        bodies.append(client.post("/internal/identity/redeem",
                                  json={"run_id": RUN,
                                        "claimed_launcher": "mallory@x.com"}).text)
        bodies.append(client.post("/internal/identity/redeem",
                                  json={"run_id": RUN}).text)              # replay
        bodies.append(client.post("/internal/identity/redeem",
                                  json={"run_id": "nope"}).text)           # miss

    for b in bodies:
        assert TOKEN not in b
    assert TOKEN not in caplog.text
