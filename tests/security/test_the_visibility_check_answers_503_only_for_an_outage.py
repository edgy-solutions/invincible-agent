"""The visibility check answers 503 for an OUTAGE of its stores and nothing else.

WHICH SITES. Found by what they call, not by a list: every function in engine O that reaches
`can_view_program`, walked up through whatever calls it or hands it on, until a `try` answers for it
(`_visibility_census`). A new route is covered the day it is written. Only the two sites below and
`/notice_parts` are also driven, because driving one needs its own request.

WHAT IS SEALED. `/resolve_instance` and the enumerate gate (`_gate_enumerated_members`) both run
`_filter_sustainment_candidates`. Their catch is `_VISIBILITY_OUTAGE`, exactly the classes the
stores raise when down (`SubstrateUnavailable`, neo4j's ServiceUnavailable / SessionExpired /
TransientError, `httpx.HTTPError`). Any other exception is a DEFECT and propagates (a 500); it is
never filed as "the lookup failed". Each 500 still fails closed: no candidate list is returned.
  * the tuple is exactly that set, with no member wide enough to catch a defect;
  * neither route has a bare / `Exception` / `BaseException` handler (AST, so a rename reds);
  * every path to the program check ends in a `_VISIBILITY_OUTAGE` arm answering 503, and no other
    arm stands around it;
  * the not-connected graph raises an outage class, by the real path;
  * every outage class answers 503 (with the cause chained), every defect class escapes;
  * the 502 catch around `execute_sparql` in `resolve_instance` is `SubstrateUnavailable` only;
  * a control: with nothing raising, both routes answer, so the arms above reach their catch.

This answers lane/74's section 4 ask in
`sessions/2026-10-11-packet-to-gov-the-caller-side-is-pr-48-five-sites-moved-five-left-to-be-refused.md`,
and section 3 of its 2026-11-08 packet to Lane 1, which is where the fixed list was found wanting.
"""
from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

import httpx  # noqa: E402
import neo4j.exceptions as neo_exc  # noqa: E402
from fastapi import HTTPException  # noqa: E402

MAIN = _ROOT / "agent_fleet" / "ontology_service" / "main.py"
ROUTES = ("resolve_instance", "_gate_enumerated_members")
PROGRAM_CHECK = "can_view_program"
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
_HTTP_VERBS = {"get", "post", "put", "patch", "delete", "api_route"}
_REQ = httpx.Request("POST", "http://t")


@pytest.fixture()
def eo():
    from agent_fleet.ontology_service import main as mod
    return mod


def _outages(eo):
    return {
        "SubstrateUnavailable": eo.SubstrateUnavailable("x"),
        "ServiceUnavailable": neo_exc.ServiceUnavailable("x"),
        "SessionExpired": neo_exc.SessionExpired("x"),
        "TransientError": neo_exc.TransientError("x"),
        "ConnectError": httpx.ConnectError("x"),
        "ReadTimeout": httpx.ReadTimeout("x"),
        "HTTPStatusError": httpx.HTTPStatusError(
            "x", request=_REQ, response=httpx.Response(503, request=_REQ)),
    }


DEFECTS = {
    "TypeError": TypeError("x"), "KeyError": KeyError("x"), "AttributeError": AttributeError("x"),
    "ValueError": ValueError("x"), "RuntimeError": RuntimeError("x"), "NameError": NameError("x"),
}
OUTAGE_NAMES = ["SubstrateUnavailable", "ServiceUnavailable", "SessionExpired", "TransientError",
                "ConnectError", "ReadTimeout", "HTTPStatusError"]


def _raiser(exc):
    async def _f(*a, **kw):
        raise exc
    return _f


def _call_route(eo, monkeypatch, route, exc):
    monkeypatch.setattr(eo, "_filter_sustainment_candidates", _raiser(exc))
    if route == "resolve_instance":
        async def _sparql(*a, **kw):
            return []
        monkeypatch.setattr(eo, "execute_sparql", _sparql)
        return asyncio.run(eo.resolve_instance(eo.ResolveInstanceRequest(
            identifier="PCN-D1", user_email="a@b", entitled_domains=[])))
    return asyncio.run(eo._gate_enumerated_members(
        eo.EnumerateInstancesRequest(class_uri="x"),
        {"members": [{"instance_id": "x"}], "count": 1}))


