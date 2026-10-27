"""The visibility check answers 503 for an OUTAGE of its stores and nothing else.

WHAT IS SEALED. `/resolve_instance` and the enumerate gate (`_gate_enumerated_members`) both run
`_filter_sustainment_candidates`. Their catch is `_VISIBILITY_OUTAGE`, exactly the classes the
stores raise when down (`SubstrateUnavailable`, neo4j's ServiceUnavailable / SessionExpired /
TransientError, `httpx.HTTPError`). Any other exception is a DEFECT and propagates (a 500); it is
never filed as "the lookup failed". Each 500 still fails closed: no candidate list is returned.
  * the tuple is exactly that set, with no member wide enough to catch a defect;
  * neither route has a bare / `Exception` / `BaseException` handler (AST, so a rename reds);
  * the not-connected graph raises an outage class, by the real path;
  * every outage class answers 503 (with the cause chained), every defect class escapes;
  * the 502 catch around `execute_sparql` in `resolve_instance` is `SubstrateUnavailable` only;
  * a control: with nothing raising, both routes answer, so the arms above reach their catch.

This answers lane/74's section 4 ask in
`sessions/2026-10-11-packet-to-gov-the-caller-side-is-pr-48-five-sites-moved-five-left-to-be-refused.md`.
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
