"""SEAL 2 -- the originator comes from a verified token only.

Architect, overnight: "the originator comes from a verified token only".

The ORIGINATOR of a run is the person (or service) whose verified token started it. Everything that
later says "who" -- the run config the supervisor reads, the audit line, the vault entry the redeemed
token is read back from -- must derive from that token and from nothing the client typed.

HOW: the REAL `auth.get_current_user` runs (no dependency override). The only seam is
`auth.verified_claims`, the JWKS check itself: a token string the test minted verifies to a payload,
anything else raises like a bad signature. So "verified" means exactly what production means by it.
Then, for every carrier a client controls on `/orchestrate` (body fields, headers, query string,
cookies, even a second Authorization-shaped header), a FORGED originator is sent alongside the valid
token, and the assertions are on BEHAVIOUR at every place the originator lands:

  * the launch the route makes (`user_email`, `user_id`, `caller_token` handed to the run),
  * the audit line (`who=`),
  * the vault entry `_launch -> VAULT.stash(subject=...)` for the run,
  * and NOTHING with the forged value in any of them.

Carriers are not listed by field name: the forged value is planted under many names in every carrier
and the assertion is that it appears NOWHERE downstream. A bad token with forged carriers is refused
and launches nothing.

Run: uv run pytest tests/identity/test_the_originator_comes_from_a_verified_token_only.py -q
"""
from __future__ import annotations

import json
import logging

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import auth, gateway  # noqa: E402

LOGGER = "iagent.audit.orchestrate"
REAL = "alice.real@example.invalid"
SUB = "5b1c0a52-0000-4000-8000-00000000a11c"
CLIENT = "browser-client"
GOOD = "tok-alice-verified"
FORGED = "mallory.forged@example.invalid"
FORGED_SUB = "00000000-0000-4000-8000-0000000f0123"

_NAMES = ["user_email", "user_id", "user", "email", "sub", "authz_id", "originator", "launcher",
          "launched_by", "created_by", "submitted_by", "requested_by", "on_behalf_of", "actor",
          "caller", "principal", "x_user", "claimed_launcher", "subject"]
_HEADERS = ["X-User-Email", "X-User", "X-User-Id", "X-Forwarded-User", "X-Forwarded-Email",
            "X-Authenticated-User", "X-Auth-Request-Email", "X-Remote-User", "X-On-Behalf-Of",
            "X-Originator", "X-Launched-By", "X-Actor", "X-Authz-Id", "X-Caller",
            "X-Impersonate", "Remote-User"]


@pytest.fixture(autouse=True)
def _real_auth(monkeypatch):
    def verified(token):
        if token != GOOD:
            raise auth.jwt.InvalidTokenError("signature verification failed")
        return {"sub": SUB, "email": REAL, "azp": CLIENT, "realm_access": {"roles": []},
                "jti": "j-1", "exp": 4102444800}
    monkeypatch.setattr(auth, "verified_claims", verified)
    monkeypatch.setattr(auth, "_get_entitlement_cache", lambda: None)
    gateway.app.dependency_overrides.clear()
    yield
    gateway.app.dependency_overrides.clear()


class _Seen:
    def __init__(self):
        self.streams: list[dict] = []

    def blob(self) -> str:
        return json.dumps(self.streams, default=str)


@pytest.fixture
def seen(monkeypatch):
    s = _Seen()

    async def stream(request, **kw):
        s.streams.append(kw)
        yield "event: final_payload\ndata: {\"k\": 1}\n\n"
    monkeypatch.setattr(gateway, "generate_dagster_stream", stream)
    return s


def _lines(caplog):
    return [r.getMessage() for r in caplog.records
            if r.name == LOGGER and r.getMessage().startswith("orchestrate_access ")]


def _forged_request():
    body = {"message": "what is the state of pump 7", "session_id": "s-forge"}
    body.update({n: FORGED for n in _NAMES})
    body["user_id"] = FORGED_SUB
    headers = {"Authorization": f"Bearer {GOOD}"}
    headers.update({h: FORGED for h in _HEADERS})
    params = {n: FORGED for n in _NAMES}
    cookies = {n: FORGED for n in _NAMES}
    return body, headers, params, cookies


