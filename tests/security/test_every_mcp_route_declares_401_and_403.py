"""Every MCP-tagged route declares its 401 and 403, and the 403's declaration is only as strong as
the sites behind it.

RULING (architect via Chris, 2026-11-06, G5): "every MCP-tagged route declares 401 and 403 via
`responses=` with the RefusalEnvelope schema, so the OpenAPI projection (what the MCP generator
reads) carries them; no per-route text." Chris, on gov's census (2026-11-06): the 403 conforms
(a 403 is a policy refusal and belongs in the envelope), the 401 is declared as the
`{detail: string}` it is; "envelope with refusal optional ... and the seal that lists the
non-compliant sites exactly and flips refusal to required when the list empties."

So this file holds:

  DECLARED   each MCP route's `responses` carries `ingest_api.MCP_REFUSAL_RESPONSES`' 401 and 403,
             in the app's schema and in the committed `docs/api/mcp.openapi.json`
  THE LIST   every 403 a route can reach that sends no `refusal`, EXACTLY (`ENVELOPELESS_403`).
             Reach is the name-resolved call closure over `src/iagent` from the handler and the
             route's dependencies, so it over-approximates: a row is "may reach", and a site
             missing from the census is the claim to trust. A new reachable site fails; a listed
             site that is gone or now carries a refusal fails
  COUPLING   `PolicyRefusalDetail.refusal` is optional exactly while the list has a DEBT row
  STRUCTURAL the architect, 2026-11-07: "the two structural refusals ... are declared as anyOf
             members and never carry an envelope". `StructuralRefusalDetail`'s codes are the
             STRUCTURAL rows' codes exactly, it has no `refusal` and refuses extra keys, and the
             act route's rendering of a `PromotionRefused` fits it
  401        every 401 the routes can reach sends a string `detail`
  THE DOOR   driven live: where a delegate entry would admit a `svc:` caller, the refusal names
             `config:DELEGATE_ON_BEHALF_OF` and the grantor the map holds; elsewhere the body
             reads as `StructuralRefusalDetail`

NOT CHECKED: a status an engine sends and a route forwards (`status_code=rr.status_code`); that
body is the engine's, and `relay_refusal` completes a refusal only when the engine sent one.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import time
import types
from collections import defaultdict
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.iagent import auth, gateway
from src.iagent.authz import refusal as refusal_mod
from src.iagent.ingest_api import (
    MCP_REFUSAL_RESPONSES, MCP_TAG, PolicyRefusalBody, PolicyRefusalDetail, StructuralRefusalDetail,
    UnauthenticatedBody,
)

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_ratchet_for_mcp_403", ROOT / "tests/security/test_every_policy_refusal_names_policy_binding_grantor.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

GW = "src/iagent/gateway.py"
PR = "src/iagent/promotion.py"
DEBT = "a policy refusal on the ratchet's PENDING list"
STRUCTURAL = "no grant lifts it (the ratchet's NOT_POLICY); declared as StructuralRefusalDetail, never an envelope"

#: Measured 2026-11-07 on lane/gov-mcp-refusal-responses. Keys are the ratchet's.
ENVELOPELESS_403: dict[str, str] = {
    f"{GW}::_mcp_door.door::service_token_refused": STRUCTURAL,  # a route with no on_behalf_of
    f"{GW}::_admit_on_behalf_of::not_a_delegate": DEBT,
    f"{GW}::_admit_on_behalf_of::principal_not_declared_for_delegate": DEBT,
    f"{GW}::act_on_human_task::not_authorized_to_act": DEBT,
    f"{GW}::act_on_human_task::not_authorized_to_act | <_restate_refusal_message>": DEBT,  # the Restate relay
    f"{GW}::canvas_seed::cell_cannot_see_verbs | seeded 0 of {{}} panels; every ask": DEBT,
    f"{GW}::orchestrate::cell_not_entitled | user {{}} is not entitled to perso": DEBT,
    f"{GW}::export_package::not_a_recipient_you_may_export_to": DEBT,
    f"{GW}::_export_package_from_template::not_a_recipient_you_may_export_to": DEBT,
    f"{GW}::export_package_artifact::caller {{}} is not entitled to the package for {{}}.": DEBT,  # a string detail
    f"{GW}::_engine_failure::<relay_refusal>": DEBT,  # passes an engine body through when it has no refusal
    f"{PR}::act::not_authorized_to_act": DEBT,
    f"{PR}::act::dropper_cannot_attest_origin": STRUCTURAL,  # separation of duties
}


def mcp_routes() -> list[APIRoute]:
    return [r for r in gateway.app.routes if isinstance(r, APIRoute) and MCP_TAG in (r.tags or [])]


def _ids(routes):
    return [f"{sorted(r.methods)[0]} {r.path}" for r in routes]


# --- DECLARED ------------------------------------------------------------------------------


@pytest.mark.parametrize("route", mcp_routes(), ids=_ids(mcp_routes()))
def test_the_route_declares_the_shared_401_and_403(route):
    for code in (401, 403):
        assert route.responses.get(code) is MCP_REFUSAL_RESPONSES[code], (route.path, code)


def _ref(model) -> str:
    return f"#/components/schemas/{model.__name__}"


def _declared(doc: dict) -> list[tuple[str, str, str, str]]:
    """(method, path, status, $ref) of every MCP operation's 401 and 403."""
    out = []
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if MCP_TAG not in op.get("tags", []):
                continue
            for code in ("401", "403"):
                ref = op.get("responses", {}).get(code, {}).get("content", {}) \
                    .get("application/json", {}).get("schema", {}).get("$ref")
                out.append((method, path, code, ref))
    return out


