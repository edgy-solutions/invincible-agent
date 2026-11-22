"""The identity prefix, code half: compose a client id once, at the mint; read doors and the
BFF's `azp` under the same prefix. With the variable empty everything is byte-identical to today.

Each seal names the claim it defends (docs/proposals/one-realm-many-instances-the-identity-prefix.md,
sections 1, 2 and 5). Against a double, the assertions are on the REQUEST the double received.
"""
from __future__ import annotations

import ast
import asyncio
import datetime
import importlib
import sys
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.utils import identity_prefix as ip  # noqa: E402
from agent_fleet.utils import mesh_registration as mr  # noqa: E402
from agent_fleet.utils import service_identity as si  # noqa: E402

PFX = "t-"
ENV = ip.PREFIX_ENV

# The role literals of the census (proposal 4a, 4b).
ROLES = [
    "iagent-cost-agent", "iagent-data-analyst", "iagent-engine-d", "iagent-docs-agent",
    "iagent-finance-agent", "iagent-engine-e", "iagent-engine-o", "iagent-planning-agent",
    "iagent-safety-agent", "iagent-engine-w", "iagent-engine-a", "iagent-graph-host",
    "iagent-supervisor", "iagent-review-starter", "iagent-case-runner", "iagent-gateway",
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


# -- 1. composition ------------------------------------------------------------------------

def test_empty_prefix_is_the_identity_for_every_role(monkeypatch):
    """CLAIM: with the variable unset or empty, no role changes (byte-identical to today)."""
    for set_it in (False, True):
        if set_it:
            monkeypatch.setenv(ENV, "")
        for role in ROLES:
            assert ip.compose_client_id(role) == role
    assert ip.identity_prefix() == ""


def test_prefix_composes_and_is_read_at_call_time(monkeypatch):
    """CLAIM: `t-` gives `t-<role>`, and the env is read per call, not at import."""
    for role in ROLES:
        monkeypatch.setenv(ENV, PFX)
        assert ip.compose_client_id(role) == PFX + role
    monkeypatch.setenv(ENV, "u-")
    assert ip.compose_client_id("iagent-engine-o") == "u-iagent-engine-o"


def test_a_role_already_carrying_the_prefix_is_refused_naming_it(monkeypatch):
    """CLAIM: an id is never prefixed twice; the refusal names the role."""
    monkeypatch.setenv(ENV, PFX)
    with pytest.raises(ip.IdentityPrefixError, match="t-iagent-engine-o"):
        ip.compose_client_id("t-iagent-engine-o")
    with pytest.raises(ip.IdentityPrefixError):
        ip.compose_client_id("")


@pytest.mark.parametrize("bad", ["T-", "t", "t-x-", "abcdefghijklm-", " t-", "iagent-", "1t-", "t--", "-"])
def test_a_malformed_or_stem_prefix_is_refused(monkeypatch, bad):
    """CLAIM: every prefix outside the pattern, or equal to a role stem, makes composition raise.

    `iagent-` matches the pattern; it is refused where it bites, because every role literal
    already starts with it (the chart render also refuses it).
    """
    monkeypatch.setenv(ENV, bad)
    with pytest.raises(ip.IdentityPrefixError):
        ip.compose_client_id("iagent-engine-o")


def test_a_13_char_prefix_is_refused_and_a_12_char_one_is_not(monkeypatch):
    monkeypatch.setenv(ENV, "a" * 12 + "-")
    assert ip.identity_prefix() == "a" * 12 + "-"
    monkeypatch.setenv(ENV, "a" * 13 + "-")
    with pytest.raises(ip.IdentityPrefixError, match=ip.PREFIX_ENV):
        ip.identity_prefix()


def test_an_override_naming_another_instance_yields_a_client_that_does_not_exist(monkeypatch):
    """CLAIM: an env override cannot leave the instance's namespace."""
    monkeypatch.setenv(ENV, PFX)
    assert ip.compose_client_id("p-iagent-engine-o") == "t-p-iagent-engine-o"


# -- 2. the mint composes once, per surface -------------------------------------------------

class _Recorder:
    def __init__(self):
        self.requests = []

    def __call__(self, **kw):
        self.requests.append(kw)
        return "a.jwt.token"

    @property
    def ids(self):
        return [r["client_id"] for r in self.requests]


@pytest.fixture
def rec(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr("iagent_mesh.service_identity.mint_token", r)   # engine_mint imports lazily
    monkeypatch.setattr(si, "mint_token", r)
    monkeypatch.setenv("ENGINE_SECRET", "s")
    monkeypatch.setenv("SUPERVISOR_CLIENT_SECRET", "s")
    monkeypatch.setenv("CASE_RUNNER_CLIENT_SECRET", "s")
    monkeypatch.setenv("REVIEW_STARTER_CLIENT_SECRET", "s")
    si.forget_case_runner_token()
    return r


SURFACES = ["engine_mint", "outbound_auth_headers", "mint_supervisor_token",
            "mint_case_runner_token", "mint_service_token"]


def _surface(monkeypatch, name, role):
    """One outbound surface driven with ROLE."""
    monkeypatch.setenv("SUPERVISOR_CLIENT_ID", role)
    monkeypatch.setenv("CASE_RUNNER_CLIENT_ID", role)
    monkeypatch.setenv("REVIEW_STARTER_CLIENT_ID", role)
    return {
        "engine_mint": lambda: mr.engine_mint(client_id=role, secret_env="ENGINE_SECRET")(),
        "outbound_auth_headers": lambda: si.outbound_auth_headers(client_id=role, secret_env="ENGINE_SECRET"),
        "mint_supervisor_token": si.mint_supervisor_token,
        "mint_case_runner_token": si.mint_case_runner_token,
        "mint_service_token": si.mint_service_token,
    }[name]


@pytest.mark.parametrize("surface", SURFACES)
def test_each_mint_sends_exactly_prefix_plus_role(monkeypatch, rec, surface):
    """CLAIM: the client id on the wire is `t-<role>` -- not `<role>`, not `t-t-<role>`."""
    role = "iagent-engine-o"
    monkeypatch.setenv(ENV, PFX)
    _surface(monkeypatch, surface, role)()
    assert rec.ids == [PFX + role]


@pytest.mark.parametrize("surface", SURFACES)
def test_each_mint_is_unchanged_under_an_empty_prefix(monkeypatch, rec, surface):
    """CLAIM: no-op. The id on the wire is the role, as today."""
    role = "iagent-engine-o"
    _surface(monkeypatch, surface, role)()
    assert rec.ids == [role]


def test_the_exchange_post_carries_prefix_plus_role(monkeypatch):
    """CLAIM: the token-exchange form post names `t-<role>` (the REQUEST the realm received)."""
    ix = importlib.import_module("src.iagent.identity_exchange")
    seen = []

    def handler(request):
        seen.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(400, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(ix.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("IDENTITY_EXCHANGE_TOKEN_URL", "http://realm.invalid/token")
    monkeypatch.setenv("IDENTITY_EXCHANGE_CLIENT_ID", "iagent-gateway")
    monkeypatch.setenv("IDENTITY_EXCHANGE_CLIENT_SECRET", "s")
    for env, want in (("", "iagent-gateway"), (PFX, "t-iagent-gateway")):
        monkeypatch.setenv(ENV, env)
        seen.clear()
        asyncio.run(ix.exchange("a.b.c"))
        assert [s["client_id"] for s in seen] == [want]


# -- 3. the census seal ---------------------------------------------------------------------

def _is_mint_token_call(node):
    f = node.func
    return (isinstance(f, ast.Name) and f.id == "mint_token") or \
           (isinstance(f, ast.Attribute) and f.attr == "mint_token")


def _is_compose(node):
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == "compose_client_id")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "compose_client_id"))


def _composed_names(fn):
    names = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and _is_compose(n.value):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
    return names


def _composed(expr, fn):
    return _is_compose(expr) or (isinstance(expr, ast.Name) and expr.id in _composed_names(fn))


def census_violations(source: str, where: str = "<src>"):
    """Every `mint_token(` call and every dict with a client_id key and a client_secret key
    (a token-endpoint form) whose client id does not come from compose_client_id."""
    tree = ast.parse(source)
    out, sites = [], []
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in fns:
        for n in ast.walk(fn):
            expr = None
            if isinstance(n, ast.Call) and _is_mint_token_call(n):
                expr = next((k.value for k in n.keywords if k.arg == "client_id"), None)
                if expr is None and n.args:
                    expr = n.args[0]
            elif isinstance(n, ast.Dict):
                keys = [k.value if isinstance(k, ast.Constant) else None for k in n.keys]
                if "client_id" in keys and "client_secret" in keys:
                    expr = n.values[keys.index("client_id")]
                else:
                    continue
            else:
                continue
            sites.append((where, n.lineno))
            if expr is None or not _composed(expr, fn):
                out.append(f"{where}:{n.lineno}")
    return out, sites


def _tree_sources():
    for base in ("src", "agent_fleet"):
        for p in (ROOT / base).rglob("*.py"):
            if "baml_client" in p.parts or ".venv" in p.parts:
                continue
            yield p


def test_every_mint_and_token_post_composes_its_client_id():
    """CLAIM: no `mint_token(` call and no token-endpoint form post sends a client id that did
    not come from compose_client_id (directly, or a local assigned from it)."""
    bad, n_sites = [], 0
    for p in _tree_sources():
        text = p.read_text(encoding="utf-8")
        if "mint_token" not in text and "client_secret" not in text:
            continue
        v, s = census_violations(text, str(p.relative_to(ROOT)))
        bad += v
        n_sites += len(s)
    assert n_sites >= 6, f"the census found only {n_sites} sites; the walk is not seeing them"
    assert not bad, "client id not composed at: " + ", ".join(bad)


def test_census_positive_control_a_bare_literal_fails():
    """CONTROL: the walk is capable of failing."""
    src = "def f():\n    return mint_token(client_id='iagent-engine-o', client_secret='x')\n"
    assert census_violations(src)[0]
    src = "def g(cid):\n    form = {'client_id': cid, 'client_secret': 's'}\n    return form\n"
    assert census_violations(src)[0]
    ok = ("def f(role):\n    cid = compose_client_id(role)\n"
          "    return mint_token(client_id=cid, client_secret='x')\n")
    assert not census_violations(ok)[0]


# -- 4. the door list under a prefix --------------------------------------------------------

def test_the_door_list_is_composed(monkeypatch):
    """CLAIM: CAN_CALL_DOOR_CLIENTS carries ROLE names; under `t-`, azp `t-iagent-mesh` is a door
    and a bare `iagent-mesh` azp is NOT (the control: the prefix not applied)."""
    from src.iagent.authz import call_capability as cc
    monkeypatch.setenv(cc.DOOR_CLIENTS_ENV, "iagent-mesh")
    monkeypatch.setenv(ENV, PFX)
    doors = cc.door_clients()
    assert "t-iagent-mesh" in doors
    assert "iagent-mesh" not in doors
    monkeypatch.delenv(ENV)
    assert cc.door_clients() == frozenset({"iagent-mesh"})


def test_a_door_entry_already_prefixed_fails_loudly(monkeypatch):
    """CLAIM: a prefixed entry is never read as an ordinary caller's list; the error propagates."""
    from src.iagent.authz import call_capability as cc
    monkeypatch.setenv(cc.DOOR_CLIENTS_ENV, "t-iagent-mesh")
    monkeypatch.setenv(ENV, PFX)
    with pytest.raises(ip.IdentityPrefixError, match="t-iagent-mesh"):
        cc.door_clients()


# -- 5. the BFF refuses another instance's token --------------------------------------------

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

ISSUER = "https://realm.test/realms/r"
_UNSET = object()


@pytest.fixture
def bff(monkeypatch):
    mod = importlib.import_module("iagent.auth")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()

    class _K:
        pass
    _K.key = key.public_key()
    monkeypatch.setattr(mod.jwks_client, "get_signing_key_from_jwt", lambda t: _K(), raising=True)
    monkeypatch.setenv(mod.ACCEPTED_ISSUERS_ENV, ISSUER)
    monkeypatch.setenv(mod.ACCEPTED_AUDIENCES_ENV, "t-cortex-bff")

    def mint(aud, azp=_UNSET):
        now = datetime.datetime.now(datetime.timezone.utc)
        claims = {"sub": "s", "iss": ISSUER, "aud": aud, "iat": now,
                  "exp": now + datetime.timedelta(minutes=5)}
        if azp is not _UNSET:
            claims["azp"] = azp
        return jwt.encode(claims, pem, algorithm="RS256")

    def verify(token):
        """The refusal as a string, or 'ADMITTED'."""
        try:
            mod.verified_claims(token)
        except jwt.PyJWTError as exc:
            return f"{type(exc).__name__}: {exc}"
        return "ADMITTED"
    return verify, mint, mod


def test_the_bff_refuses_another_instances_token(monkeypatch, bff):
    """CLAIM: under `t-`, a `p-` audience is refused (audience check), a `t-` audience from a
    foreign client is refused as azp_not_this_instance, a missing azp is refused, and the
    instance's own token is admitted (the control)."""
    verify, mint, _ = bff
    monkeypatch.setenv(ENV, PFX)
    assert "InvalidAudienceError" in verify(mint("p-cortex-bff", "p-cortex-ui"))
    r = verify(mint("t-cortex-bff", "p-cortex-ui"))
    assert "azp_not_this_instance" in r and "InvalidAudienceError" in r
    assert "azp_not_this_instance" in verify(mint("t-cortex-bff"))
    assert verify(mint("t-cortex-bff", "t-cortex-ui")) == "ADMITTED"


def test_the_bff_azp_check_is_a_no_op_under_an_empty_prefix(bff):
    """CLAIM: with no prefix, azp is not checked."""
    verify, mint, _ = bff
    assert verify(mint("t-cortex-bff", "anything")) == "ADMITTED"
    assert verify(mint("t-cortex-bff")) == "ADMITTED"


def test_the_azp_refusal_is_a_401_through_get_current_user(monkeypatch, bff):
    """CLAIM: the refusal reaches the caller as the same 401 an audience mismatch does."""
    _verify, mint, mod = bff
    monkeypatch.setenv(ENV, PFX)
    with pytest.raises(Exception) as exc:
        mod.get_current_user(token=mint("t-cortex-bff", "p-cortex-ui"))
    assert exc.value.status_code == 401 and "azp_not_this_instance" in str(exc.value.detail)
