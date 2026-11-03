"""Review seals for #181 (lane saf, NOT committed to fin's branch). Drives the REAL
`can_read_recipient` through httpx.MockTransport: the doubles in the PR raise a builtin
ConnectionError only; Topaz fails in other ways.

  P1  every failure form x every door that asks the rail  -> 503, never 403, never 200
  P2  every call site of the rail is a door P1 covers (AST census from the code)
  P3  (removed, superseded by the 10-31 ruling) pickers: omit under each failure form
  P4  (removed, superseded by the 10-31 ruling) the omission is distinguishable from "no readers"
  P5  malformed bodies that DO NOT raise: must not admit
  P6  (saf's packet, 10-31) a picker/offer: outage -> 503, no readers -> 403, both sites
  P6-plan-a/b/c  the plan owner counts like any other owner (architect relay, 10-31)
  TEMPLATE ROUTE  `POST /export/package` with a template_id: an outage is 503 at the ROUTE

Provenance: saf's review of #181 (lane saf, 10-31), committed here by lane fin. Changes from saf's
file: P3/P4 removed (above); P6 added verbatim from saf's packet; the plan arms and the template
route seal added; the `topaz` fixture gained `only` (fail one owner alone) and `rows` (the rows
the double answers from); the P6 arms serve the plan profile set (`plan_served`) instead of
`_no_plan`, because an engine-cost that cannot be asked is itself a 503 at a picker.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_fleet.cost_agent import main as cost_main
from agent_fleet.cost_agent import measures
from agent_fleet.finance_agent import main as fin_main
from agent_fleet.utils import recipient_readers as rr
from src.iagent import gateway
from tests.recipient_rail_double import rail_rows
from tests.test_finance_and_cost_recipient_readers_ride_the_rail import (
    BEARER, OWNERS, ROWS, _Caller, _Resp, _User, _bff_download, _no_plan, _post_export)
from tests.finance import test_fin_package_export as fpe

REPO = pathlib.Path(__file__).resolve().parents[1]

FORMS = {
    "connect_error": lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused", request=req)),
    "read_timeout": lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=req)),
    "http_503": lambda req: httpx.Response(503, text="unavailable", request=req),
    "http_500": lambda req: httpx.Response(500, text="boom", request=req),
    "empty_200": lambda req: httpx.Response(200, content=b"", request=req),
    "html_200": lambda req: httpx.Response(200, text="<html>gateway</html>", request=req),
    "list_200": lambda req: httpx.Response(200, json=[], request=req),
    "null_200": lambda req: httpx.Response(200, json=None, request=req),
}


@pytest.fixture
def topaz(monkeypatch):
    """The REAL can_read_recipient over a MockTransport. state['mode'] = None -> answers from the
    shipped rows; a FORMS key -> that failure; a callable -> custom."""
    st = {"mode": None, "calls": 0, "only": None}
    rows = rail_rows()
    st["rows"] = rows
    real = httpx.Client

    def handler(req):
        st["calls"] += 1
        m = st["mode"]
        import json as _j
        b = _j.loads(req.content)
        owner, scope = b["object_id"].split(":", 1)
        if m in FORMS and (st["only"] is None or owner in st["only"]):  # `only`: one owner fails alone
            return FORMS[m](req)
        if callable(m):
            return m(req)
        return httpx.Response(200, json={"check": b["subject_id"] in rows.get((owner, scope), ())}, request=req)

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return real(*a, **k)

    monkeypatch.setattr(rr.httpx, "Client", factory)
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://topaz.test")
    return st


@pytest.fixture
def doors(monkeypatch):
    monkeypatch.setattr(measures, "_repo_root", lambda: None)
    monkeypatch.setattr(fin_main, "_repo_root", lambda: None)
    who = {"v": None}
    monkeypatch.setattr(cost_main, "_current_caller", lambda: _Caller(who["v"]))
    monkeypatch.setattr(fin_main, "_current_caller", lambda: _Caller(who["v"]))
    clients = {"cost": TestClient(cost_main.app), "finance": TestClient(fin_main.app)}

    class _C:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None, **k): return _Resp()
        async def post(self, url, json=None, headers=None, **k):
            return fpe._Resp(200, dict(fpe.GOOD_ENGINE_BODY))

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _C)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(who["v"])
    with TestClient(gateway.app) as bff:
        def go(door, owner, scope, reader):
            who["v"] = reader
            if door == "engine_artifact":
                return clients[owner].get("/artifact/" + OWNERS[owner](scope))
            if door == "bff_download":
                return bff.get(_bff_download(owner, scope), headers=BEARER)
            if door == "bff_export_cost":
                return _post_export(monkeypatch, reader, scope)
            if door == "bff_export_fin_template":
                body = gateway.ExportPackageRequest(**fpe.GOOD)
                try:
                    out = asyncio.run(gateway.export_package(body, fpe._Req(), _User(reader)))
                    return type("R", (), {"status_code": 200, "detail": out})
                except HTTPException as e:
                    return type("R", (), {"status_code": e.status_code, "detail": e.detail})
            raise AssertionError(door)
        yield go
    gateway.app.dependency_overrides.clear()


def _door_matrix():
    cost = next((s, r) for o, s, r in ROWS if o == "cost")
    fin = next((s, r) for o, s, r in ROWS if o == "finance")
    out = []
    for door in ("engine_artifact", "bff_download"):
        out += [(door, "cost", *cost), (door, "finance", *fin)]
    out.append(("bff_export_cost", "cost", *cost))
    out.append(("bff_export_fin_template", "finance", *fin))
    return out


MATRIX = [pytest.param(*m, id=f"{m[0]}:{m[1]}") for m in _door_matrix()]


@pytest.mark.parametrize("door,owner,scope,reader", MATRIX)
def test_control_the_door_admits_its_reader_when_topaz_answers(topaz, doors, monkeypatch, door, owner, scope, reader):
    if door.startswith("bff_export"):
        _no_plan(monkeypatch)
    got = doors(door, owner, scope, reader)
    assert got.status_code not in (403, 503), (door, got.status_code)


@pytest.mark.parametrize("form", sorted(FORMS))
@pytest.mark.parametrize("door,owner,scope,reader", MATRIX)
def test_p1_a_topaz_failure_form_is_a_503_at_every_door(topaz, doors, monkeypatch, door, owner, scope, reader, form):
    if door.startswith("bff_export"):
        _no_plan(monkeypatch)
    topaz["mode"] = form
    got = doors(door, owner, scope, reader)
    assert got.status_code == 503, (door, form, got.status_code)


# ---- P2: census of the rail's call sites, from the code ---------------------------------------
COVERED = {
    # enclosing function -> door in MATRIX that reaches it
    ("src/iagent/gateway.py", "_rail_reader"): "all bff doors",
    ("agent_fleet/cost_agent/main.py", "artifact"): "engine_artifact:cost",
    ("agent_fleet/cost_agent/main.py", "_plan_reader_or_refuse"): "plan (pre-existing, not in this PR)",
    ("agent_fleet/finance_agent/main.py", "get_artifact"): "engine_artifact:finance",
}


def _sites():
    found = set()
    for base in ("src", "agent_fleet"):
        for p in (REPO / base).rglob("*.py"):
            if ".venv" in p.parts or "baml" in p.name:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for n in ast.walk(fn):
                        if isinstance(n, ast.Call):
                            f = n.func
                            nm = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
                            if nm == "can_read_recipient":
                                found.add((str(p.relative_to(REPO)).replace("\\", "/"), fn.name))
    return found


def test_p2_every_call_site_of_the_rail_is_a_covered_door():
    sites = _sites()
    assert sites - set(COVERED) == set(), f"a door asks the rail and this review did not cover it: {sites - set(COVERED)}"
    assert set(COVERED) - sites == set(), "COVERED names a site that is gone"


def _gateway_callers(names):
    tree = ast.parse((REPO / "src/iagent/gateway.py").read_text(encoding="utf-8"))
    out = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                if isinstance(n, ast.Name) and n.id in names or (isinstance(n, ast.Attribute) and n.attr in names):
                    out.setdefault(fn.name, set()).add(getattr(n, "id", None) or n.attr)
    return out


def test_p2_every_gateway_caller_of_the_list_helpers_is_a_door_in_the_matrix_or_a_picker():
    callers = _gateway_callers({"_export_recipients_for", "_fin_export_recipients_for"})
    known = {"_export_recipients_for", "_fin_export_recipients_for", "_picker_scopes",  # was _export_recipients_or_none (deleted)
             "export_package", "export_package_artifact", "_export_package_from_template"}
    assert set(callers) <= known, set(callers) - known


# ---- P3 / P4 REMOVED: superseded by the architect's 10-31 ruling ("an outage answers 503, no
# readers answers 403"). P3 pinned "the picker omits on an outage", P4 pinned that omission being
# distinguishable from no-readers; P6 below is the ruled form of both.


# ---- P5: malformed bodies that do not raise ---------------------------------------------------

@pytest.mark.parametrize("body", [{}, {"check": None}, {"check": "false"}, {"check": "no"}, {"check": 0},
                                  {"check": "0"}, {"allowed": True}])
def test_p5_a_200_body_that_is_not_a_true_boolean_never_admits(topaz, body):
    topaz["mode"] = lambda req: httpx.Response(200, json=body, request=req)
    scope, reader = next((s, r) for o, s, r in ROWS if o == "cost")
    try:
        got = rr.can_read_recipient("cost", scope, reader)
    except Exception:
        return  # raising is an outage: 503, fail closed
    assert got is False, f"{body!r} ADMITTED"


# ---- P6: the ruled form (architect 10-31): an outage is 503, "no readers" is 403 ---------------
# Verbatim from saf's packet except: `_no_plan(monkeypatch)` became the `plan_served` fixture. With the
# ruling, an engine-cost that cannot be asked is itself a 503 at a picker, so `_no_plan` could no
# longer give the control its 200 or the no-readers case its 403.

@pytest.fixture
def plan_served(monkeypatch):
    """engine-cost SERVES its real profile set and `can_export` admits: the plan half of the
    picker is answerable, so the owners under test are the only thing that can fail."""
    with TestClient(cost_main.app) as eng:
        monkeypatch.setattr(gateway, "_cost_profiles_get",
                            lambda url: eng.get("/answers_export/profiles"))
        monkeypatch.setattr("agent_fleet.utils.export_capability.can_export", lambda *a, **k: True)
        yield


_SITES = [("get", "/export/package/recipients", None),
          ("post", "/export/package/recipients", {"answers": [{"artifact_id": "a1"}]})]


def _call(c, method, path, body):
    return c.get(path, headers=BEARER) if method == "get" else c.post(path, headers=BEARER, json=body)


@pytest.mark.parametrize("method,path,body", _SITES)
@pytest.mark.parametrize("form", sorted(FORMS))
def test_p6_an_outage_at_a_picker_or_offer_is_503(topaz, doors, plan_served, monkeypatch, form, method, path, body):
    scope, reader = next((s, r) for o, s, r in ROWS if o == "cost")
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(reader)
    with TestClient(gateway.app) as c:
        assert _call(c, method, path, body).status_code == 200  # control: Topaz up, a reader is listed
        topaz["mode"] = form
        got = _call(c, method, path, body)
    assert got.status_code == 503, (form, got.status_code, got.text[:120])


@pytest.mark.parametrize("method,path,body", _SITES)
def test_p6_no_readers_at_a_picker_or_offer_is_403(topaz, doors, plan_served, monkeypatch, method, path, body):
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User("mallory@example.com")
    with TestClient(gateway.app) as c:
        got = _call(c, method, path, body)
    assert got.status_code == 403, (got.status_code, got.text[:120])


@pytest.fixture(autouse=True)
def _offer_resolves(monkeypatch):
    # the offer resolves its answers from the store before it asks the rail; the rail is what is under test
    monkeypatch.setattr(gateway, "_resolve_export_answers", lambda ids, uid: [])


# ---- P6-plan: a plan recipient counts like any other owner's (architect relay, 10-31) ----------

def _plan_row():
    """(scope, reader) of a plan row, READ from the rail file the double answers from."""
    rows = rail_rows()
    scope = next(s for (o, s) in sorted(rows) if o == gateway._PLAN_OWNER)
    return scope, rows[(gateway._PLAN_OWNER, scope)][0]


@pytest.mark.parametrize("method,path,body", _SITES)
def test_p6_plan_a_a_caller_whose_only_recipients_are_plan_ones_gets_200_and_the_plan_one(
        topaz, doors, plan_served, method, path, body):
    scope, who = _plan_row()
    for k in [k for k, readers in topaz["rows"].items() if k[0] != gateway._PLAN_OWNER]:
        topaz["rows"][k] = tuple(r for r in topaz["rows"][k] if r != who)  # he reads NO cost/finance scope
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(who)
    with TestClient(gateway.app) as c:
        got = _call(c, method, path, body)
    assert got.status_code == 200, (got.status_code, got.text[:120])
    assert [r["value"] for r in got.json()["recipients"]] == [scope]


@pytest.mark.parametrize("method,path,body", _SITES)
def test_p6_plan_b_zero_readers_across_cost_and_plan_with_plan_rows_present_is_403(
        topaz, doors, plan_served, method, path, body):
    assert _plan_row()  # control: plan rows exist and the profile set is served
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User("mallory@example.com")
    with TestClient(gateway.app) as c:
        got = _call(c, method, path, body)
    assert got.status_code == 403, (got.status_code, got.text[:120])
    assert got.json()["detail"]["error"] == "no_recipient_you_may_export_to"
    assert got.json()["detail"]["refusal"]["grantable_by"]  # read from the grantor map, not typed here


@pytest.mark.parametrize("method,path,body", _SITES)
@pytest.mark.parametrize("form", sorted(FORMS))
@pytest.mark.parametrize("down", [gateway._COST_OWNER, gateway._PLAN_OWNER])
def test_p6_plan_c_one_owner_alone_down_is_503_naming_it(
        topaz, doors, plan_served, down, form, method, path, body):
    _scope, who = _plan_row()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(who)
    with TestClient(gateway.app) as c:
        assert _call(c, method, path, body).status_code == 200  # control: every owner up
        topaz["mode"], topaz["only"] = form, {down}
        got = _call(c, method, path, body)
    assert got.status_code == 503, (down, form, got.status_code, got.text[:120])
    assert got.json()["detail"] == {"reason": "recipient_readers_unavailable", "owner": down}


@pytest.mark.parametrize("method,path,body", _SITES)
@pytest.mark.parametrize("who", ["reader", "stranger"])
def test_p6_a_profile_set_outage_is_503_whether_or_not_the_caller_reads_anything(
        topaz, doors, monkeypatch, who, method, path, body):
    """engine-cost's profile set cannot be had: could-not-check is never a 403, and never an omission."""
    def _down(url):
        raise ConnectionError("engine-cost is down")
    monkeypatch.setattr(gateway, "_cost_profiles_get", _down)
    _scope, reader = next((s, r) for o, s, r in ROWS if o == "cost")
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(
        reader if who == "reader" else "mallory@example.com")
    with TestClient(gateway.app) as c:
        got = _call(c, method, path, body)
    assert got.status_code == 503, (got.status_code, got.text[:120])
    assert got.json()["detail"] == {"reason": "answer_profiles_unavailable"}


# ---- the fin template export door, at the ROUTE (saf's finding 1) ------------------------------
# `doors` reaches `_export_package_from_template` through the function `export_package`; this goes
# through `POST /export/package` itself, so a mutant at the function that swallows the 503 is red here.

@pytest.mark.parametrize("form", sorted(FORMS))
def test_the_fin_template_route_is_503_under_every_failure_form(topaz, doors, form):
    scope, reader = next((s, r) for o, s, r in ROWS if o == "finance")
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(reader)
    with TestClient(gateway.app) as c:
        control = c.post("/export/package", headers=BEARER, json=dict(fpe.GOOD))
        assert control.status_code == 200, (control.status_code, control.text[:160])  # admits its reader
        topaz["mode"] = form
        got = c.post("/export/package", headers=BEARER, json=dict(fpe.GOOD))
    assert got.status_code == 503, (form, got.status_code, got.text[:160])
