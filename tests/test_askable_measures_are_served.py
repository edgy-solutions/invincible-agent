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
    persona = None
    # No entitlement cells: the ask's honest-empty branch, so the list keeps `entitled_domains`.
    entitlements = type("_Ent", (), {"cells": [], "default": None})()

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


def _unit_of(r):
    return r.render.get("unit") if isinstance(r.render, dict) else None


def _cells_of(r):
    return {c.upper() for c in r.cells}


def _builtins():
    return measure_verbs.load_askable_builtins()


def _declared_only(measures):
    """The served entries that are declared rows, not built-ins."""
    b = {e["verb"] for e in _builtins()}
    return [m for m in measures if m["verb"] not in b]


# 1
def test_one_entry_per_declared_row_with_or_without_a_menu(monkeypatch):
    rows = _rows()
    assert rows, "positive control"
    assert any(not r.menu for r in rows), "control: a row without a menu block"
    _use_sample(monkeypatch)
    got = menu_blocks.askable()
    assert got.composed is True and got.invalid == []
    declared = _declared_only(got.measures)
    assert len(declared) == len(rows)
    by_verb = {m["verb"]: m for m in declared}
    assert len(by_verb) == len(rows)
    for r in rows:
        assert by_verb["mesh:" + r.verb] == {
            "verb": "mesh:" + r.verb, "name": r.name, "description": r.description,
            "phrasings": list(r.synonyms), "cells": sorted(r.cells),
            "shape": r.archetype, "unit": _unit_of(r),
            "example_ask": r.example_ask or None, "group_label": r.group_label or None,
            "subject": measure_verbs.declared_subject()}
    verbs = [m["verb"] for m in got.measures]
    assert verbs == sorted(verbs)


# 2
def test_the_verb_joins_to_the_engine_and_to_the_menu_blocks(monkeypatch):
    from agent_fleet.finance_agent import main as fin
    rows = _rows()
    monkeypatch.setattr(fin, "DECLARED", {r.measure_id: r for r in rows})
    reported = {v["fn"]: v["verb"] for v in fin.list_verbs()["verbs"]}
    _use_sample(monkeypatch)
    served = menu_blocks.askable().measures
    got = {m["verb"] for m in _declared_only(served)}
    assert got == {reported[r.measure_id] for r in rows}
    # every built-in verb served is a verb the engine registers
    builtin_served = {m["verb"] for m in served} - got
    assert builtin_served, "control: built-ins are served"
    assert builtin_served <= {v["verb"] for v in fin.VERBS}
    placed = {b["declared_by"] for b in menu_blocks.compose().blocks}
    assert placed and placed <= got
    assert placed == {reported[r.measure_id] for r in rows if r.menu}


# 3
def test_visible_to_keeps_rows_whose_cells_the_caller_holds(monkeypatch):
    rows = _rows()
    _use_sample(monkeypatch)
    measures = _declared_only(menu_blocks.askable().measures)
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
    assert {m["verb"] for m in _declared_only(a["measures"])} == x_rows
    held_other = set().union(*(_cells_of(r) for r in rows)) - {cell.upper()}
    b = _get(sorted(held_other))  # identical but for holding none of X
    assert not ({m["verb"] for m in b["measures"]} & {
        "mesh:" + r.verb for r in rows if _cells_of(r) == {cell.upper()}})
    c = _get(["NOT_A_DECLARED_CELL"])
    assert c["composed"] is True and c["measures"] == []


# 5  built-ins list whatever the overlay env
def test_unset_env_lists_the_builtins_and_reads_no_declared_row(monkeypatch):
    entries = _builtins()
    assert entries, "control: the engine has built-ins to list"
    got = menu_blocks.askable()
    assert got.composed is True and got.invalid == []
    assert [m["verb"] for m in got.measures] == sorted(e["verb"] for e in entries)
    e = next(x for x in entries if x["cells"])
    holder = _get([e["cells"][0].lower()])
    assert holder["composed"] is True and holder["invalid"] == []
    assert e["verb"] in {m["verb"] for m in holder["measures"]}
    stranger = "NOT_A_DECLARED_CELL"
    assert all(stranger not in x["cells"] for x in entries)
    body = _get([stranger])
    assert body["composed"] is True and body["measures"] == []