def _post(body, headers, params=None, cookies=None):
    c = TestClient(gateway.app, raise_server_exceptions=False)
    if cookies:
        for k, v in cookies.items():
            c.cookies.set(k, v)
    return c.post("/orchestrate", json=body, headers=headers, params=params or {})


def test_control_a_valid_token_alone_launches_as_its_person(seen, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    r = _post({"message": "x", "session_id": "s-ok"}, {"Authorization": f"Bearer {GOOD}"})
    assert r.status_code == 200, r.text[:300]
    (kw,) = seen.streams
    assert kw["user_email"] == REAL and kw["user_id"] == SUB and kw["caller_token"] == GOOD, kw
    assert any(f"who={REAL}" in ln for ln in _lines(caplog)), _lines(caplog)


def test_a_forged_originator_in_any_carrier_never_reaches_the_launch_or_the_audit_line(seen, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    body, headers, params, cookies = _forged_request()
    r = _post(body, headers, params, cookies)
    assert r.status_code == 200, r.text[:300]
    (kw,) = seen.streams
    # the verified identity won ...
    assert kw["user_email"] == REAL and kw["user_id"] == SUB and kw["caller_token"] == GOOD, kw
    lines = _lines(caplog)
    assert lines and all(f"who={REAL}" in ln for ln in lines), lines
    # ... and the forged one is nowhere that is downstream of the route.
    for place, text in (("launch", {k: v for k, v in kw.items() if k != "request"}.__repr__()),
                        ("audit", "\n".join(lines))):
        assert FORGED not in text and FORGED_SUB not in text, (place, text)


def test_a_token_that_does_not_verify_launches_nothing_whatever_the_carriers_say(seen, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    body, headers, params, cookies = _forged_request()
    headers["Authorization"] = "Bearer not-a-token-the-keys-signed"
    r = _post(body, headers, params, cookies)
    assert r.status_code == 401, (r.status_code, r.text[:200])
    assert seen.streams == []
    assert not any(FORGED in ln for ln in _lines(caplog))


def test_no_token_launches_nothing_whatever_the_carriers_say(seen):
    body, headers, params, cookies = _forged_request()
    headers.pop("Authorization")
    r = _post(body, headers, params, cookies)
    assert r.status_code in (401, 403), r.status_code
    assert seen.streams == []


class _Stop(BaseException):
    """Ends the run right after the stash. A BaseException, because a stash failure is deliberately
    swallowed by the route (it must not kill the run), and the poll that follows would never return."""


class _Resp:
    status_code = 200
    content = b"{}"

    def raise_for_status(self):
        pass

    def json(self):
        return {"mode": "ONE_SHOT", "entity_refs": []}


class _Http:
    def __init__(self, *a, **k): ...
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, *a, **k): return _Resp()
    async def get(self, *a, **k): return _Resp()


def test_the_run_and_its_vault_entry_are_made_under_the_verified_person(monkeypatch):
    """Past the route, through the REAL generate_dagster_stream: what the run is launched for and what
    the VAULT is told the stashed token belongs to. The redemption cross-check (`claimed_launcher` vs the
    stashed subject) is only as good as that subject, so it must be the verified person, never a field."""
    stashed: list[dict] = []
    launched: list[dict] = []

    async def launch(*a, **k):
        launched.append(k)
        return "run-forge-1"

    def stash(run_id, token, subject, slots=1):
        stashed.append({"run_id": run_id, "token": token, "subject": subject})
        raise _Stop()

    monkeypatch.setattr(gateway, "_launch_supervisor_job", launch)
    monkeypatch.setattr(gateway.VAULT, "stash", stash)
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Http)
    body, headers, params, cookies = _forged_request()
    try:
        _post(body, headers, params, cookies)
    except _Stop:
        pass
    assert launched and stashed, ("the run was not launched with the stubs in place", launched, stashed)
    blob = json.dumps({"stashed": stashed, "launched": launched}, default=str)
    assert FORGED not in blob and FORGED_SUB not in blob, blob
    for s in stashed:
        assert s["subject"] == REAL and s["token"] == GOOD, s
    for k in launched:
        assert k.get("user_email") == REAL and k.get("user_id") == SUB, k
