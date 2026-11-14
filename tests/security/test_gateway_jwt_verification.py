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

WHAT THE READ CONFIRMED (src/iagent/auth.py, verified_claims):
  * `jwks_client.get_signing_key_from_jwt(token)` — key comes from Keycloak's live JWKS.
  * `jwt.decode(..., algorithms=["RS256"])` — the algorithm is PINNED, which closes both
    `alg: none` and the HS256-signed-with-the-public-key confusion. Not asserted by accident:
    an unpinned algorithm list is the classic way a "verified" decode verifies nothing.
  * `verify_signature` is left at its default (ON).
  * `iss` and `aud` are checked against SERVED lists (BFF_JWT_ACCEPTED_ISSUERS / _AUDIENCES), and
    either list empty refuses every token. Until 2026-11-11 `verify_aud` was off and no issuer was
    passed, so any client of the realm, minted for any audience, was admitted (a delegate's report,
    the architect's security order). Each check below is a pair: the wrong value refused, the same
    token with the right value admitted.
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
ISSUER, AUDIENCE = "https://realm.test/realms/r", "bff.test"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


_UNSET = object()


def _token(private_pem: str, *, iss=ISSUER, aud=AUDIENCE) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    claims = {
        "sub": "probe-subject",
        "email": "probe@example.com",
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
        "realm_access": {"roles": []},
    }
    if iss is not _UNSET:
        claims["iss"] = iss
    if aud is not _UNSET:
        claims["aud"] = aud
    return jwt.encode(claims, private_pem, algorithm="RS256")


def _outcome(mod, token: str) -> str:
    """The refusal detail, or the sentinel when the token got past verification."""
    with pytest.raises(Exception) as exc:
        mod.get_current_user(token=token)
    return f"{getattr(exc.value, 'status_code', None)} {getattr(exc.value, 'detail', '')} {exc.value}"


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
    monkeypatch.setenv(mod.ACCEPTED_ISSUERS_ENV, ISSUER)
    monkeypatch.setenv(mod.ACCEPTED_AUDIENCES_ENV, AUDIENCE)
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


@pytest.mark.parametrize("aud", ["account", "training-workbench", ["account", "another.test"]])
def test_a_token_for_another_audience_is_refused(auth_mod, aud):
    """The same realm, the same key, minted for someone else: refused, naming the audience."""
    mod, keycloak_pem = auth_mod
    got = _outcome(mod, _token(keycloak_pem, aud=aud))
    assert got.startswith("401") and "audience" in got.lower(), got
    assert _SENTINEL not in got, got


@pytest.mark.parametrize("aud", [AUDIENCE, ["account", AUDIENCE]])
def test_control_the_same_token_naming_the_served_audience_is_admitted(auth_mod, aud):
    """Control for the refusal above: only `aud` differs. Keycloak may emit a list; one match admits."""
    mod, keycloak_pem = auth_mod
    assert _SENTINEL in _outcome(mod, _token(keycloak_pem, aud=aud))


def test_a_token_with_no_audience_is_refused(auth_mod):
    mod, keycloak_pem = auth_mod
    got = _outcome(mod, _token(keycloak_pem, aud=_UNSET))
    assert got.startswith("401") and "aud" in got.lower(), got
    assert _SENTINEL not in got, got


@pytest.mark.parametrize("iss", ["https://realm.test/realms/other", "https://evil.test/realms/r"])
def test_a_token_from_another_issuer_is_refused(auth_mod, iss):
    """Signed by the pinned key but naming another issuer: refused, naming the issuer."""
    mod, keycloak_pem = auth_mod
    got = _outcome(mod, _token(keycloak_pem, iss=iss))
    assert got.startswith("401") and "issuer" in got.lower(), got
    assert _SENTINEL not in got, got


def test_a_token_with_no_issuer_is_refused(auth_mod):
    mod, keycloak_pem = auth_mod
    got = _outcome(mod, _token(keycloak_pem, iss=_UNSET))
    assert got.startswith("401") and "iss" in got.lower(), got
    assert _SENTINEL not in got, got


def test_control_every_served_issuer_is_admitted(auth_mod, monkeypatch):
    """Control for the issuer refusals: a served list of two (public and in-cluster) admits both."""
    mod, keycloak_pem = auth_mod
    other = "http://realm.internal.test/realms/r"
    monkeypatch.setenv(mod.ACCEPTED_ISSUERS_ENV, f"{ISSUER}, {other}")
    for iss in (ISSUER, other):
        assert _SENTINEL in _outcome(mod, _token(keycloak_pem, iss=iss)), iss


@pytest.mark.parametrize("env", ["ACCEPTED_ISSUERS_ENV", "ACCEPTED_AUDIENCES_ENV"])
@pytest.mark.parametrize("value", [None, "", " , "])
def test_an_empty_served_list_refuses_a_correct_token(auth_mod, monkeypatch, env, value):
    """Empty refuses everything, never allows everything. The control is the legitimately signed
    test above: this token is identical, only the served list is emptied."""
    mod, keycloak_pem = auth_mod
    name = getattr(mod, env)
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)
    got = _outcome(mod, _token(keycloak_pem))
    assert got.startswith("401") and name in got, got
    assert _SENTINEL not in got, got


def test_algorithm_is_pinned_to_rs256():
    """`algorithms=` must be an explicit allow-list.

    An unpinned decode is the classic way a "verified" signature verifies nothing: `alg: none`
    is accepted, or an HS256 token signed with the RSA PUBLIC key validates. Asserted on the
    SOURCE because the runtime probe above cannot see a permissive allow-list that simply was
    not exercised.
    """
    import ast
    import inspect
    auth = importlib.import_module("iagent.auth")
    decodes = [n for n in ast.walk(ast.parse(inspect.getsource(auth)))
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "decode" and getattr(n.func.value, "id", None) == "jwt"]
    assert decodes, "iagent.auth has no jwt.decode to read; the verification moved"
    for call in decodes:
        kwargs = {k.arg: k.value for k in call.keywords}
        assert "algorithms" in kwargs, f"line {call.lineno}: jwt.decode with no allow-list"
        assert ast.literal_eval(kwargs["algorithms"]) == ["RS256"], f"line {call.lineno}"
        assert "issuer" in kwargs and "audience" in kwargs, (
            f"line {call.lineno}: jwt.decode without issuer= and audience= checks neither"
        )
        for k in ("issuer", "audience"):
            assert not isinstance(kwargs[k], ast.Constant), (
                f"line {call.lineno}: {k}= is a literal; it must be the served value"
            )
        if "options" in kwargs:
            options = ast.literal_eval(kwargs["options"])
            for flag in ("verify_signature", "verify_aud", "verify_iss", "verify_exp"):
                assert options.get(flag, True) is True, f"line {call.lineno} turns off {flag}"
            assert {"exp", "iss", "aud"} <= set(options.get("require", [])), (
                f"line {call.lineno}: a token without exp/iss/aud must be refused, not skipped"
            )
    # The door goes through the one that was read.
    src = inspect.getsource(auth.get_current_user)
    assert "verified_claims(" in src, "get_current_user does not verify through verified_claims"
    assert "jwt.decode(" not in src, "get_current_user decodes for itself"