def _call_notice_parts(eo, monkeypatch, exc):
    def _read(*a, **kw):
        raise exc
    monkeypatch.setattr(eo._notice_parts, "read_notice_parts", _read)
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", object())
    return asyncio.run(eo.notice_parts_route(eo.NoticePartsRequest(
        resolved_instance_id="PCN-D1", user_email="a@b", entitled_domains=[eo._notice_parts.DOMAIN])))


# -- 1. the tuple ------------------------------------------------------------------------------

def test_VISIBILITY_OUTAGE_is_exactly_the_stores_outage_classes(eo):
    from agent_fleet.ontology_service import read_outcome
    assert set(eo._VISIBILITY_OUTAGE) == {
        eo.SubstrateUnavailable, neo_exc.ServiceUnavailable, neo_exc.SessionExpired,
        neo_exc.TransientError, httpx.HTTPError}
    assert eo.SubstrateUnavailable is read_outcome.SubstrateUnavailable
    for member in eo._VISIBILITY_OUTAGE:
        assert member not in (Exception, BaseException)
        for defect in (TypeError, KeyError, AttributeError, ValueError, RuntimeError):
            assert not issubclass(defect, member), f"{member.__name__} would catch {defect.__name__}"


# -- 2. the handlers ---------------------------------------------------------------------------

def _names(node):
    if node is None:
        return []
    if isinstance(node, ast.Tuple):
        return [n for e in node.elts for n in _names(e)]
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    return ["<other>"]


def _raised_status(handler):
    for n in ast.walk(handler):
        if isinstance(n, ast.Call) and _names(n.func) == ["HTTPException"]:
            for kw in n.keywords:
                if kw.arg == "status_code" and isinstance(kw.value, ast.Constant):
                    return kw.value.value
    return None


def test_NO_HANDLER_in_either_route_can_catch_a_defect():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
             and n.name in ROUTES}
    assert set(funcs) == set(ROUTES), f"found {sorted(funcs)}; a rename must red, not skip"
    for name, fn in funcs.items():
        handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
        assert handlers, name
        for h in handlers:
            assert h.type is not None, f"{name}: bare except"
            got = _names(h.type)
            assert "Exception" not in got and "BaseException" not in got, (name, got)
        h503 = [h for h in handlers if _raised_status(h) == 503]
        assert len(h503) == 1, f"{name}: want exactly one 503 handler, found {len(h503)}"
        assert isinstance(h503[0].type, ast.Name) and h503[0].type.id == "_VISIBILITY_OUTAGE", name
    h502 = [h for h in ast.walk(funcs["resolve_instance"])
            if isinstance(h, ast.ExceptHandler) and _raised_status(h) == 502]
    assert len(h502) == 1 and _names(h502[0].type) == ["SubstrateUnavailable"]


# -- 2b. the sites, found by form ---------------------------------------------------------------

def _uses(fn, names):
    """Each use of one of `names` in `fn`, called or handed on: (name, line, the `try`s whose body
    holds it). A nested `def` starts with no `try`, because its body does not run where it is written."""
    found = []

    def walk(node, tries):
        if isinstance(node, ast.Try):
            for b in node.body:
                walk(b, [*tries, node])
            for part in node.handlers + node.orelse + node.finalbody:
                walk(part, tries)
            return
        if isinstance(node, _DEFS) and node is not fn:
            tries = []
        name = (node.id if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                else node.attr if isinstance(node, ast.Attribute) else None)
        if name in names:
            found.append((name, node.lineno, tries))
        for child in ast.iter_child_nodes(node):
            walk(child, tries)
    walk(fn, [])
    return found


def _is_route(fn):
    return any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in _HTTP_VERBS
               for d in fn.decorator_list)


