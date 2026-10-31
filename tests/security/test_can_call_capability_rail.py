"""The `can_call:<tag>` call policy for a door client: DENY-BY-DEFAULT, AND over a route's tags.

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
from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import human_tasks  # noqa: E402
from src.iagent.auth import User, get_current_user  # noqa: E402
from src.iagent.authz import call_capability as cc  # noqa: E402
from src.iagent.ingest_api import INGEST_V1_TAG  # noqa: E402

DOC = ROOT / "docs" / "api" / "mcp.openapi.json"
DOOR = "a-door-client-for-the-test"


def _doc_ops() -> list[tuple[str, str, list[str]]]:
    doc = json.loads(DOC.read_text(encoding="utf-8"))
    return [(m, p, list(op.get("tags") or [])) for p, item in doc["paths"].items()
            for m, op in item.items() if isinstance(op, dict)]


def _served_tags() -> set[str]:
    return {t for _, _, ts in _doc_ops() for t in ts}


def _pick():
    ops = _doc_ops()
    one = next(o for o in ops if len(o[2]) == 1)
    # (the v1 response check in conftest inspects any route tagged v1, so a toy route avoids that tag)
    two = next(o for o in ops if len(o[2]) == 2 and INGEST_V1_TAG not in o[2])
    return one, two


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


def _app(azp, tags_for):
    app = FastAPI()
    reached: list[str] = []
    for path, tags in tags_for.items():
        def _h(path=path):
            reached.append(path)
            return {"ok": True}
        app.add_api_route(path, _h, methods=["GET"], tags=tags,
                          dependencies=[Depends(cc.require_call_capability)])
    app.dependency_overrides[get_current_user] = lambda: User(id="u1", authz_id="who-1", azp=azp,
                                                         entitlement_source="none")
    return TestClient(app), reached


def _setup(monkeypatch, doors=DOOR):
    if doors is None:
        monkeypatch.delenv(cc.DOOR_CLIENTS_ENV, raising=False)
    else:
        monkeypatch.setenv(cc.DOOR_CLIENTS_ENV, doors)
    return _pick()


# -- (a) the door, unit ----------------------------------------------------------------------

def test_a_door_with_no_grants_is_refused_on_the_first_sorted_tag(monkeypatch, topaz):
    _, two = _setup(monkeypatch)
    client, reached = _app(DOOR, {"/r": two[2]})
    r = client.get("/r")
    first = sorted(two[2])[0]
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["error"] == "not_entitled_to_call"
    assert d["refusal"]["policy_id"] == f"capability_grants:can_call:{first}"
    assert d["refusal"]["missing_binding"] == f"can_invoke can_call:{first}"
    assert reached == []
    assert [c for c, _ in topaz.calls] == [f"can_call:{first}"]


def test_a_door_missing_exactly_one_tag_is_refused_naming_it(monkeypatch, topaz):
    _, two = _setup(monkeypatch)
    missing = sorted(two[2])[-1]
    topaz.grants = {f"can_call:{t}" for t in two[2] if t != missing}
    client, reached = _app(DOOR, {"/r": two[2]})
    r = client.get("/r")
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["refusal"]["missing_binding"] == f"can_invoke can_call:{missing}"
    assert d["tag"] == missing
    assert reached == []


def test_a_door_holding_every_tag_reaches_the_handler(monkeypatch, topaz):
    _, two = _setup(monkeypatch)
    topaz.grants = {f"can_call:{t}" for t in two[2]}
    client, reached = _app(DOOR, {"/r": two[2]})
    assert client.get("/r").status_code == 200
    assert reached == ["/r"]
    assert sorted(c for c, _ in topaz.calls) == sorted(f"can_call:{t}" for t in two[2])
    assert {w for _, w in topaz.calls} == {"who-1"}


def test_a_non_door_caller_is_untouched(monkeypatch, topaz):
    _, two = _setup(monkeypatch)
    client, reached = _app("not-" + DOOR, {"/r": two[2]})
    assert client.get("/r").status_code == 200
    assert reached == ["/r"] and topaz.calls == []


def test_a_caller_with_no_azp_is_untouched(monkeypatch, topaz):
    _, two = _setup(monkeypatch)
    client, _reached = _app(None, {"/r": two[2]})
    assert client.get("/r").status_code == 200
    assert topaz.calls == []


def test_unset_env_makes_every_caller_a_non_door(monkeypatch, topaz):
    _, two = _setup(monkeypatch, doors=None)
    client, reached = _app(DOOR, {"/r": two[2]})
    assert client.get("/r").status_code == 200
    assert reached == ["/r"] and topaz.calls == []


def test_a_door_route_with_no_tags_is_refused(monkeypatch, topaz):
    _setup(monkeypatch)
    client, reached = _app(DOOR, {"/r": []})
    r = client.get("/r")
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["refusal"]["missing_binding"] == "can_invoke can_call:"
    assert reached == [] and topaz.calls == []


def test_unavailable_and_unconfigured_are_503(monkeypatch, topaz):
    one, _ = _setup(monkeypatch)
    client, _r = _app(DOOR, {"/r": one[2]})
    topaz.raises = human_tasks.AuthorizationUnavailable("x")
    r = client.get("/r")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "authorization_unavailable"
    topaz.raises = human_tasks.AuthorizationUnconfigured("x")
    r = client.get("/r")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "authorization_unconfigured"


def test_door_list_parsing(monkeypatch):
    monkeypatch.setenv(cc.DOOR_CLIENTS_ENV, " a , ,b ")
    assert cc.door_clients() == frozenset({"a", "b"})


# -- (b) wiring against the real gateway ----------------------------------------------------

def test_b_the_dependency_is_on_exactly_the_mcp_tagged_routes():
    from fastapi.routing import APIRoute

    from src.iagent import gateway
    from src.iagent.ingest_api import MCP_ROUTES, MCP_TAG
    wired, tagged = set(), set()
    for r in gateway.app.routes:
        if not isinstance(r, APIRoute):
            continue
        has = any(d.call is cc.require_call_capability for d in r.dependant.dependencies)
        is_mcp = MCP_TAG in (r.tags or [])
        keys = {(m, r.path) for m in r.methods if m not in ("HEAD", "OPTIONS")}
        if has:
            wired |= keys
        if is_mcp:
            tagged |= keys
        assert has == is_mcp, (r.path, sorted(r.methods), r.tags)
    assert tagged, "no MCP-tagged route found"
    assert wired == tagged
    assert tagged == set(MCP_ROUTES)


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

def test_d_the_shipped_rail_validates():
    pol = ROOT / "policy"
    assert vp.validate(pol, pol) == []


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
    groups = yaml.safe_load((ROOT / "policy" / "groups.yaml").read_text(encoding="utf-8"))
    node = groups.get("groups", groups) if isinstance(groups, dict) else groups
    if isinstance(node, dict):
        names = set(node)
    else:
        names = {g.get("name") or g.get("id") for g in node if isinstance(g, dict)}
    banned = _served_tags() | {n for n in names if n}
    assert banned
    assert not (literals & banned), literals & banned
    assert DOOR not in literals