@pytest.mark.parametrize("source", ["app", "committed"])
def test_the_openapi_carries_both_on_every_mcp_operation(source):
    doc = gateway.app.openapi() if source == "app" else \
        json.loads((ROOT / "docs/api/mcp.openapi.json").read_text(encoding="utf-8"))
    rows = _declared(doc)
    assert len(rows) == 2 * len(mcp_routes()), len(rows)
    want = {"401": _ref(UnauthenticatedBody), "403": _ref(PolicyRefusalBody)}
    wrong = [r for r in rows if r[3] != want[r[2]]]
    assert not wrong, wrong
    for model in (UnauthenticatedBody, PolicyRefusalBody, PolicyRefusalDetail, StructuralRefusalDetail):
        assert model.__name__ in doc["components"]["schemas"], (source, model.__name__)
    # the structural refusals are their own anyOf member (ruled 2026-11-07), not a reading of the open one
    members = doc["components"]["schemas"][PolicyRefusalBody.__name__]["properties"]["detail"]["anyOf"]
    assert sorted(m.get("$ref") or m.get("type") for m in members) == sorted(
        [_ref(PolicyRefusalDetail), _ref(StructuralRefusalDetail), "string"]), (source, members)


def test_the_401_declares_the_challenge_header():
    assert "WWW-Authenticate" in MCP_REFUSAL_RESPONSES[401]["headers"]


# --- THE LIST ------------------------------------------------------------------------------


def _files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--", "src/iagent"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split("\n")
    return [p for p in out if p.endswith(".py") and "baml_client" not in p]


def _defs() -> dict[str, list[tuple[str, str, ast.AST]]]:
    """name -> [(path, qualname, node)]; qualname as the ratchet keys it (classes included)."""
    defs = defaultdict(list)
    for p in _files():
        tree = ast.parse((ROOT / p).read_text(encoding="utf-8"), p)

        def walk(node, stack):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs[ch.name].append((p, ".".join(stack + [ch.name]), ch))
                    walk(ch, stack + [ch.name])
                elif isinstance(ch, ast.ClassDef):
                    walk(ch, stack + [ch.name])
                else:
                    walk(ch, stack)
        walk(tree, [])
    return defs


