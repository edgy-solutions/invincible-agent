"""The gateway's JWT signature verification is REAL — probed, not assumed.

WHY THIS TEST EXISTS AT ALL. `agent_fleet/core/authz.py` decoded bearer tokens with
`verify_signature=False` and justified it in a comment: *"We don't verify the signature here as
the API Gateway/BFF handles that."* That module is now deleted (unsound, not merely unapplied),
but deleting it does not discharge the sentence — it PROMOTES it. "The gateway verifies
signatures" is now the load-bearing assumption of the DA seam, the whole `on_behalf_of` design,
and every engine that trusts an identity it did not itself authenticate.

An assumption that three designs rest on gets a READ and a PROBE, not a nod. This month has
produced three separate instances of SECURITY-ASSUMED-AT-A-BOUNDARY-THE-COMPONENT-DOES-NOT-
CONTROL — the DA read path deferring to a gateway gate, the SDK's `MESH_DEV_TOKEN` resting on
"you are running within the secured JupyterHub environment", and core/authz deferring here.
Two of the three turned out to be wrong. This one is right, and now says so with a witness.

WHAT THE READ CONFIRMED (src/iagent/auth.py:200-210):
  * `jwks_client.get_signing_key_from_jwt(token)` — key comes from Keycloak's live JWKS.
  * `jwt.decode(..., algorithms=["RS256"])` — the algorithm is PINNED, which closes both
    `alg: none` and the HS256-signed-with-the-public-key confusion. Not asserted by accident:
    an unpinned algorithm list is the classic way a "verified" decode verifies nothing.
  * `verify_signature` is left at its default (ON). Only `verify_aud` is relaxed, deliberately.
  * All three except-paths return 401 — including the JWKS-fetch catch-all, so a Keycloak
    outage DENIES rather than admits.

WHY THE PROBE IS A DISCRIMINATING PAIR, not a single 401. Because the catch-all also returns
401, a forged token would produce 401 even if signature checking were absent and the JWKS fetch
merely failed — the same observation for opposite reasons, which is the false-witness shape this
suite exists to refuse. So JWKS is pinned to a known key and two tokens differing ONLY in which
key signed them are pushed through the SAME path:

    attacker-signed -> 401 naming SIGNATURE failure      (the gate bites)
    keycloak-signed -> reaches identity resolution       (the gate lets the legitimate through)

The positive control is what makes the negative meaningful: without it, a gate that rejected
EVERYTHING would pass the forged-token test perfectly.
"""
from __future__ import annotations

import datetime
import importlib

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

_SENTINEL = "PROBE-REACHED-IDENTITY-RESOLUTION"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def _token(private_pem: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode(
        {
            "sub": "probe-subject",
            "email": "probe@example.com",
            "iat": now,
            "exp": now + datetime.timedelta(minutes=5),
            "realm_access": {"roles": []},
        },
        private_pem,
        algorithm="RS256",
    )


@pytest.fixture()
def auth_mod(monkeypatch):
    """`iagent.auth` with JWKS pinned to a KNOWN key and identity resolution short-circuited.

    Pinning JWKS is what makes the pair discriminating: both tokens then take the identical
    code path and differ only in their signature. Short-circuiting identity resolution with a
    sentinel keeps the probe hermetic — no Topaz, no network — while still proving the valid
    token got PAST the signature check, which a bare "no exception" could not show.
    """
    mod = importlib.import_module("iagent.auth")

    keycloak_pem, keycloak_pub = _keypair()

    class _SigningKey:
        key = keycloak_pub

    monkeypatch.setattr(mod.jwks_client, "get_signing_key_from_jwt",
                        lambda token: _SigningKey(), raising=True)

    def _short_circuit(payload):
        raise ValueError(_SENTINEL)

    monkeypatch.setattr(mod, "resolve_token_identity", _short_circuit, raising=True)
    return mod, keycloak_pem


def test_forged_token_is_refused_by_signature(auth_mod):
    """A token signed by a key Keycloak never issued must be REFUSED, naming the signature."""
    mod, _ = auth_mod
    attacker_pem, _ = _keypair()

    with pytest.raises(Exception) as exc:
        mod.get_current_user(token=_token(attacker_pem))

    detail = f"{getattr(exc.value, 'detail', '')} {exc.value}"
    assert getattr(exc.value, "status_code", None) == 401, (
        f"forged token did not produce 401: {detail}"
    )
    assert "signature" in detail.lower(), (
        "the forged token was refused, but NOT for its signature — the refusal must be "
        f"attributable to signature verification, else a gate that rejects everything would "
        f"pass this test. Got: {detail}"
    )
    assert _SENTINEL not in detail, (
        "a forged token reached identity resolution — signature verification did not bite"
    )


def test_legitimately_signed_token_passes_the_signature_gate(auth_mod):
    """POSITIVE CONTROL — without this, a reject-everything gate would look perfect above."""
    mod, keycloak_pem = auth_mod

    with pytest.raises(Exception) as exc:
        mod.get_current_user(token=_token(keycloak_pem))

    detail = f"{getattr(exc.value, 'detail', '')} {exc.value}"
    assert _SENTINEL in detail, (
        "a token signed by the pinned JWKS key did NOT reach identity resolution, so this "
        f"suite cannot distinguish a working gate from a gate that refuses everyone. Got: {detail}"
    )
    assert "signature" not in detail.lower(), (
        f"a legitimately signed token was rejected for its signature: {detail}"
    )


def test_algorithm_is_pinned_to_rs256():
    """`algorithms=` must be an explicit allow-list.

    An unpinned decode is the classic way a "verified" signature verifies nothing: `alg: none`
    is accepted, or an HS256 token signed with the RSA PUBLIC key validates. Asserted on the
    SOURCE because the runtime probe above cannot see a permissive allow-list that simply was
    not exercised.
    """
    import inspect
    src = inspect.getsource(importlib.import_module("iagent.auth").get_current_user)
    assert 'algorithms=["RS256"]' in src or "algorithms=['RS256']" in src, (
        "get_current_user does not pin algorithms to RS256"
    )
    assert "verify_signature" not in src or "verify_signature\": False" not in src, (
        "get_current_user appears to disable signature verification"
    )
