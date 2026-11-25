"""`GET /askable_measures` is filtered to the cell an ask would run under, resolved by the ASK's
own rule (`_resolve_ask_cell`), and `askable_pick` is checked under that same cell.

Run: uv run pytest tests/routing/test_the_askable_list_narrows_to_the_active_persona.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402
from iagent import menu_blocks  # noqa: E402
from iagent.auth import User  # noqa: E402
from iagent.authz.topaz_client import EntitlementCell, Entitlements  # noqa: E402

_X, _Y, _Z = "CELL_X", "CELL_Y", "CELL_Z"


def _entry(verb, cell):
    return {
        "verb": verb, "name": verb, "description": "d", "phrasings": [verb], "cells": [cell],
        "shape": None, "unit": None, "example_ask": None, "group_label": None,
        "subject": "http://example.invalid/ont#S",
    }


_VERB_X, _VERB_Y = "mesh:measureInX", "mesh:measureInY"
_VERB_Z = "mesh:measureInZ"
_CALLS: list[int] = []
_CELLS = [EntitlementCell(persona="A", domain=_X), EntitlementCell(persona="B", domain=_Y)]


@pytest.fixture(autouse=True)
def _the_list(monkeypatch):
    _CALLS.clear()

    def _askable():
        _CALLS.append(1)
        return menu_blocks.AskableMeasures(
            True, [_entry(_VERB_X, _X), _entry(_VERB_Y, _Y), _entry(_VERB_Z, _Z)], [])

    monkeypatch.setattr(menu_blocks, "askable", _askable)


def _caller(default=True, cells=None) -> User:
    """Persona A holds X; persona B holds Y; the default cell is (A, X)."""
    cells = _CELLS if cells is None else cells
    return User(
        id="u1", authz_id="alice@example.com", entitlement_source="none",
        entitled_domains=[c.domain for c in cells],
        entitlements=Entitlements(
            cells=list(cells), default=cells[0] if (default and cells) else None),
    )


def _get(params=None, user=None):
    gw.app.dependency_overrides[gw.get_current_user] = (lambda: user) if user else _caller
    try:
        with TestClient(gw.app) as c:
            return c.get("/askable_measures", params=params)
    finally:
        gw.app.dependency_overrides.clear()


@pytest.fixture()
def stream(monkeypatch):
    """`/orchestrate` with the stream stubbed: a refusal is told from a pass by the stream call."""
    calls: list = []

    async def _empty():
        if False:
            yield b""

    def _gen(*a, **k):
        calls.append(1)
        return _empty()

    monkeypatch.setattr(gw, "generate_dagster_stream", _gen)
    return calls


def _post(body=None, user=None):
    gw.app.dependency_overrides[gw.get_current_user] = (lambda: user) if user else _caller
    try:
        with TestClient(gw.app) as c:
            return c.post("/orchestrate", json={"message": "m", "session_id": "s1", **(body or {})})
    finally:
        gw.app.dependency_overrides.clear()


def _verbs(r):
    assert r.status_code == 200, r.text
    return sorted(m["verb"] for m in r.json()["measures"])


def _error(r):
    d = r.json()["detail"]
    return d["error"] if isinstance(d, dict) else d


def _cell(r):
    j = r.json()
    return j["persona"], j["domains"], j["cell_source"]


def test_no_params_is_the_default_cell_exactly_as_an_ask():
    r = _get()
    assert _verbs(r) == [_VERB_X]
    assert _cell(r) == ("A", [_X], "default")


def test_a_picked_cell_lists_that_cell():
    r = _get({"active_persona": "B", "active_domains": [_Y]})
    assert _verbs(r) == [_VERB_Y]
    assert _cell(r) == ("B", [_Y], "picker")


def test_either_param_alone_is_incomplete_as_for_an_ask():
    for params in ({"active_persona": "A"}, {"active_domains": [_X]}):
        r = _get(params)
        assert r.status_code == 400 and _error(r) == "incomplete_override", params


def test_a_domain_not_held_under_the_persona_refuses_with_the_cells():
    r = _get({"active_persona": "A", "active_domains": [_Y]})
    assert r.status_code == 403 and _error(r) == "cell_not_entitled"
    d = r.json()["detail"]
    assert d["requested_missing"] == [_Y]
    assert d["entitled_cells"] == [{"persona": "A", "domain": _X}, {"persona": "B", "domain": _Y}]


def test_no_default_falls_to_the_first_cell_and_all_its_domains():
    cells = [EntitlementCell(persona="B", domain=_Y), EntitlementCell(persona="B", domain=_X)]
    r = _get(user=_caller(default=False, cells=cells))
    assert _cell(r) == ("B", [_Y, _X], "first-cell")
    assert _verbs(r) == sorted([_VERB_X, _VERB_Y])


def test_no_cells_is_none():
    r = _get(user=_caller(default=False, cells=[]))
    assert _cell(r) == (None, [], "none")
    assert _verbs(r) == []


@pytest.mark.parametrize("params,status", [
    ({"active_persona": "A", "active_domains": [_Y]}, 403),
    ({"active_domains": [_X]}, 400),
    ({"active_persona": "A"}, 400),
])
def test_a_refused_request_does_not_read_the_list(params, status):
    assert _get(params).status_code == status
    assert _CALLS == []
    assert _get().status_code == 200
    assert _CALLS == [1]


class _Sentinel(Exception):
    pass


def test_the_list_and_the_ask_share_one_derivation(monkeypatch):
    def _boom(*a, **k):
        raise _Sentinel

    monkeypatch.setattr(gw, "_resolve_ask_cell", _boom)
    gw.app.dependency_overrides[gw.get_current_user] = _caller
    try:
        with TestClient(gw.app, raise_server_exceptions=True) as c:
            with pytest.raises(_Sentinel):
                c.get("/askable_measures")
            with pytest.raises(_Sentinel):
                c.post("/orchestrate", json={"message": "m", "session_id": "s1"})
    finally:
        gw.app.dependency_overrides.clear()


@pytest.mark.parametrize("picked", [False, True])
def test_the_list_and_the_ask_resolve_the_same_cell(monkeypatch, stream, picked):
    seen: list = []
    real = gw._resolve_ask_cell

    def _rec(*a, **k):
        out = real(*a, **k)
        seen.append(out)
        return out

    monkeypatch.setattr(gw, "_resolve_ask_cell", _rec)
    ask = {"active_persona": "B", "active_domains": [_Y]} if picked else {}
    r = _get(ask)
    assert r.status_code == 200
    assert _post(ask).status_code == 200
    assert len(seen) == 2 and seen[0] == seen[1]
    assert _cell(r) == seen[0]


def test_the_pick_is_checked_under_the_cell_the_ask_runs_under(stream):
    pick = {"askable_pick": {"verb": _VERB_Y, "bindings": {}}}
    r = _post(pick)  # no persona: the default cell (A, X) does not list Y's verb
    assert r.status_code == 422
    assert r.json()["detail"] == "askable_pick names a measure that is not on your askable list."
    assert stream == []
    r = _post({**pick, "active_persona": "B", "active_domains": [_Y]})
    assert r.status_code == 200
    assert stream == [1]


_TWO_DOMAIN_A = [
    EntitlementCell(persona="A", domain=_X),
    EntitlementCell(persona="A", domain=_Z),
    EntitlementCell(persona="B", domain=_Y),
]


def test_the_default_cell_lists_its_own_domain_not_the_personas_domains():
    """Persona A holds two domains, so the default cell's domain and the persona's domains differ."""
    r = _get(user=_caller(cells=_TWO_DOMAIN_A))
    assert _verbs(r) == [_VERB_X]
    assert _cell(r) == ("A", [_X], "default")


def test_the_default_cell_asks_under_its_own_domain_not_the_personas_domains(monkeypatch):
    """Persona A holds two domains, so the default cell's domain and the persona's domains differ."""
    seen: list = []

    async def _empty():
        if False:
            yield b""

    def _gen(*a, **k):
        seen.append(k)
        return _empty()

    monkeypatch.setattr(gw, "generate_dagster_stream", _gen)
    assert _post(user=_caller(cells=_TWO_DOMAIN_A)).status_code == 200
    assert len(seen) == 1
    assert seen[0]["user_persona"] == "A"
    assert seen[0]["entitled_domains"] == [_X]