def _visibility_census(source: str):
    """(the functions whose `try` answers for the check, what is wrong). Walks up from the check by
    use. A use inside a `try` is answered there, so every arm around it must be the 503 for
    `_VISIBILITY_OUTAGE`; any other arm is undecided and fails. A use outside one passes the outage
    to whoever uses this function, and a route that does so has let it out as a 500."""
    tree = ast.parse(source)
    defs = {}
    for n in tree.body:
        if isinstance(n, _DEFS):
            defs[n.name] = n
        elif isinstance(n, ast.ClassDef):
            defs.update({m.name: m for m in n.body if isinstance(m, _DEFS)})
    sites, problems, reached, used, frontier = set(), [], set(), set(), {PROGRAM_CHECK}
    while frontier:
        names, frontier = frontier, set()
        for g, fn in defs.items():
            for name, line, tries in _uses(fn, names):
                if name == g:
                    continue
                used.add(name)
                if tries:
                    sites.add(g)
                    for h in (h for t in tries for h in t.handlers):
                        if not (isinstance(h.type, ast.Name) and h.type.id == "_VISIBILITY_OUTAGE"):
                            problems.append(f"{g}:{h.lineno}: `except {_names(h.type)}` stands around the check")
                        elif _raised_status(h) != 503:
                            problems.append(f"{g}:{h.lineno}: the outage arm does not answer 503")
                elif _is_route(fn):
                    problems.append(f"{g}:{line}: the route lets an outage out of `{name}` as a 500")
                elif g not in reached:
                    reached.add(g)
                    frontier.add(g)
    problems += [f"{g}: reaches the check and nothing answers for it" for g in sorted(reached - used)]
    return sites, sorted(set(problems))


def test_EVERY_SITE_that_reaches_the_program_check_answers_an_outage():
    sites, problems = _visibility_census(MAIN.read_text(encoding="utf-8"))
    assert problems == []
    assert sites >= {*ROUTES, "notice_parts_route"}, sites


_SITE_CHECK = """
def can_view_program(p, c):
    return True

def helper():
    return can_view_program(1, 2)
"""
_ANSWERED = """
@app.post("/r")
async def route():
    try:
        return await to_thread(read, can_view_program=helper)
    except _VISIBILITY_OUTAGE as exc:
        raise HTTPException(status_code=503, detail="x") from exc
"""
_SITE_DEFECTS = {
    "a route with no catch, handing the check on": ("""
@app.post("/r")
async def bad():
    return await to_thread(read, can_view_program=helper)
""", "lets an outage out"),
    "a route that calls the check through a helper": ("""
@app.get("/r")
async def bad():
    return helper()
""", "lets an outage out"),
    "a broad arm": ("""
@app.post("/r")
async def bad():
    try:
        return helper()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="x") from exc
""", "stands around"),
    "another arm beside the right one": ("""
@app.post("/r")
async def bad():
    try:
        return helper()
    except _VISIBILITY_OUTAGE as exc:
        raise HTTPException(status_code=503, detail="x") from exc
    except KeyError:
        return []
""", "stands around"),
    "a broad arm outside the right one": ("""
@app.post("/r")
async def bad():
    try:
        try:
            return helper()
        except _VISIBILITY_OUTAGE as exc:
            raise HTTPException(status_code=503, detail="x") from exc
    except Exception:
        return []
""", "stands around"),
    "an outage answered as something else": ("""
@app.post("/r")
async def bad():
    try:
        return helper()
    except _VISIBILITY_OUTAGE as exc:
        raise HTTPException(status_code=403, detail="x") from exc
""", "does not answer 503"),
    "a def written inside the try, which runs outside it": ("""
@app.post("/r")
async def bad():
    try:
        def inner():
            return helper()
        return inner
    except _VISIBILITY_OUTAGE as exc:
        raise HTTPException(status_code=503, detail="x") from exc
""", "lets an outage out"),
    "a use in the else, which no arm covers": ("""
@app.post("/r")
async def bad():
    try:
        x = 1
    except _VISIBILITY_OUTAGE as exc:
        raise HTTPException(status_code=503, detail="x") from exc
    else:
        return helper()
""", "lets an outage out"),
    "a use through a module": ("""
@app.post("/r")
async def bad():
    return mod.helper()
""", "lets an outage out"),
    "a method route": ("""
class S:
    @app.post("/r")
    async def bad(self):
        return helper()
""", "lets an outage out"),
    "a helper nobody answers for": ("""
def nobody():
    return helper()
""", "nothing answers"),
}