def test_a_bad_declared_row_never_raises(monkeypatch, tmp_path):
    (tmp_path / "bad.yaml").write_text("measure_id: [unterminated\n", encoding="utf-8")
    monkeypatch.setenv(_MEASURE_ENV, str(tmp_path))
    menu_blocks.clear_cache()
    try:
        entries = list(measure_verbs.load_askable_builtins())
        builtins_raise = False
    except Exception:
        entries, builtins_raise = [], True
    got = menu_blocks.askable()
    sources = [i["source"] for i in got.invalid]
    assert "measure_verbs" in sources
    assert all(i["reason"].startswith("unreadable: ") for i in got.invalid)
    # OBSERVED BRANCH: the built-in loader RAISES under this bad overlay, because its listing
    # rows come from the same composition; so measure_builtins is named and nothing was read.
    # (If this ever flips, the else branch asserts the built-ins are served.)
    if builtins_raise:
        assert sources == ["measure_verbs", "measure_builtins"]
        assert got.composed is False and got.measures == []
    else:
        assert sources == ["measure_verbs"]
        assert got.composed is True
        assert [m["verb"] for m in got.measures] == sorted(e["verb"] for e in entries)
    body = _get(["X"])
    assert body["composed"] is got.composed
    assert [i["source"] for i in body["invalid"]] == sources


def test_nothing_read_is_not_composed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(measure_verbs, "load_askable_builtins", boom)
    got = menu_blocks.askable()
    assert got.composed is False and got.measures == []
    assert got.invalid == [{"source": "measure_builtins", "reason": "unreadable: RuntimeError"}]


def test_the_builtins_cache_follows_the_env_between_two_calls(monkeypatch):
    def fake(*a, **k):
        import os
        return [{"verb": "mesh:x", "name": "name-" + os.getenv(_SEED_ENV, ""),
                 "description": "d", "phrasings": [], "cells": ["X"]}]

    monkeypatch.setattr(measure_verbs, "load_askable_builtins", fake)
    def named():
        return [m["name"] for m in menu_blocks.askable().measures if m["verb"] == "mesh:x"]

    _use_sample(monkeypatch)
    monkeypatch.setenv(_SEED_ENV, "one")
    assert named() == ["name-one"]
    monkeypatch.setenv(_SEED_ENV, "two")  # no clear_cache(): the key must follow the env
    assert named() == ["name-two"]


def test_visible_to_strips_a_padded_declared_cell():
    entry = {"verb": "mesh:x", "cells": [" x "]}
    assert menu_blocks.visible_to([entry], ["X"]) == [entry]


# 6
def test_compose_and_askable_share_one_load(monkeypatch):
    calls, bcalls = [], []
    real = measure_verbs.load_measure_verbs
    breal = measure_verbs.load_askable_builtins

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    def bcounting(*a, **k):
        bcalls.append(1)
        return breal(*a, **k)

    monkeypatch.setattr(measure_verbs, "load_measure_verbs", counting)
    monkeypatch.setattr(measure_verbs, "load_askable_builtins", bcounting)
    _use_sample(monkeypatch)
    assert menu_blocks.compose().composed is True
    assert menu_blocks.askable().composed is True
    assert menu_blocks.askable().composed is True
    assert len(calls) == 1
    assert len(bcalls) == 1


# 7  shape and unit come from the row
def test_shape_and_unit_are_served_from_the_row(monkeypatch):
    rows = _rows()
    assert any(_unit_of(r) for r in rows), "control: a row with a unit"
    assert any(_unit_of(r) is None for r in rows), "control: a row without a unit"
    _use_sample(monkeypatch)
    by_verb = {m["verb"]: m for m in menu_blocks.askable().measures}
    for r in rows:
        m = by_verb["mesh:" + r.verb]
        assert m["shape"] == r.archetype
        assert m["unit"] == _unit_of(r)
    domains = sorted(set().union(*(_cells_of(r) for r in rows)))
    body = _get(domains)
    served = {m["verb"]: m for m in body["measures"]}
    assert served
    for r in rows:
        if "mesh:" + r.verb in served:
            assert served["mesh:" + r.verb]["shape"] == r.archetype
            assert served["mesh:" + r.verb]["unit"] == _unit_of(r)


# 8a  built-ins are listed, read from the engine's own loader
def test_builtins_are_listed_as_their_engine_declares(monkeypatch):
    entries = _builtins()
    assert entries, "positive control"
    assert any(e.get("unit") for e in entries), "control: a built-in with a unit"
    assert any(not e.get("unit") for e in entries), "control: a built-in without a unit"
    _use_sample(monkeypatch)
    got = menu_blocks.askable()
    by_verb = {m["verb"]: m for m in got.measures}
    for e in entries:
        m = by_verb[e["verb"]]
        assert m["name"] == e["name"] and m["description"] == e["description"]
        assert m["phrasings"] == e["phrasings"] and m["cells"] == e["cells"]
        assert m["unit"] == e.get("unit")
        assert m["shape"] is None
        assert m["example_ask"] == e.get("example_ask")
        assert m["group_label"] == e.get("group_label")
    verbs = [m["verb"] for m in got.measures]
    assert verbs == sorted(verbs)


