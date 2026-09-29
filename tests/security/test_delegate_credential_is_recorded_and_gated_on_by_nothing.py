"""A delegate credential's `on_behalf_of` is RECORDED and reaches no authorization decision.

WHAT IS BEING ADDED AND WHY IT NEEDS A GUARD IMMEDIATELY. The gateway now reads an
`on_behalf_of` claim off a verified client-credentials token and puts it on `User`. Accepting
such a token was never the missing part — `resolve_token_identity` falls back to `sub`, so a
service-account token already authenticated and came out honest-empty. What was missing is the
delegation being RECORDED, and the recording is exactly what makes a guard load-bearing: before
this change nothing could gate on `on_behalf_of` because the field did not exist, which is the
same accidental safety lock 2 found ("the property held because nobody had yet added an identity
field"). One field later, the property is a claim someone must keep.

THE FLEET ALREADY NAMED THIS HAZARD. `on_behalf_of` is this codebase's term for the laundering
shape: a subject the caller names is not an identity, it is a request field, and a gate keyed on
it checks who the asker CLAIMED asked (helm values.yaml on `serviceClients`;
docs/plans/register-caller-enumeration.md; lock 2 at `0555620`). So the claim is audit/trace
only, and every authorization decision keeps keying on `authz_id` — the credential that was
actually authenticated.

WHY THE CENTRAL ARM IS A DISCRIMINATING PAIR AND NOT AN ABSENCE CHECK. "Nothing gates on it" is
an absence assertion, and an absence assertion is worth its control. Grepping for the field's
name in a gate would pass just as well if the gate were unreachable, if the name were spelled
differently, or if the field were consumed one hop away. So the arm mints TWO REAL SIGNED TOKENS
that differ in `on_behalf_of` AND NOTHING ELSE, pushes both through the real `get_current_user`,
and asserts every authorization input comes out identical.

That comparison is only worth something if it can detect a change at all — an all-fields-equal
assertion passes trivially against a function that returns a constant. So the pair has a
CONTROL that differs in exactly one OTHER thing: the entitlement claim. Same harness, same
comparison, and the authorization inputs MUST move. Without it, this file would prove that
`get_current_user` ignores its input.

Run:  uv run --frozen python -m pytest tests/security/test_delegate_credential_is_recorded_and_gated_on_by_nothing.py -q
"""
from __future__ import annotations

import datetime
import importlib
import re
from pathlib import Path

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_AUTH = _ROOT / "src" / "iagent" / "auth.py"
_GATEWAY = _ROOT / "src" / "iagent" / "gateway.py"
_HUMAN_TASKS = _ROOT / "src" / "iagent" / "human_tasks.py"

#: The delegate's own identity — the thing that WAS authenticated, and the only thing a gate may
#: key on. Shaped like the chart's `authzId` values (`svc:engine-d`, `svc:data-analyst`).
DELEGATE_AUTHZ_ID = "svc:reporting-delegate"

#: The principal the delegate names. Deliberately a DIFFERENT, higher-value-looking identity than
#: the delegate's own: if anything did key on the claim, the pair below would show it as a
#: privilege change rather than a cosmetic one.
PRINCIPAL = "alice@example.com"
OTHER_PRINCIPAL = "ceo@example.com"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


@pytest.fixture()
def auth_mod(monkeypatch):
    """The real `iagent.auth`, with JWKS pinned to a known key and Topaz absent.

    JWKS is pinned rather than stubbed out so tokens travel the REAL decode path — signature
    verified, RS256 pinned — because a claim read off a token nobody verified would be the
    laundering shape with extra steps, and this file's whole subject is a claim's authority.

    Topaz is left unconfigured (`TOPAZ_DIRECTORY_URL` empty), so `_get_entitlement_cache()`
    returns None and the entitlement matrix is honest-empty. That keeps the probe hermetic, and
    the fields it flattens are still the ones every gate keys on.
    """
    mod = importlib.import_module("iagent.auth")
    pem, pub = _keypair()

    class _SigningKey:
        key = pub

    monkeypatch.setattr(mod.jwks_client, "get_signing_key_from_jwt",
                        lambda token: _SigningKey(), raising=True)
    monkeypatch.setattr(mod, "TOPAZ_DIRECTORY_URL", "", raising=True)
    monkeypatch.setattr(mod, "_entitlement_cache", None, raising=True)
    # The sandbox default: the entitlement claim IS email, so the delegate's hardcoded
    # `authzId` mapper writes into the claim every gate keys on — the chart's own arrangement
    # (keycloak-configmap.yaml: claim.name = authzClaim | default "email").
    monkeypatch.setattr(mod, "USER_ENTITLEMENT_CLAIM", "email", raising=True)
    return mod, pem