def _own(fn):
    """Each node of fn's body, not descending into a nested def (that def is its own node)."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(ast.iter_child_nodes(n))


def _names(fn) -> set[str]:
    """What fn may call: called names, names passed (Depends(x)), and its nested defs."""
    out = set()
    for n in _own(fn):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(n.name)
        elif isinstance(n, ast.Call):
            out.add(R._fname(n))
        elif isinstance(n, ast.Name):
            out.add(n.id)
    return out


def _reach(route: APIRoute, defs) -> set[str]:
    todo = [route.endpoint.__name__] + [d.call.__name__ for d in route.dependant.dependencies]
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        for _, _, node in defs[name]:
            todo.extend(_names(node))
    return seen


def _sites(path, qual, fn, code):
    """(key, carries_refusal, body) of fn's own calls refusing with `code`."""
    assigned = {t.id: n.value for n in ast.walk(fn) if isinstance(n, ast.Assign)
                and isinstance(n.value, ast.Dict) for t in n.targets if isinstance(t, ast.Name)}
    for n in _own(fn):
        if not isinstance(n, ast.Call):
            continue
        if code == 403 and R._fname(n) == R.HELPER:
            yield f"{path}::{qual}::{R._frag(n.args[0] if n.args else None)}", True, None
        elif R._status(n) == code:
            b = R._body(n)
            if isinstance(b, ast.Name) and b.id in assigned:
                b = assigned[b.id]
            yield f"{path}::{qual}::{R._frag(b)}", R._carries_refusal(b), b


_CACHE: dict = {}


def census(code: int) -> dict[str, list]:
    """key -> [(carries_refusal, body)] over every site any MCP route may reach."""
    if code not in _CACHE:
        defs, out = _defs(), defaultdict(list)
        names = set().union(*(_reach(r, defs) for r in mcp_routes()))
        for name in names:
            for path, qual, node in defs[name]:
                for key, ok, body in _sites(path, qual, node, code):
                    out[key].append((ok, body))
        _CACHE[code] = dict(out)
    return _CACHE[code]


def test_the_envelopeless_403s_are_listed_exactly():
    got = {k for k, rows in census(403).items() if not all(ok for ok, _ in rows)}
    assert got - set(ENVELOPELESS_403) == set(), ("a reachable 403 sends no refusal: build it "
                                                  "with policy_refusal, or list it", sorted(got - set(ENVELOPELESS_403)))
    assert set(ENVELOPELESS_403) - got == set(), ("a listed 403 is gone or carries a refusal now: "
                                                  "drop its row", sorted(set(ENVELOPELESS_403) - got))


def test_the_census_reaches_the_door_and_a_compliant_site():
    """Positive control: the walk reaches the door through `dependencies=` and counts a site that complies."""
    door = census(403)[f"{GW}::_mcp_door.door::service_token_refused"]
    assert sorted(ok for ok, _ in door) == [False, True], door
    assert any(ok for rows in census(403).values() for ok, _ in rows if rows is not door)


def test_refusal_is_optional_exactly_while_a_debt_row_is_listed():
    debt = [k for k, why in ENVELOPELESS_403.items() if why == DEBT]
    required = PolicyRefusalDetail.model_fields["refusal"].is_required()
    assert required == (not debt), (
        "no DEBT row is left: make PolicyRefusalDetail.refusal required (ingest-v1 minor bump)"
        if not debt else "refusal is required but listed DEBT sites send none")


def _code(key: str) -> str:
    return key.split("::")[2].split(" | ")[0]


def test_the_structural_member_declares_exactly_the_structural_rows():
    """The join between the list and the declaration: a code is structural in both or neither."""
    declared = set(StructuralRefusalDetail.model_fields["error"].annotation.__args__)
    listed = {_code(k) for k, why in ENVELOPELESS_403.items() if why == STRUCTURAL}
    assert declared == listed, (sorted(declared), sorted(listed))


def test_the_structural_member_can_never_carry_an_envelope():
    assert "refusal" not in StructuralRefusalDetail.model_fields
    assert StructuralRefusalDetail.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        StructuralRefusalDetail.model_validate(
            {"error": "service_token_refused",
             "refusal": refusal_mod.refusal("config:DELEGATE_ON_BEHALF_OF", 'delegate_of("svc:x")')})


