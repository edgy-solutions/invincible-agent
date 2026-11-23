"""GET /askable_measures: the declared measures a caller can ask, served through the same
loader as /menu_blocks. Expectations are read from the loader, never typed.

Run: uv run pytest tests/test_askable_measures_are_served.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_fleet.finance_agent import measure_verbs
from src.iagent import gateway, menu_blocks

_SAMPLE = Path(__file__).resolve().parents[1] / "policy" / "overlays" / "sample" / "measure_verbs"
_MENU_ENV = "MENU_BLOCK_OVERLAY_DIRS"
_MEASURE_ENV = "MEASURE_VERB_OVERLAY_DIRS"
_SEED_ENV = "MEASURE_VERB_POLICY_DIR"


class _User:
    id = "u"
    email = "u@example.invalid"

    def __init__(self, domains):
        self.entitled_domains = list(domains)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for e in (_MENU_ENV, _MEASURE_ENV, _SEED_ENV):
        monkeypatch.delenv(e, raising=False)
    menu_blocks.clear_cache()
    yield
    menu_blocks.clear_cache()


def _rows():
    return measure_verbs.load_measure_verbs(overlay_dirs=[_SAMPLE])


def _use_sample(monkeypatch):
    monkeypatch.setenv(_MEASURE_ENV, str(_SAMPLE))
    menu_blocks.clear_cache()


def _get(domains):
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(domains)
    try:
        with TestClient(gateway.app) as c:
            r = c.get("/askable_measures")
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    return r.json()


def _cells_of(r):
    return {c.upper() for c in r.cells}


# 1
def test_one_entry_per_declared_row_with_or_without_a_menu(monkeypatch):
    rows = _rows()
    assert rows, "positive control"
    assert any(not r.menu for r in rows), "control: a row without a menu block"
    _use_sample(monkeypatch)
    got = menu_blocks.askable()
    assert got.composed is True and got.invalid == []
    assert len(got.measures) == len(rows)
    by_verb = {m["verb"]: m for m in got.measures}
    assert len(by_verb) == len(rows)
    for r in rows:
        assert by_verb["mesh:" + r.verb] == {
            "verb": "mesh:" + r.verb, "name": r.name, "description": r.description,
            "phrasings": list(r.synonyms), "cells": sorted(r.cells)}
    verbs = [m["verb"] for m in got.measures]
    assert verbs == sorted(verbs)


# 2
def test_the_verb_joins_to_the_engine_and_to_the_menu_blocks(monkeypatch):
    from agent_fleet.finance_agent import main as fin
    rows = _rows()
    monkeypatch.setattr(fin, "DECLARED", {r.measure_id: r for r in rows})
    reported = {v["fn"]: v["verb"] for v in fin.list_verbs()["verbs"]}
    _use_sample(monkeypatch)
    got = {m["verb"] for m in menu_blocks.askable().measures}
    assert got == {reported[r.measure_id] for r in rows}
    placed = {b["declared_by"] for b in menu_blocks.compose().blocks}
    assert placed and placed <= got
    assert placed == {reported[r.measure_id] for r in rows if r.menu}


# 3
def test_visible_to_keeps_rows_whose_cells_the_caller_holds(monkeypatch):
    rows = _rows()
    _use_sample(monkeypatch)
    measures = menu_blocks.askable().measures
    cell = sorted(rows[0].cells)[0]
    expected = {"mesh:" + r.verb for r in rows if cell.upper() in _cells_of(r)}
    assert expected
    got = menu_blocks.visible_to(measures, [cell.lower()])
    assert {m["verb"] for m in got} == expected
    assert menu_blocks.visible_to(measures, []) == []
    declared = set().union(*(_cells_of(r) for r in rows))
    stranger = "NOT_A_DECLARED_CELL"
    assert stranger not in declared
    assert menu_blocks.visible_to(measures, [stranger]) == []


# 4  absence assertion with its control
def test_the_route_lists_for_the_holder_and_not_for_the_stranger(monkeypatch):
    rows = _rows()
    _use_sample(monkeypatch)
    cell = sorted(rows[0].cells)[0]
    x_rows = {"mesh:" + r.verb for r in rows if cell.upper() in _cells_of(r)}
    assert x_rows
    a = _get([cell.lower()])
    assert a["composed"] is True
    assert {m["verb"] for m in a["measures"]} == x_rows
    held_other = set().union(*(_cells_of(r) for r in rows)) - {cell.upper()}
    b = _get(sorted(held_other))  # identical but for holding none of X
    assert not ({m["verb"] for m in b["measures"]} & {
        "mesh:" + r.verb for r in rows if _cells_of(r) == {cell.upper()}})
    c = _get([])
    assert c["composed"] is True and c["measures"] == []


# 5
def test_unset_env_is_not_read_and_a_bad_row_never_raises(monkeypatch, tmp_path):
    assert menu_blocks.askable() == menu_blocks.AskableMeasures(False, [], [])
    assert _get(["X"]) == {"composed": False, "measures": [], "invalid": []}
    (tmp_path / "bad.yaml").write_text("measure_id: [unterminated\n", encoding="utf-8")
    monkeypatch.setenv(_MEASURE_ENV, str(tmp_path))
    menu_blocks.clear_cache()
    got = menu_blocks.askable()
    assert got.composed is False and got.measures == []
    assert len(got.invalid) == 1 and got.invalid[0]["source"] == "measure_verbs"
    assert got.invalid[0]["reason"].startswith("unreadable: ")
    body = _get(["X"])
    assert body["composed"] is False and body["measures"] == []
    assert [i["source"] for i in body["invalid"]] == ["measure_verbs"]


# 6
def test_compose_and_askable_share_one_load(monkeypatch):
    calls = []
    real = measure_verbs.load_measure_verbs

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(measure_verbs, "load_measure_verbs", counting)
    _use_sample(monkeypatch)
    assert menu_blocks.compose().composed is True
    assert menu_blocks.askable().composed is True
    assert len(calls) == 1