def _token(pem: str, **claims):
    """A verified client-credentials token. `email` carries the delegate's OWN authz id, which is
    what the chart's hardcoded `authz-id-svc` mapper does for every service client today."""
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": "kc-uuid-delegate",
        "email": DELEGATE_AUTHZ_ID,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
        "realm_access": {"roles": []},
    }
    payload.update(claims)
    return jwt.encode(payload, pem, algorithm="RS256")


def _authorization_inputs(user) -> dict:
    """Every field of `User` an authorization decision is permitted to read.

    Named as a set rather than compared field-by-field at each call site so that a NEW
    authorization-relevant field cannot be added to `User` and quietly escape the pair — the
    completeness of this dict is asserted separately, below.
    """
    return {
        "id": user.id,
        "authz_id": user.authz_id,
        "email": user.email,
        "roles": list(user.roles),
        "persona": user.persona,
        "entitled_domains": list(user.entitled_domains),
        "entitlement_source": user.entitlement_source,
        "entitlements": user.entitlements.model_dump(),
    }


# ── the claim is actually recorded ──────────────────────────────────────────────────────────────

def test_a_delegate_token_is_accepted_and_the_principal_is_recorded(auth_mod):
    """The positive case: a real signed client-credentials token with the claim gets in, and the
    delegation survives as a readable fact rather than being dropped."""
    mod, pem = auth_mod
    user = mod.get_current_user(token=_token(pem, on_behalf_of=PRINCIPAL))

    assert user.on_behalf_of == PRINCIPAL
    # ...and the authenticated identity is still the DELEGATE's own.
    assert user.authz_id == DELEGATE_AUTHZ_ID


def test_an_ordinary_caller_has_no_principal_rather_than_an_empty_one(auth_mod):
    """Absent claim -> None. A human login and a plain service credential both act as
    themselves, and `None` says that; `""` would read as "delegated, for nobody"."""
    mod, pem = auth_mod
    user = mod.get_current_user(token=_token(pem))
    assert user.on_behalf_of is None


# ── the pair, and its control ───────────────────────────────────────────────────────────────────

def test_changing_the_principal_moves_no_authorization_input(auth_mod):
    """THE CENTRAL ARM. Two tokens, identical but for `on_behalf_of`, through the real gate.

    If any authorization input moved, the claim would be an identity the caller chose.
    """
    mod, pem = auth_mod
    a = mod.get_current_user(token=_token(pem, on_behalf_of=PRINCIPAL))
    b = mod.get_current_user(token=_token(pem, on_behalf_of=OTHER_PRINCIPAL))

    assert a.on_behalf_of != b.on_behalf_of, "the tokens did not actually differ"
    assert _authorization_inputs(a) == _authorization_inputs(b), (
        "an authorization input changed when only on_behalf_of changed — the claim is being "
        "gated on somewhere between the decode and the model"
    )


def test_the_control_changing_the_entitlement_claim_DOES_move_them(auth_mod):
    """THE CONTROL, differing in exactly one OTHER thing.

    Same harness, same comparison. If this passed too, the arm above would be proving that
    `get_current_user` ignores its input, not that it ignores this claim.
    """
    mod, pem = auth_mod
    a = mod.get_current_user(token=_token(pem, on_behalf_of=PRINCIPAL))
    b = mod.get_current_user(
        token=_token(pem, email="svc:some-other-delegate", on_behalf_of=PRINCIPAL))

    assert a.on_behalf_of == b.on_behalf_of, "the control changed the claim too"
    assert _authorization_inputs(a) != _authorization_inputs(b), (
        "changing the ENTITLEMENT CLAIM moved no authorization input either — the comparison "
        "cannot detect a change, so the pair above proves nothing"
    )


def test_the_authorization_input_set_is_every_user_field_but_the_claim(auth_mod):
    """The pair is only as complete as `_authorization_inputs`. If `User` grows a field, it must
    be classified — as an authorization input (add it here) or as audit (name it below) — rather
    than silently escaping the comparison."""
    mod, pem = auth_mod
    fields = set(mod.User.model_fields)
    audit_only = {"on_behalf_of"}
    # DERIVED by calling the helper, never re-typed: a second copy of the field list would let
    # the two drift and this arm would then be checking its own duplicate.
    compared = set(_authorization_inputs(
        mod.get_current_user(token=_token(pem, on_behalf_of=PRINCIPAL))))
    assert fields == compared | audit_only, (
        f"User's fields are no longer partitioned: {fields ^ (compared | audit_only)} is "
        f"neither compared as an authorization input nor declared audit-only"
    )


