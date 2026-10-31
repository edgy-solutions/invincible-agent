"""The `can_call:<tag>` call policy for a door client: confined to the MCP surface app-wide,
DENY-BY-DEFAULT, AND over a route's tags.

Tags are read from docs/api/mcp.openapi.json (the served MCP document) and routes from the real
gateway app; no tag, group or client id is typed here.

Run:  uv run python -m pytest tests/security/test_can_call_capability_rail.py -q
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "src", ROOT / "policy" / "sync"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import validate_policy as vp  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.routing import Route  # noqa: E402

from src.iagent import human_tasks  # noqa: E402
from src.iagent.authz import call_capability as cc  # noqa: E402
from src.iagent.ingest_api import INGEST_V1_TAG, MCP_ROUTES, MCP_TAG  # noqa: E402

DOC = ROOT / "docs" / "api" / "mcp.openapi.json"
DOOR = "a-door-client-for-the-test"
WHO = "who-1"
SKIP = ("HEAD", "OPTIONS")


def _doc_ops() -> list[tuple[str, str, list[str]]]:
    doc = json.loads(DOC.read_text(encoding="utf-8"))
    return [(m, p, list(op.get("tags") or [])) for p, item in doc["paths"].items()
            for m, op in item.items() if isinstance(op, dict)]


def _served_tags() -> set[str]:
    return {t for _, _, ts in _doc_ops() for t in ts}


def _pick():
    ops = _doc_ops()
    # (the v1 response check in conftest inspects any route tagged v1, so a toy route avoids that tag)
    two = next(o for o in ops if len(o[2]) == 2 and MCP_TAG in o[2] and INGEST_V1_TAG not in o[2])
    off = next(t for t in sorted(_served_tags()) if t != MCP_TAG)
    return two[2], off


class Topaz:
    def __init__(self):
        self.grants: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self.raises: Exception | None = None

    def __call__(self, capability, caller):
        self.calls.append((capability, caller))
        if self.raises:
            raise self.raises
        return capability in self.grants


@pytest.fixture
def topaz(monkeypatch):
    t = Topaz()
    monkeypatch.setattr(human_tasks, "can_invoke_or_unavailable", t)
    return t


@pytest.fixture
def idents(monkeypatch):
    """`_identify` as a dict lookup, token -> (authz_id, azp); a token not in it is unverifiable."""
    table = {"door": (WHO, DOOR), "plain": (WHO, "not-" + DOOR), "noazp": (WHO, None)}
    seen: list[str] = []

    def _fake(token):
        seen.append(token)
        return table.get(token)

    monkeypatch.setattr(cc, "_identify", _fake)
    monkeypatch.setenv(cc.DOOR_CLIENTS_ENV, DOOR)
    _fake.seen = seen
    return _fake


def _h(token="door"):
    return {"Authorization": f"Bearer {token}"}


def _toy():
    two, off = _pick()
    app = FastAPI()
    reached: list[str] = []

    def _gate():
        raise HTTPException(403, {"error": "persona_gate"})

    def _add(path, tags, deps=()):
        def _handler(path=path):
            reached.append(path)
            return {"ok": True}
        app.add_api_route(path, _handler, methods=["GET"], tags=tags, dependencies=list(deps))

    _add("/two", two)
    _add("/one", [MCP_TAG])
    _add("/off", [off])
    _add("/none", [])
    _add("/gated", [MCP_TAG], deps=[Depends(_gate)])
    app.add_middleware(cc.DoorGuard, router=app.router)
    return TestClient(app), reached, two, off


# -- (a) the door, unit ----------------------------------------------------------------------

def test_a_door_with_no_grants_is_refused_on_the_first_sorted_tag(idents, topaz):
    client, reached, two, _ = _toy()
    r = client.get("/two", headers=_h())
    first = sorted(two)[0]
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["error"] == "not_entitled_to_call"
    assert d["refusal"]["policy_id"] == f"capability_grants:can_call:{first}"
    assert d["refusal"]["missing_binding"] == f"can_invoke can_call:{first}"
    assert reached == []
    assert [c for c, _ in topaz.calls] == [f"can_call:{first}"]


def test_a_door_missing_exactly_one_tag_is_refused_naming_it(idents, topaz):
    client, reached, two, _ = _toy()
    missing = sorted(two)[-1]
    topaz.grants = {f"can_call:{t}" for t in two if t != missing}
    r = client.get("/two", headers=_h())
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["refusal"]["missing_binding"] == f"can_invoke can_call:{missing}"
    assert d["tag"] == missing
    assert reached == []


def test_a_door_holding_every_tag_of_the_route_reaches_the_handler(idents, topaz):
    client, reached, two, _ = _toy()
    topaz.grants = {f"can_call:{t}" for t in two}
    assert client.get("/two", headers=_h()).status_code == 200
    assert reached == ["/two"]
    assert sorted(c for c, _ in topaz.calls) == sorted(f"can_call:{t}" for t in two)
    assert {w for _, w in topaz.calls} == {WHO}


@pytest.mark.parametrize("path", ["/off", "/none", "/nope"])
def test_a_door_holding_every_served_tag_is_still_refused_off_the_surface(idents, topaz, path):
    client, reached, _, _ = _toy()
    topaz.grants = {f"can_call:{t}" for t in _served_tags()}
    r = client.get(path, headers=_h())
    assert r.status_code == 403, (path, r.status_code, r.text)  # an unmatched path is 403, not 404
    d = r.json()["detail"]
    assert d["error"] == "not_entitled_to_call"
    assert d["on_surface"] is False
    assert d["refusal"]["policy_id"] == "capability_grants:can_call:"
    assert reached == [] and topaz.calls == []


def test_the_routes_own_gate_still_decides_beneath_the_door(idents, topaz):
    client, reached, _, _ = _toy()
    topaz.grants = {f"can_call:{t}" for t in _served_tags()}
    r = client.get("/gated", headers=_h())
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "persona_gate"
    assert reached == []


def test_a_non_door_token_on_the_same_route_is_untouched(idents, topaz):
    # the control for the refusal above: the same route, differing only in azp
    client, reached, _, _ = _toy()
    for tok in ("plain", "noazp"):
        assert client.get("/off", headers=_h(tok)).status_code == 200
    assert reached == ["/off", "/off"] and topaz.calls == []


def test_no_authorization_header_is_untouched(idents, topaz):
    client, reached, _, _ = _toy()
    assert client.get("/off").status_code == 200
    assert reached == ["/off"] and topaz.calls == [] and idents.seen == []


def test_an_unverifiable_token_is_passed_through_to_the_route(idents, topaz):
    client, reached, _, _ = _toy()
    assert client.get("/off", headers=_h("garbage")).status_code == 200
    assert reached == ["/off"] and topaz.calls == []


def test_unset_env_does_no_token_work(monkeypatch, idents, topaz):
    monkeypatch.delenv(cc.DOOR_CLIENTS_ENV, raising=False)
    client, reached, _, _ = _toy()
    assert client.get("/off", headers=_h()).status_code == 200
    assert reached == ["/off"] and topaz.calls == []
    assert idents.seen == []  # _identify was never called


def test_unavailable_and_unconfigured_are_503(idents, topaz):
    client, _r, _, _ = _toy()
    topaz.raises = human_tasks.AuthorizationUnavailable("x")
    r = client.get("/one", headers=_h())
    assert r.status_code == 503 and r.json()["detail"]["error"] == "authorization_unavailable"
    topaz.raises = human_tasks.AuthorizationUnconfigured("x")
    r = client.get("/one", headers=_h())
    assert r.status_code == 503 and r.json()["detail"]["error"] == "authorization_unconfigured"


def test_door_list_parsing(monkeypatch):
    monkeypatch.setenv(cc.DOOR_CLIENTS_ENV, " a , ,b ")
    assert cc.door_clients() == frozenset({"a", "b"})


def test_identify_is_the_authz_identity_and_azp_and_none_on_any_failure(monkeypatch):
    """The arms above patch `_identify`; this one runs it, so the door keys on authz_id, never sub."""
    from src.iagent import auth
    payload = {"sub": "a-sub", "azp": "a-door"}
    payload[auth.USER_ENTITLEMENT_CLAIM] = "an-authz-id"
    monkeypatch.setattr(auth, "verified_claims", lambda token: dict(payload))
    assert cc._identify("t") == ("an-authz-id", "a-door")

    def _bad(token):
        raise ValueError("bad signature")
    monkeypatch.setattr(auth, "verified_claims", _bad)
    assert cc._identify("t") is None
    monkeypatch.setattr(auth, "verified_claims", lambda token: {"azp": "a-door"})  # no identity at all
    assert cc._identify("t") is None


# -- (b) wiring against the real gateway ----------------------------------------------------

def test_b_the_guard_is_registered_once_and_innermost():
    from fastapi.middleware.cors import CORSMiddleware

    from src.iagent import gateway
    kinds = [m.cls for m in gateway.app.user_middleware]
    assert kinds.count(cc.DoorGuard) == 1
    assert CORSMiddleware in kinds
    # user_middleware is outermost-first, so the innermost has the highest index
    assert kinds.index(cc.DoorGuard) > kinds.index(CORSMiddleware)
    assert kinds.index(cc.DoorGuard) == len(kinds) - 1


def test_b_every_route_is_one_the_guard_covers():
    # The guard handles http only: a websocket route or a mount would be a second door.
    from src.iagent import gateway
    bad = [(type(r).__name__, getattr(r, "path", None)) for r in gateway.app.routes
           if not isinstance(r, (APIRoute, Route))]
    assert bad == [], bad


def test_b_the_mcp_tagged_routes_are_exactly_the_served_surface():
    from src.iagent import gateway
    tagged = {(m, r.path) for r in gateway.app.routes
              if isinstance(r, APIRoute) and MCP_TAG in (r.tags or [])
              for m in r.methods - set(SKIP)}
    assert tagged and tagged == set(MCP_ROUTES)


def test_b_census_a_door_granted_nothing_is_refused_on_every_route(idents, topaz):
    from src.iagent import gateway
    client = TestClient(gateway.app)  # not entered: the lifespan never runs
    n = 0
    for r in gateway.app.routes:
        method = next(m for m in sorted(r.methods) if m not in SKIP)
        path = re.sub(r"\{[^}]+\}", "x", r.path)
        resp = client.request(method, path, headers=_h())
        assert resp.status_code == 403, (method, r.path, resp.status_code, resp.text[:200])
        d = resp.json()["detail"]
        assert d["error"] == "not_entitled_to_call", (method, r.path, d)
        tags = getattr(r, "tags", None) or []
        if MCP_TAG in tags:
            first = sorted(set(map(str, tags)))[0]
            assert d["refusal"]["missing_binding"] == f"can_invoke can_call:{first}", (r.path, d)
        else:
            assert d["on_surface"] is False, (method, r.path, d)
        n += 1
    assert n == len(gateway.app.routes) and n > 0


# -- (c) the validator ----------------------------------------------------------------------

@pytest.fixture
def pol(tmp_path):
    d = tmp_path / "policy"
    shutil.copytree(ROOT / "policy", d, ignore=shutil.ignore_patterns("__pycache__", "overlays"))
    return d


def _add(d, key, row):
    p = d / "capability_grants.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["capabilities"][key] = row
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _a_group(d):
    data = yaml.safe_load((d / "capability_grants.yaml").read_text(encoding="utf-8"))
    for row in data["capabilities"].values():
        if row.get("grant_to_groups"):
            return row["grant_to_groups"][0]
    raise AssertionError("no group row in the seed")


def test_c_a_served_tag_validates(pol):
    tag = sorted(_served_tags())[0]
    _add(pol, f"can_call:{tag}", {"granted_by": "t", "reason": "t",
                                  "grant_to_groups": [_a_group(pol)]})
    assert vp.validate(pol, pol) == []


def test_c_an_unserved_tag_is_refused_naming_key_and_doc(pol):
    _add(pol, "can_call:not-a-served-tag", {"granted_by": "t", "reason": "t",
                                            "grant_to_groups": [_a_group(pol)]})
    errs = vp.validate(pol, pol)
    hit = [e for e in errs if "can_call:not-a-served-tag" in e]
    assert hit and "mcp.openapi.json" in hit[0], errs


def test_c_known_call_tags_equals_the_independent_union():
    tags, notes = vp.known_call_tags()
    assert tags == _served_tags() and tags
    assert notes == [f"{DOC.as_posix()} ({len(tags)} tag(s))"]


# -- (d) the shipped rail -------------------------------------------------------------------

def _load(name):
    return yaml.safe_load((ROOT / "policy" / name).read_text(encoding="utf-8"))


def _group_names() -> set[str]:
    groups = _load("groups.yaml")
    node = groups.get("groups", groups) if isinstance(groups, dict) else groups
    if isinstance(node, dict):
        return set(node)
    return {g.get("name") or g.get("id") for g in node if isinstance(g, dict)}


def test_d_the_shipped_rail_validates():
    pol = ROOT / "policy"
    assert vp.validate(pol, pol) == []


def test_d_every_shipped_call_row_names_a_served_tag_and_a_populated_group():
    rows = {k: v for k, v in _load("capability_grants.yaml")["capabilities"].items()
            if k.startswith(cc.CALL_PREFIX)}
    assert rows, "no can_call row ships"
    members = {g for u in _load("users.yaml")["users"] for g in (u.get("groups") or [])}
    known = _group_names()
    for key, row in rows.items():
        assert key[len(cc.CALL_PREFIX):] in _served_tags(), key
        assert row.get("grant_to_groups"), key
        for g in row["grant_to_groups"]:
            assert g in known, (key, g)
            assert g in members, f"{key}: group {g} has no member, so the row grants nobody"


# -- (e) no case in code --------------------------------------------------------------------

def _call_part_of_validator() -> str:
    s = (ROOT / "policy" / "sync" / "validate_policy.py").read_text(encoding="utf-8")
    a = s.index("def known_call_tags")
    b = s.index("#: No grantee is named in code")
    c = s.index("# `can_call:<T>` (2026-10-30")
    d = s.index("# recipient_readers.yaml: validated WHEN PRESENT")
    return s[a:b] + s[c:d]


def test_e_no_served_tag_group_or_door_client_is_quoted_in_code():
    srcs = [(ROOT / "src" / "iagent" / "authz" / "call_capability.py").read_text(encoding="utf-8"),
            _call_part_of_validator()]
    literals = {m[1] for s in srcs for m in re.findall(r"""(["'])([^"'\n]*)\1""", s)}
    banned = _served_tags() | {n for n in _group_names() if n}
    assert banned
    assert not (literals & banned), literals & banned
    assert DOOR not in literals