@pytest.mark.parametrize("name", sorted(_SITE_DEFECTS))
def test_the_site_census_sees_each_defect(name):
    src, word = _SITE_DEFECTS[name]
    _, problems = _visibility_census(_SITE_CHECK + src + _ANSWERED)
    assert any(word in p for p in problems), problems


def test_the_site_census_passes_an_answered_site():
    sites, problems = _visibility_census(_SITE_CHECK + _ANSWERED)
    assert problems == [] and sites == {"route"}


@pytest.mark.parametrize("name", OUTAGE_NAMES)
def test_NOTICE_PARTS_answers_503_for_an_outage(eo, monkeypatch, name):
    exc = _outages(eo)[name]
    with pytest.raises(HTTPException) as caught:
        _call_notice_parts(eo, monkeypatch, exc)
    assert caught.value.status_code == 503 and caught.value.__cause__ is exc


@pytest.mark.parametrize("name", list(DEFECTS))
def test_NOTICE_PARTS_lets_a_defect_out(eo, monkeypatch, name):
    exc = DEFECTS[name]
    with pytest.raises(type(exc)) as caught:
        _call_notice_parts(eo, monkeypatch, exc)
    assert caught.value is exc


# -- 3. the not-connected graph ----------------------------------------------------------------

def test_the_not_connected_graph_raises_an_outage_class(eo, monkeypatch):
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", None)
    with pytest.raises(eo._VISIBILITY_OUTAGE) as caught:
        asyncio.run(eo._filter_sustainment_candidates(
            [{"instance_id": eo._NOTICE_IRI_PREFIX + "PCN-D1"}],
            user_email="a@b", entitled_domains=[]))
    assert isinstance(caught.value, eo.SubstrateUnavailable)


# -- 4. the routes -----------------------------------------------------------------------------

@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("name", OUTAGE_NAMES)
def test_an_OUTAGE_answers_503(eo, monkeypatch, route, name):
    exc = _outages(eo)[name]
    with pytest.raises(HTTPException) as caught:
        _call_route(eo, monkeypatch, route, exc)
    assert caught.value.status_code == 503
    assert caught.value.__cause__ is exc


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("name", list(DEFECTS))
def test_a_DEFECT_is_not_filed_as_an_outage(eo, monkeypatch, route, name):
    exc = DEFECTS[name]
    with pytest.raises(type(exc)) as caught:
        _call_route(eo, monkeypatch, route, exc)
    assert caught.value is exc
    assert not isinstance(caught.value, HTTPException)


def test_the_502_catch_is_the_substrate_outage_only(eo, monkeypatch):
    req = eo.ResolveInstanceRequest(identifier="PCN-D1", user_email="a@b", entitled_domains=[])
    down = eo.SubstrateUnavailable("jena down")
    monkeypatch.setattr(eo, "execute_sparql", _raiser(down))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(eo.resolve_instance(req))
    assert caught.value.status_code == 502 and caught.value.__cause__ is down
    defect = TypeError("x")
    monkeypatch.setattr(eo, "execute_sparql", _raiser(defect))
    with pytest.raises(TypeError) as caught2:
        asyncio.run(eo.resolve_instance(req))
    assert caught2.value is defect


# -- 5. the control ----------------------------------------------------------------------------

def test_CONTROL_the_route_answers_when_nothing_raises(eo, monkeypatch):
    async def _pass(c, **kw):
        return c

    async def _sparql(*a, **kw):
        return []
    monkeypatch.setattr(eo, "_filter_sustainment_candidates", _pass)
    monkeypatch.setattr(eo, "execute_sparql", _sparql)
    got = asyncio.run(eo.resolve_instance(eo.ResolveInstanceRequest(
        identifier="PCN-D1", user_email="a@b", entitled_domains=[])))
    assert "candidates" in got
    kept, count = asyncio.run(eo._gate_enumerated_members(
        eo.EnumerateInstancesRequest(class_uri="x"),
        {"members": [{"instance_id": "x"}], "count": 1}))
    assert isinstance(kept, list) and isinstance(count, int)
