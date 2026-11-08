"""The /orchestrate audit line names the USER: the token's authorization identity, not the OAuth
client the token was issued to (`azp`, which belongs in `via=`) and not the opaque `sub`.

Driven through the REAL route (`gateway.app`, the real `_audit_orchestrate_refusals` door and
`_audit_orchestrate_wrap`, the real `iagent.audit.orchestrate` logger) with the user resolved by
the real `User` model. Three identities are made distinct on purpose (authz id, sub, client), so a
line that took the wrong one cannot match by accident. It is checked on BOTH exits: the line a
refusal leaves before the stream opens, and the line the stream leaves when it ends.

A SERVICE caller never reaches the line: since #187 the MCP door refuses it 403 before `/orchestrate`
logs anything, so the tests below assert that refusal (the envelope read off the live app) and the
absence of a line, with a user-token control, instead of a line naming a service identity.

DELEGATION, as it exists on master: `/orchestrate` has NO `on_behalf_of`. `InterviewRequest` has no
such field and no token-exchange `act` claim is read anywhere in `auth.py`; `on_behalf_of` exists
only on the ingest-family routes (`/ingest`, `/human_tasks/{task_id}/act`) as an ASSERTED body field
admitted by `_admit_on_behalf_of` (R-089). So on this route a delegate's token is the caller, and
the line names the delegate, who authenticated; there is no principal to name. The last test pins
that absence: the day `InterviewRequest` gains `on_behalf_of`, this goes red until the audit line
carries the principal too.

Run: uv run pytest tests/mcp_seals/test_the_orchestrate_audit_line_names_the_user.py -q
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from src.iagent import gateway
from src.iagent.ingest_api import MCP_TAG
from src.iagent.auth import User

LOGGER = "iagent.audit.orchestrate"
AUTHZ = "alice@example.com"
SUB = "5b1c0a52-0000-4000-8000-00000000a11c"
CLIENT = "mcp-server-client"


def _user(authz=AUTHZ):
    return User(id=SUB, authz_id=authz, email=authz if "@" in authz else None, azp=CLIENT,
                entitlement_source="none")


@pytest.fixture
def caller(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    state = {"user": _user()}
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: state["user"]
    try:
        yield state
    finally:
        gateway.app.dependency_overrides.clear()


def _lines(caplog):
    return [r.getMessage() for r in caplog.records
            if r.name == LOGGER and r.getMessage().startswith("orchestrate_access ")]


def _field(line: str, name: str) -> str:
    return next(tok.split("=", 1)[1] for tok in line.split() if tok.startswith(name + "="))


def _post_refused(session):
    """A request the door refuses before the stream opens (no such template)."""
    return TestClient(gateway.app, raise_server_exceptions=False).post(
        "/orchestrate",
        json={"message": "x", "session_id": session,
              "seed_panel": {"template_id": "no_such_template", "panel": 0, "bindings": {}}},
        headers={"Authorization": "Bearer tok"})


def _post_streaming(session, monkeypatch):
    async def stream(*a, **k):
        yield "event: status\ndata: {\"stage\": \"routing\"}\n\n"
        yield "event: final_payload\ndata: {\"k\": 1}\n\n"
    monkeypatch.setattr(gateway, "generate_dagster_stream", stream)
    return TestClient(gateway.app, raise_server_exceptions=False).post(
        "/orchestrate", json={"message": "x", "session_id": session},
        headers={"Authorization": "Bearer tok"})


def test_a_refusal_line_names_the_authz_identity_not_the_sub_or_the_client(caller, caplog):
    r = _post_refused("s-refused")
    assert r.status_code in (409, 422), r.status_code
    (line,) = _lines(caplog)
    assert _field(line, "who") == AUTHZ, line
    assert _field(line, "via") == CLIENT, line
    assert SUB not in line, line


def test_a_completed_stream_line_names_the_authz_identity_not_the_sub_or_the_client(
        caller, caplog, monkeypatch):
    r = _post_streaming("s-stream", monkeypatch)
    assert r.status_code == 200 and "final_payload" in r.text, (r.status_code, r.text[:200])
    (line,) = _lines(caplog)
    assert _field(line, "who") == AUTHZ, line
    assert _field(line, "via") == CLIENT, line
    assert _field(line, "outcome") == "completed" and SUB not in line, line


def test_the_line_follows_the_token_it_is_not_a_constant(caller, caplog, monkeypatch):
    """CONTROL: change who the token resolves to and the line changes with it."""
    caller["user"] = _user("bob@example.com")
    _post_streaming("s-other", monkeypatch)
    (line,) = _lines(caplog)
    assert _field(line, "who") == "bob@example.com", line


def _door_refusal_served_by_another_route():
    """The refusal envelope the MCP door SERVES, read off the live app: the 403 any other MCP-tagged
    GET route (derived from `app.routes` by `MCP_TAG`, path params filled) answers a service caller.
    Nothing here is a typed copy of the status or the body."""
    import re
    seen = []
    for r in gateway.app.routes:
        if MCP_TAG not in (getattr(r, "tags", None) or []) or "GET" not in (getattr(r, "methods", None) or ()):
            continue
        if getattr(r, "path", "") == "/orchestrate" or getattr(r, "body_field", None) is not None:
            continue
        seen.append(re.sub(r"\{[^}]+\}", "x", r.path))
    assert seen, "no other MCP-tagged GET route to read the served refusal from"
    out = []
    for path in seen:
        got = TestClient(gateway.app, raise_server_exceptions=False).get(path, headers={"Authorization": "Bearer tok"})
        out.append((got.status_code, got.json()))
    assert all(o == out[0] for o in out), out  # one door, one envelope, on every route
    return out[0]


def _post_stream_unrefused(session):
    return TestClient(gateway.app, raise_server_exceptions=False).post(
        "/orchestrate", json={"message": "x", "session_id": session}, headers={"Authorization": "Bearer tok"})


def test_a_service_identity_is_refused_at_the_door_and_the_refusal_is_the_served_one(
        caller, caplog, monkeypatch):
    """#187: the MCP door refuses a service caller before /orchestrate runs. This asserts the REFUSAL
    (status and envelope, equal to what the door serves on its other routes), not an audit line."""
    caller["user"] = _user("svc:mcp-server")
    status, envelope = _door_refusal_served_by_another_route()
    assert status == 403 and envelope["detail"]["authz_id"] == "svc:mcp-server", (status, envelope)
    r = _post_streaming("s-svc", monkeypatch)
    assert (r.status_code, r.json()) == (status, envelope), (r.status_code, r.text[:200])


def test_a_declared_delegate_is_refused_here_too_because_the_body_has_no_on_behalf_of(
        caller, caplog, monkeypatch):
    """A delegate passes only where the body can name a principal; `InterviewRequest` cannot."""
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", '{"svc:mcp-server": ["alice@example.com"]}')
    caller["user"] = _user("svc:mcp-server")
    status, envelope = _door_refusal_served_by_another_route()
    r = _post_streaming("s-delegate", monkeypatch)
    assert (r.status_code, r.json()) == (status, envelope), (r.status_code, r.text[:200])


def test_a_refused_service_request_writes_no_audit_line_and_a_user_request_on_the_same_path_does(
        caller, caplog, monkeypatch):
    """ABSENCE with its CONTROL: the refused request leaves no `orchestrate_access` line (the door
    refuses before /orchestrate logs anything); the same path with a user token leaves exactly one,
    so the empty log above is the door, not a broken logger."""
    caller["user"] = _user("svc:mcp-server")
    refused = _post_streaming("s-absent", monkeypatch)
    assert refused.status_code == 403, refused.status_code
    assert _lines(caplog) == [], _lines(caplog)
    caller["user"] = _user()
    ok = _post_streaming("s-present", monkeypatch)
    assert ok.status_code == 200, ok.status_code
    (line,) = _lines(caplog)
    assert _field(line, "who") == AUTHZ and "svc:" not in line, line


def test_orchestrate_has_no_on_behalf_of_so_there_is_no_principal_to_name():
    """PIN (the absence, as on master): the request model has no `on_behalf_of`, so an asserted
    principal cannot reach /orchestrate unaudited. Adding one must come with the audit line."""
    assert "on_behalf_of" not in gateway.InterviewRequest.model_fields