# 8b  declared example_ask / group_label
def test_declared_example_ask_and_group_label_are_served(monkeypatch, tmp_path):
    import shutil
    ov = tmp_path / "ov"
    shutil.copytree(_SAMPLE, ov)
    target = _rows()[0]
    f = ov / (target.measure_id + ".yaml")
    f.write_text(f.read_text(encoding="utf-8").rstrip("\n")
                 + "\nexample_ask: an example question\ngroup_label: a group label\n",
                 encoding="utf-8")
    rows = measure_verbs.load_measure_verbs(overlay_dirs=[ov])
    by_id = {r.measure_id: r for r in rows}
    assert by_id[target.measure_id].example_ask and by_id[target.measure_id].group_label
    assert any(not r.example_ask and not r.group_label for r in rows), "control"
    monkeypatch.setenv(_MEASURE_ENV, str(ov))
    menu_blocks.clear_cache()
    served = {m["verb"]: m for m in menu_blocks.askable().measures}
    for r in rows:
        m = served["mesh:" + r.verb]
        assert m["example_ask"] == (r.example_ask or None)
        assert m["group_label"] == (r.group_label or None)
    t = served["mesh:" + by_id[target.measure_id].verb]
    assert t["example_ask"] == "an example question" and t["group_label"] == "a group label"


# 8c  a built-in load failure
def test_a_builtin_load_failure_keeps_the_declared_entries(monkeypatch):
    rows = _rows()

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(measure_verbs, "load_askable_builtins", boom)
    _use_sample(monkeypatch)
    got = menu_blocks.askable()
    assert got.composed is True
    assert {m["verb"] for m in got.measures} == {"mesh:" + r.verb for r in rows}
    assert got.invalid == [{"source": "measure_builtins", "reason": "unreadable: RuntimeError"}]


# 8d  the same verb on both sides
def test_a_verb_both_declared_and_builtin_is_left_out_and_named_twice(monkeypatch):
    rows = _rows()
    real = measure_verbs.load_askable_builtins
    real_entries = real()
    assert real_entries, "control: a real built-in beside the clash"
    clash = "mesh:" + rows[0].verb

    def with_clash(*a, **k):
        return list(real(*a, **k)) + [{**real_entries[0], "verb": clash}]

    monkeypatch.setattr(measure_verbs, "load_askable_builtins", with_clash)
    _use_sample(monkeypatch)
    got = menu_blocks.askable()
    verbs = {m["verb"] for m in got.measures}
    assert clash not in verbs
    assert {"mesh:" + r.verb for r in rows[1:]} <= verbs
    assert {e["verb"] for e in real_entries} <= verbs
    assert sorted(i["source"] for i in got.invalid) == ["measure_builtins", "measure_verbs"]
    assert all(clash in i["reason"] and i["reason"].startswith("ambiguous: ") for i in got.invalid)


# 8e  through the route
def test_the_route_lists_a_builtin_for_its_cell_holder_not_the_stranger(monkeypatch):
    entries = _builtins()
    e = next(x for x in entries if x["cells"])
    _use_sample(monkeypatch)
    holder = _get([e["cells"][0].lower()])
    served = {m["verb"]: m for m in holder["measures"]}
    assert e["verb"] in served
    assert served[e["verb"]]["shape"] is None and served[e["verb"]]["unit"] == e.get("unit")
    stranger = "NOT_A_DECLARED_CELL"
    assert all(stranger not in x["cells"] for x in entries)
    assert e["verb"] not in {m["verb"] for m in _get([stranger])["measures"]}


# 8  nothing finance-specific in the served contract
_FIN = ("financ", "fin_", "finance_agent")


def _names_finance(text):
    low = text.lower()
    return any(w in low for w in _FIN)


def test_the_served_contract_names_nothing_finance_specific():
    import yaml
    assert _names_finance("the finance engine"), "control: the detector can fire"
    spec = gateway.app.openapi()
    desc = spec["paths"]["/askable_measures"]["get"].get("description", "")
    assert desc, "control: the route has a description"
    assert not _names_finance(desc), desc
    schemas = spec["components"]["schemas"]
    for name in ("AskableMeasure", "AskableMeasuresResponse"):
        assert name in schemas
        assert not _names_finance(repr(schemas[name])), name
    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load(
        (root / "docs" / "architecture" / "endpoint_gating_manifest.yaml").read_text(encoding="utf-8"))

    def walk(x):
        if isinstance(x, dict):
            if x.get("path") == "/askable_measures":
                yield x
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, list):
            for v in x:
                yield from walk(v)

    found = list(walk(manifest))
    assert len(found) == 1
    assert not _names_finance(repr(found[0]))
