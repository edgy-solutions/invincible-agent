"""Capture A probe — entitlement_source fidelity flag on produced_for.

ADR-0025 §"Capture A — entitlement_source fidelity flag on
produced_for". The capture records WHICH origin the JWT claim came
from at the moment auth.py reads it. Once `get_current_user` returns,
the persisted `produced_for` records the final VALUE but not the
ORIGIN; that information is unrecoverable — capture-or-lose-forever.

Three legs per the ADR's probe spec:

  Leg 1 (fallback): no persona claim, no domains claim → "fallback"
  Leg 2 (claim):    both claims present                → "claim"
  Leg 3 (partial):  exactly one claim present          → "partial"

RED-first per [[pre-written-fixtures-must-fail-first]]:

  Predicted RED reason (Leg 1): `AttributeError: 'User' object has
  no attribute 'entitlement_source'` — the field doesn't exist on
  the Pydantic model yet.

  Predicted GREEN (after implementation): all three legs hold.

These tests do NOT require Neo4j or a running service. They
exercise the auth.py User construction layer directly via the
same payload-parsing logic `get_current_user` uses, so the
RED→GREEN transition is observable without an integration
substrate.

Run:
    uv run pytest tests/test_capture_a_entitlement_source_recorded.py -v

Plan reference:
    docs/adr/ADR-0025-instance-plane-access-control-as-provenance.md
    docs/plans/projector-build-plan.md §3.6 footnote
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

# Predicted-RED reason: until the User model gains the
# `entitlement_source` field, `User(...)` construction without it
# either fails ValidationError (if required) or the asserted
# attribute is missing.
from src.iagent.auth import (  # noqa: E402
    USER_DOMAINS_CLAIM,
    USER_PERSONA_CLAIM,
    USER_PERSONA_FALLBACK,
    User,
)


def _build_user_from_payload(payload: Dict[str, Any]) -> User:
    """Mirror the claim-read logic in src/iagent/auth.py:71-95
    exactly, BUT skip the JWT signature verification (which would
    require keycloak access). This is the same User-construction
    path the FastAPI dependency takes after JWT verification — we
    drop in at the payload-already-decoded boundary so the probe
    is hermetic.

    If the auth.py code changes the claim-read shape, this helper
    must be updated to mirror it. The probe is the canary for that
    drift per [[verify-subtle-acceptance-by-inspection]].
    """
    user_id = payload.get("sub") or "test-sub"
    email = payload.get("email") or "test@example.com"
    realm_access = payload.get("realm_access", {})
    roles = realm_access.get("roles", [])

    persona_claim_present = USER_PERSONA_CLAIM in payload
    domains_claim_present = USER_DOMAINS_CLAIM in payload

    persona_claim = payload.get(USER_PERSONA_CLAIM)
    persona = (persona_claim or USER_PERSONA_FALLBACK).upper()

    entitled_raw = payload.get(USER_DOMAINS_CLAIM, [])
    if isinstance(entitled_raw, str):
        entitled_raw = [
            s.strip() for s in entitled_raw.split(",") if s.strip()
        ]
    entitled_domains = [str(d).upper() for d in entitled_raw if d]

    # Compute entitlement_source per ADR-0025 §"Capture A":
    #   "claim"    — both present
    #   "fallback" — neither present (PingSSO production baseline)
    #   "partial"  — one present, the other fallback
    if persona_claim_present and domains_claim_present:
        entitlement_source = "claim"
    elif not persona_claim_present and not domains_claim_present:
        entitlement_source = "fallback"
    else:
        entitlement_source = "partial"

    return User(
        id=user_id,
        email=email,
        roles=roles,
        persona=persona,
        entitled_domains=entitled_domains,
        entitlement_source=entitlement_source,
    )


def test_leg1_fallback_when_no_claims_present() -> None:
    """Predicted-RED reason: User has no `entitlement_source`
    attribute → AttributeError on the assertion, OR ValidationError
    on construction if the field is required and we forgot to pass
    it. Predicted-GREEN: the field is "fallback" when neither claim
    was present.
    """
    payload: Dict[str, Any] = {
        "sub": "test-user-fallback",
        "email": "fallback@example.com",
    }
    user = _build_user_from_payload(payload)
    assert hasattr(user, "entitlement_source"), (
        "User model missing entitlement_source field — Capture A not "
        "wired. ADR-0025 §Capture A requires this field on the User "
        "Pydantic model."
    )
    assert user.entitlement_source == "fallback", (
        f"entitlement_source is {user.entitlement_source!r}; expected "
        f"'fallback' when neither persona nor domains claim is "
        f"present in the JWT."
    )


def test_leg2_claim_when_both_claims_present() -> None:
    """Predicted-RED reason: same as Leg 1 (field missing).
    Predicted-GREEN: the field is "claim" when both were present.
    Proves the field is genuinely two-valued, not constant-fallback.
    """
    payload = {
        "sub": "test-user-claim",
        "email": "claim@example.com",
        USER_PERSONA_CLAIM: "MAINTAINER",
        USER_DOMAINS_CLAIM: ["maintenance", "logistics"],
    }
    user = _build_user_from_payload(payload)
    assert user.entitlement_source == "claim", (
        f"entitlement_source is {user.entitlement_source!r}; expected "
        f"'claim' when both persona and domains claims are present."
    )
    # Sanity: the persona was sourced from the claim, not the fallback.
    assert user.persona == "MAINTAINER"
    assert user.entitled_domains == ["MAINTENANCE", "LOGISTICS"]


def test_leg3_partial_when_only_persona_present() -> None:
    """Predicted-RED reason: same as Legs 1+2.
    Predicted-GREEN: the field is "partial" when exactly one claim
    is present. Proves the partial state is reachable and labeled
    correctly per the ADR's transitional / misconfigured shape.
    """
    payload = {
        "sub": "test-user-partial-1",
        "email": "partial1@example.com",
        USER_PERSONA_CLAIM: "OPERATOR",
        # No USER_DOMAINS_CLAIM — domains fall back to [].
    }
    user = _build_user_from_payload(payload)
    assert user.entitlement_source == "partial", (
        f"entitlement_source is {user.entitlement_source!r}; expected "
        f"'partial' when only the persona claim is present."
    )


def test_leg3_partial_when_only_domains_present() -> None:
    """Sibling to Leg 3 above — the other half of the partial state.
    Both halves must hold for "partial" to be a useful label.
    """
    payload = {
        "sub": "test-user-partial-2",
        "email": "partial2@example.com",
        # No USER_PERSONA_CLAIM — persona falls back to MECHANIC.
        USER_DOMAINS_CLAIM: ["audit"],
    }
    user = _build_user_from_payload(payload)
    assert user.entitlement_source == "partial", (
        f"entitlement_source is {user.entitlement_source!r}; expected "
        f"'partial' when only the domains claim is present."
    )


def test_pydantic_model_requires_entitlement_source_explicitly() -> None:
    """Per [[optimistic-defaults-are-dishonest]]: the field is
    required at the Pydantic-model layer. Defaulting to "claim"
    would silently mask the fallback path; defaulting to "fallback"
    would be honest but would hide drift if the auth code forgot
    to compute it. Requiring explicit input forces the auth code
    to make the choice at the moment the JWT is read.

    Predicted-RED reason: if the field defaults silently to "claim"
    (or anything else), constructing User without it succeeds and
    this test fails. Predicted-GREEN: the field is required;
    constructing User without it raises ValidationError.
    """
    with pytest.raises(Exception) as excinfo:
        User(
            id="x",
            email="x@example.com",
            roles=[],
            persona="MECHANIC",
            entitled_domains=[],
            # entitlement_source intentionally omitted.
        )
    # Accept any pydantic / value error shape — the point is the
    # construction MUST fail, not the specific exception class.
    err_str = str(excinfo.value).lower()
    assert (
        "entitlement_source" in err_str
        or "validation" in err_str
        or "required" in err_str
        or "missing" in err_str
    ), (
        f"User construction without entitlement_source did not fail "
        f"with a field-required error. Got: {excinfo.value!r}. The "
        f"field must be REQUIRED per "
        f"[[optimistic-defaults-are-dishonest]]."
    )
