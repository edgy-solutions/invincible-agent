"""/me/entitlements names the caller's authz_id, the value a self-drop's `on_behalf_of` must echo.

At work-deploy USER_ENTITLEMENT_CLAIM is the employee id, so authz_id, `sub` and email are three
different strings. cortex-ui sent the OIDC email as `on_behalf_of`, which the gateway reads as a
delegation and refuses `not_a_delegate` (reported 2026-10-21). The fixture keeps the three apart,
so an endpoint that answered with `id` or `email` under the authz_id key fails here.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from src.iagent import gateway
from src.iagent.auth import User

_WORK_CALLER = User(
    id="0f3c2a9e-sub", email="alice@corp.example", authz_id="E104233",
    entitlement_source="none",
)


def _body(user: User) -> dict:
    return asyncio.run(gateway.get_me_entitlements(current_user=user))


def test_the_fixture_keeps_authz_id_sub_and_email_apart():
    assert len({_WORK_CALLER.authz_id, _WORK_CALLER.id, _WORK_CALLER.email}) == 3


def test_me_entitlements_returns_the_authz_id_not_the_sub_or_the_email():
    body = _body(_WORK_CALLER)
    assert body["authz_id"] == "E104233"
    assert body["user_id"] == "0f3c2a9e-sub"
    assert body["email"] == "alice@corp.example"


def test_echoing_the_returned_authz_id_is_a_self_drop(monkeypatch):
    monkeypatch.delenv("DELEGATE_ON_BEHALF_OF", raising=False)
    assert gateway._admit_on_behalf_of(_WORK_CALLER, _body(_WORK_CALLER)["authz_id"]) == (
        "E104233", None)


def test_echoing_the_email_is_refused_not_a_delegate(monkeypatch):
    """The reported defect, kept as the control: the email is not the caller's authz_id."""
    monkeypatch.delenv("DELEGATE_ON_BEHALF_OF", raising=False)
    with pytest.raises(HTTPException) as exc:
        gateway._admit_on_behalf_of(_WORK_CALLER, _body(_WORK_CALLER)["email"])
    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "not_a_delegate"}