# ── a misconfigured mapper is refused, not recorded ─────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "   ", None, 123, {"email": PRINCIPAL}, [PRINCIPAL]])
def test_a_present_but_unusable_claim_is_refused(auth_mod, bad):
    """Present-but-blank, and present-but-not-a-string, are both a broken claim mapper.

    The dict and list cases are the interesting ones: they are what an attempt to smuggle a
    structured principal looks like, and `str(value)` on either would record something that
    reads like an identity in a trace.
    """
    mod, pem = auth_mod
    with pytest.raises(Exception) as exc:
        mod.get_current_user(token=_token(pem, on_behalf_of=bad))
    assert "401" in str(exc.value) or getattr(exc.value, "status_code", None) == 401, exc.value


def test_the_refusal_shares_the_path_of_an_unresolvable_identity(auth_mod):
    """A broken delegate claim must not be softer than a broken identity.

    If the claim were read AFTER the identity block, a token with a broken mapper would be
    authorized as an ordinary caller with the delegation dropped — a delegated write recorded as
    a direct one, which is the failure this file cares most about.
    """
    src = _AUTH.read_text(encoding="utf-8")
    block = re.search(
        r"user_id, authz_id, email = resolve_token_identity\(payload\)(.*?)except ValueError",
        src, re.S)
    assert block, "the identity resolution block moved — re-read this guard"
    assert "resolve_on_behalf_of(payload)" in block.group(1), (
        "the delegate claim is no longer read inside the identity block's try, so a malformed "
        "claim no longer shares the 401 path with an unresolvable identity"
    )


# ── nothing keys on it, asserted where the keys are written ─────────────────────────────────────

@pytest.mark.parametrize("path,label", [
    (_AUTH, "auth"), (_GATEWAY, "gateway"), (_HUMAN_TASKS, "human_tasks"),
])
def test_no_authorization_key_is_assigned_from_the_claim(path, label):
    """Source-text, over the three files that WRITE an authorization key.

    The spellings are the fleet's real ones: `authz_id` (every gate), `lookup_key` (the Topaz
    entitlement lookup), `subject_id` (the Topaz check payload), `caller_id` (can_act's
    parameter) and `user_email` (the cross-service acting subject lock 2 pins).
    """
    if not path.exists():
        pytest.skip(f"{label} not present")
    src = path.read_text(encoding="utf-8")
    for key in ("authz_id", "lookup_key", "subject_id", "caller_id", "user_email"):
        pattern = rf"{key}\s*=\s*[^=\n]*on_behalf_of"
        assert not re.search(pattern, src), (
            f"{label} assigns {key} from on_behalf_of — that is the laundering shape: the gate "
            f"would check who the caller CLAIMED to act for"
        )


def test_the_topaz_lookup_key_is_the_delegate_not_the_principal(auth_mod, monkeypatch):
    """BEHAVIOURAL, not source-text: what the entitlement lookup is actually CALLED with.

    A recording double on the cache, because the strongest form of "the principal did not
    influence authorization" is reading the argument the authorization lookup received.
    """
    mod, pem = auth_mod
    seen = {}

    class _RecordingCache:
        def get(self, *, sub, jti, exp, lookup_key):
            seen.update(sub=sub, lookup_key=lookup_key)
            return mod.Entitlements()

    monkeypatch.setattr(mod, "_get_entitlement_cache", lambda: _RecordingCache(), raising=True)
    mod.get_current_user(token=_token(pem, on_behalf_of=PRINCIPAL))

    assert seen, "the entitlement lookup was never reached — this arm proved nothing"
    assert seen["lookup_key"] == DELEGATE_AUTHZ_ID
    assert seen["lookup_key"] != PRINCIPAL
    assert seen["sub"] != PRINCIPAL


def test_the_request_model_still_cannot_name_the_principal():
    """A CONTROL ON MY OWN CHANGE. Lock 2 forbids the inbound model naming the acting subject
    under any spelling, `on_behalf_of` included. Adding a token-sourced field of that name is the
    obvious occasion for someone to mirror it onto the request body, so the prohibition is
    re-asserted from this side rather than left to the other file."""
    src = _GATEWAY.read_text(encoding="utf-8")
    m = re.search(r"class InterviewRequest\b.*?(?=\nclass |\n@app\.)", src, re.S)
    assert m, "InterviewRequest not found — did the entry model move?"
    assert not re.search(r"^\s+on_behalf_of\s*:", m.group(0), re.M), (
        "InterviewRequest now exposes on_behalf_of — a caller could name the principal in the "
        "BODY, which is the unsigned version of this claim"
    )
