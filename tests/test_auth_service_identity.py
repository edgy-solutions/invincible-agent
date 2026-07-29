"""resolve_token_identity: authenticate on the AUTHZ identity, email optional.

History (2026-07-28): get_current_user hard-required an `email` claim
(`if not user_id or not email`), which contradicted the User model's OWN
contract ("email: DISPLAY/AUDIT only — never an authorization key (use
authz_id)") and rejected any token that legitimately carries no email:
  - a service account with no mailbox, or
  - a deployment whose USER_ENTITLEMENT_CLAIM is a non-email claim.

The identity model: authz comes from USER_ENTITLEMENT_CLAIM with `sub` fallback;
email is display/audit only. This test pins that contract — authenticate iff an
authz identity resolves, email returned as-is (possibly None, never a dummy) —
across the three token shapes a real deployment sees, plus the one genuine
"who is this?" failure.

Run:  uv run --frozen python -m pytest tests/test_auth_service_identity.py -q
"""
import pytest

from src.iagent import auth


def _set_claim(monkeypatch, name):
    """Point USER_ENTITLEMENT_CLAIM at `name` for one test (the single overlay
    knob that re-keys every authz decision)."""
    monkeypatch.setattr(auth, "USER_ENTITLEMENT_CLAIM", name)


def test_email_claim_deployment_human(monkeypatch):
    """Default deployment: USER_ENTITLEMENT_CLAIM=email → authz_id == email."""
    _set_claim(monkeypatch, "email")
    sub, authz_id, email = auth.resolve_token_identity(
        {"sub": "kc-uuid-1", "email": "alice@example.com"}
    )
    assert sub == "kc-uuid-1"
    assert authz_id == "alice@example.com"
    assert email == "alice@example.com"


def test_non_email_claim_human(monkeypatch):
    """A deployment keyed on a NON-email claim: authz_id comes from that claim;
    email is still present but is display-only — it must NOT become the authz key."""
    _set_claim(monkeypatch, "preferred_username")
    sub, authz_id, email = auth.resolve_token_identity(
        {"sub": "kc-uuid-2", "preferred_username": "person-42", "email": "p42@example.com"}
    )
    assert authz_id == "person-42"        # the entitlement claim, NOT the email
    assert email == "p42@example.com"     # display/audit only


def test_mailbox_less_service_account(monkeypatch):
    """THE REGRESSION THIS FIXES: a service account whose entitlement claim carries
    its identity but which has NO email claim. Previously rejected with 401
    'missing sub or email'; now authenticates, and email stays None — an honest
    absence, never a fabricated mailbox value."""
    _set_claim(monkeypatch, "preferred_username")
    sub, authz_id, email = auth.resolve_token_identity(
        {"sub": "kc-svc-uuid", "preferred_username": "svc:review-starter"}
    )
    assert authz_id == "svc:review-starter"
    assert email is None                  # NOT defaulted to a non-mailbox value


def test_sub_fallback_when_entitlement_claim_absent(monkeypatch):
    """authz_id falls back to `sub` when the entitlement claim is absent."""
    _set_claim(monkeypatch, "preferred_username")
    sub, authz_id, email = auth.resolve_token_identity({"sub": "kc-uuid-3"})
    assert authz_id == "kc-uuid-3"        # sub fallback
    assert email is None


def test_no_identity_raises(monkeypatch):
    """The ONLY genuine failure: neither the entitlement claim nor `sub` present.
    This is the real 'who is this?' rejection — distinct from a missing email,
    which is not an identity failure."""
    _set_claim(monkeypatch, "preferred_username")
    with pytest.raises(ValueError):
        auth.resolve_token_identity({"aud": "account"})   # no sub, no claim


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
