"""`GET /askable_measures` accepts the active persona: the list narrows to the cell the caller
chose, resolved by the SAME derivation the seed uses (`_resolve_active_cell`).

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

_X, _Y = "CELL_X", "CELL_Y"


def _entry(verb, cell):
    return {
        "verb": verb, "name": verb, "description": "d", "phrasings": [verb], "cells": [cell],
        "shape": None, "unit": None, "example_ask": None, "group_label": None,
        "subject": "http://example.invalid/ont#S",
    }


_VERB_X, _VERB_Y = "mesh:measureInX", "mesh:measureInY"
_CALLS: list[int] = []


@pytest.fixture(autouse=True)
def _the_list(monkeypatch):
    _CALLS.clear()

    def _askable():
        _CALLS.append(1)
        return menu_blocks.AskableMeasures(
            True, [_entry(_VERB_X, _X), _entry(_VERB_Y, _Y)], [])

    monkeypatch.setattr(menu_blocks, "askable", _askable)


def _caller() -> User:
    """Persona A holds X; persona B holds Y."""
    return User(
        id="u1", authz_id="alice@example.com", entitlement_source="none",
        entitled_domains=[_X, _Y],
        entitlements=Entitlements(cells=[EntitlementCell(persona="A", domain=_X),
                                         EntitlementCell(persona="B", domain=_Y)]),
    )


def _get(params=None):
    gw.app.dependency_overrides[gw.get_current_user] = _caller
    try:
        with TestClient(gw.app) as c:
            return c.get("/askable_measures", params=params)
    finally:
        gw.app.dependency_overrides.clear()


def _verbs(r):
    assert r.status_code == 200, r.text
    return sorted(m["verb"] for m in r.json()["measures"])


def _error(r):
    d = r.json()["detail"]
    return d["error"] if isinstance(d, dict) else d


def test_no_params_lists_every_held_cell():
    assert _verbs(_get()) == sorted([_VERB_X, _VERB_Y])


def test_persona_alone_narrows_to_its_cell():
    assert _verbs(_get({"active_persona": "A"})) == [_VERB_X]


def test_persona_and_held_domain_narrows():
    assert _verbs(_get({"active_persona": "A", "active_domains": [_X]})) == [_VERB_X]


def test_a_domain_not_held_under_the_persona_refuses():
    r = _get({"active_persona": "A", "active_domains": [_Y]})
    assert r.status_code == 403
    assert _error(r) == "cell_not_entitled"
    d = r.json()["detail"]
    assert d["requested"] == {"persona": "A", "domains": [_Y]}
    assert d["requested_missing"] == [_Y]


def test_one_miss_refuses_the_whole_request():
    r = _get({"active_persona": "A", "active_domains": [_X, _Y]})
    assert r.status_code == 403 and _error(r) == "cell_not_entitled"


def test_domains_without_persona_is_incomplete():
    r = _get({"active_domains": [_X]})
    assert r.status_code == 400 and _error(r) == "incomplete_override"


def test_a_persona_not_held_refuses():
    r = _get({"active_persona": "C"})
    assert r.status_code == 403 and _error(r) == "persona_not_held"


def test_a_refused_request_does_not_read_the_list():
    assert _get({"active_persona": "A", "active_domains": [_Y]}).status_code == 403
    assert _get({"active_domains": [_X]}).status_code == 400
    assert _get({"active_persona": "C"}).status_code == 403
    assert _CALLS == []
    assert _get({"active_persona": "A"}).status_code == 200
    assert _CALLS == [1]


class _Sentinel(Exception):
    pass


def test_the_seed_and_the_list_share_one_derivation(monkeypatch):
    def _boom(*a, **k):
        raise _Sentinel

    monkeypatch.setattr(gw, "_resolve_active_cell", _boom)

    class _Http:
        headers: dict = {}

    import asyncio
    req = gw.CanvasSeedRequest(active_persona="A")
    with pytest.raises(_Sentinel):
        asyncio.run(gw.canvas_seed(req, _Http(), current_user=_caller()))

    gw.app.dependency_overrides[gw.get_current_user] = _caller
    try:
        with TestClient(gw.app, raise_server_exceptions=True) as c:
            with pytest.raises(_Sentinel):
                c.get("/askable_measures", params={"active_persona": "A"})
    finally:
        gw.app.dependency_overrides.clear()