def _promotion_refused_renderings() -> list[set[str]]:
    """The `detail` keys of every HTTPException the gateway raises in an `except PromotionRefused`."""
    tree = ast.parse((ROOT / GW).read_text(encoding="utf-8"))
    out = []
    for h in ast.walk(tree):
        if isinstance(h, ast.ExceptHandler) and h.type is not None and "PromotionRefused" in ast.unparse(h.type):
            for n in ast.walk(h):
                # by name: the status is `exc.status`, never a constant `R._status` can read
                if isinstance(n, ast.Call) and R._fname(n) == "HTTPException":
                    d = next((k.value for k in n.keywords if k.arg == "detail"), None)
                    if isinstance(d, ast.Dict):
                        out.append({k.value for k in d.keys if isinstance(k, ast.Constant)})
    return out


def test_a_promotion_refusal_renders_as_the_structural_member():
    """`dropper_cannot_attest_origin` reaches the wire through these renderings, so each fits."""
    got = _promotion_refused_renderings()
    assert got, "no `except PromotionRefused` rendering found: the census of renderings is empty"
    for keys in got:
        assert "error" in keys and keys <= set(StructuralRefusalDetail.model_fields), keys


def test_every_reachable_401_sends_a_string():
    sites = census(401)
    assert sites, "the census reaches no 401: the walk lost auth.get_current_user"
    not_str = [k for k, rows in sites.items() for _, b in rows
               if not (isinstance(b, ast.JoinedStr) or (isinstance(b, ast.Constant) and isinstance(b.value, str)))]
    assert not not_str, not_str


# --- THE DOOR, live ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _jwks(monkeypatch, key):
    pub = key.public_key()
    monkeypatch.setattr(auth.jwks_client, "get_signing_key_from_jwt",
                        lambda tok: types.SimpleNamespace(key=pub))
    monkeypatch.setattr(auth, "_get_entitlement_cache", lambda: None)
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", json.dumps({"svc:zz-delegate": ["zz@example.com"]}))


def _bearer(key, authz_id):
    tok = jwt.encode({"exp": time.time() + 600, "iat": time.time(), "sub": "33333333-aaaa-bbbb-cccc-000000000009",
                      "azp": "x", auth.USER_ENTITLEMENT_CLAIM: authz_id}, key, algorithm="RS256")
    return {"Authorization": f"Bearer {tok}"}


def _stub(route: APIRoute) -> TestClient:
    """The route's own dependency chain in front of a handler that does nothing."""
    app = FastAPI()

    async def reached():
        return {"reached": True}

    app.add_api_route("/x", reached, methods=["GET"],
                      dependencies=[Depends(d.call) for d in route.dependant.dependencies])
    return TestClient(app)


@pytest.mark.parametrize("route", mcp_routes(), ids=_ids(mcp_routes()))
def test_a_refused_service_caller_reads_the_declared_403(route, key):
    r = _stub(route).get("/x", headers=_bearer(key, "svc:zz-not-a-delegate"))
    assert r.status_code == 403, (route.path, r.status_code)
    PolicyRefusalBody.model_validate(r.json())
    detail = r.json()["detail"]
    if gateway._body_names_on_behalf_of(route):
        mb = 'delegate_of("svc:zz-not-a-delegate")'
        want = refusal_mod.refusal("config:DELEGATE_ON_BEHALF_OF", mb)   # the grantor map's answer
        got = PolicyRefusalDetail.model_validate(detail).refusal
        assert got is not None and got.model_dump(mode="json") == want, (route.path, got)
        with pytest.raises(ValidationError):                             # a policy refusal is not structural
            StructuralRefusalDetail.model_validate(detail)
    else:
        StructuralRefusalDetail.model_validate(detail)


@pytest.mark.parametrize("route", mcp_routes(), ids=_ids(mcp_routes()))
def test_an_unauthenticated_caller_reads_the_declared_401(route):
    r = _stub(route).get("/x")
    assert r.status_code == 401, (route.path, r.status_code)
    UnauthenticatedBody.model_validate(r.json())
    assert r.headers.get("www-authenticate") == "Bearer"
