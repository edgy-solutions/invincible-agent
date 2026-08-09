"""Capture A probe — entitlement_source fidelity flag on produced_for.

ADR-0025 §"Capture A — entitlement_source fidelity flag on
produced_for". The capture records WHERE the persona / entitlements
came from at token-read time; once `get_current_user` returns, the
persisted `produced_for` records the final VALUE but not the ORIGIN
unless we capture it — capture-or-lose-forever.

2026-07-03 — ADR-0026 step 6 retired the JWT-claim path. The
entitlement_source vocabulary collapsed from three JWT-origin values
(claim / fallback / partial) to TWO truthful states:

  "topaz" — Topaz returned a non-empty entitlement matrix.
  "none"  — Topaz returned an empty matrix (unseeded user). HONEST-
            EMPTY: persona=None, entitled_domains=[]. Never a
            fabricated default.

This probe now guards the NEW contract:
  1. entitlement_source is REQUIRED on the User model (a forgotten
     value is a ValidationError, not a silent default — per
     [[optimistic-defaults-are-dishonest]]).
  2. The two valid states construct cleanly.
  3. The RETIRED values (claim/fallback/partial) are REJECTED — the
     Literal enum no longer admits them. This is the deletion's
     structural proof: the old vocabulary can't sneak back.

Hermetic — no Neo4j, no running service, no JWT decode. Constructs
the User model directly.

Run:
    uv run pytest tests/test_capture_a_entitlement_source_recorded.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.auth import User  # noqa: E402
from iagent.authz import Entitlements, EntitlementCell  # noqa: E402


def _valid_kwargs(**overrides):
    base = dict(
        id="test-sub",
        email="test@example.com",
        # REQUIRED since the email->authz_id migration. This fixture predated it, so every `User(...)`
        # here raised a pydantic ValidationError — red on every run, for a reason that had nothing to
        # do with what the file actually guards (entitlement_source provenance).
        #
        # DELIBERATELY DIFFERENT FROM `email`. In sandbox the authz identity happens to BE the email,
        # and a fixture that sets them equal cannot catch code assuming they always are — the
        # assumption that breaks at any deploy keying entitlement on a non-email claim. A distinct
        # value makes that conflation fail in a test rather than at a provider boundary.
        authz_id="test-authz-id",
        roles=[],
        persona=None,
        entitled_domains=[],
        entitlement_source="none",
        entitlements=Entitlements(),
    )
    base.update(overrides)
    return base


def test_entitlement_source_required_on_user_model() -> None:
    """The field is REQUIRED — omitting it is a ValidationError, not a
    silent default. This is the [[optimistic-defaults-are-dishonest]]
    guard: get_current_user must compute the value, never inherit a
    default that hides the real state."""
    kwargs = _valid_kwargs()
    del kwargs["entitlement_source"]
    with pytest.raises(ValidationError):
        User(**kwargs)


def test_topaz_state_constructs() -> None:
    """'topaz' is a valid state — the caller had a non-empty matrix."""
    ents = Entitlements(
        cells=[EntitlementCell(persona="DATA_ENGINEER", domain="AVIATION")],
        default=EntitlementCell(persona="DATA_ENGINEER", domain="AVIATION"),
    )
    user = User(**_valid_kwargs(
        persona="DATA_ENGINEER",
        entitled_domains=["AVIATION"],
        entitlement_source="topaz",
        entitlements=ents,
    ))
    assert user.entitlement_source == "topaz"
    assert user.persona == "DATA_ENGINEER"


def test_none_state_is_honest_empty() -> None:
    """'none' is the honest-empty state — persona None, no domains, and
    the source truthfully records that Topaz returned nothing. The
    absent-vs-empty distinction: this is NOT an error, it's a real
    fact about an unseeded user."""
    user = User(**_valid_kwargs(
        persona=None,
        entitled_domains=[],
        entitlement_source="none",
    ))
    assert user.entitlement_source == "none"
    assert user.persona is None, (
        "honest-empty must carry persona=None, never a fabricated default"
    )
    assert user.entitled_domains == []


@pytest.mark.parametrize("retired", ["claim", "fallback", "partial"])
def test_retired_jwt_origin_values_are_rejected(retired: str) -> None:
    """The JWT-claim-era values are RETIRED. The Literal enum must
    reject them — structural proof the deletion holds and the old
    vocabulary can't reappear by accident."""
    with pytest.raises(ValidationError):
        User(**_valid_kwargs(entitlement_source=retired))
