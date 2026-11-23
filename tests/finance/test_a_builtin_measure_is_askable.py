"""A built-in finance measure has a row, so it is in the askable list (architect ruling 2026-11-23).

The seven built-in verbs are code (`VERBS`); the seed layer `policy/measure_verbs/` carries one row
each with a `name` and `description`, and `load_askable_builtins` returns them in the askable-list
shape. Phrasings are the routing synonyms and cells the engine's own `DOMAINS`, both read from the
engine; a row cannot carry `cells` or `synonyms`, or list itself without `source`.

Run: .venv/Scripts/python -m pytest tests/finance/test_a_builtin_measure_is_askable.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import measure_verbs, measures  # noqa: E402

SEED_DIR = REPO / "policy" / "measure_verbs"
SAMPLE = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
SANDBOX = REPO / "policy" / "overlays" / "sandbox" / "measure_verbs"
BUILTINS = (measures.OUTPUT_URI, [v["verb"].split(":", 1)[-1] for v in engine.VERBS])
FUNDING = {"measure_id": "fin_funding_status", "source": "seed",
           "reason": "contract carries no funding lines yet", "ratified_by": "owner"}
LISTED = {"name": "A name", "description": "A description."}


def _dir(tmp_path, rows, name="ov"):
    d = tmp_path / name
    d.mkdir()
    for i, raw in enumerate(rows):
        (d / f"row{i}.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return d


def _askable(overlays=(), seed_dir=SEED_DIR):
    return measure_verbs.load_askable_builtins(policy_dir=seed_dir, overlay_dirs=list(overlays),
                                               builtins=BUILTINS)


def _sources(overlays=(), seed_dir=SEED_DIR):
    return measure_verbs.load_measure_sources(policy_dir=seed_dir, overlay_dirs=list(overlays),
                                              builtins=BUILTINS)


def _refused(tmp_path, raw, *fragments):
    d = _dir(tmp_path, [raw])
    with pytest.raises(measure_verbs.MeasureVerbError) as ei:
        _sources([d], seed_dir=tmp_path / "no-seed")
    msg = str(ei.value)
    assert "row0.yaml" in msg, f"the refusal does not name the file: {msg}"
    for f in fragments:
        assert f in msg, f"expected {f!r} in: {msg}"


# 1 ── the real seed layer lists every built-in

def test_the_seed_layer_lists_exactly_the_built_ins():
    got = _askable()
    assert [e["verb"] for e in got] == sorted(v["verb"] for v in engine.VERBS)
    by_verb = {v["verb"]: v for v in engine.VERBS}
    for e in got:
        v = by_verb[e["verb"]]
        assert set(e) == {"verb", "name", "description", "phrasings", "cells"}
        assert e["phrasings"] == list(v["synonyms"]) and e["phrasings"]
        assert e["cells"] == sorted(engine.DOMAINS)
        assert e["name"].strip() and e["description"].strip()


# 2 ── the join with what the engine registers

def test_every_listed_verb_is_one_the_engine_registers():
    with TestClient(engine.app) as c:
        registered = {v["verb"] for v in c.get("/verbs").json()["verbs"]}
    listed = {e["verb"] for e in _askable()}
    assert listed and listed <= registered


# 3 ── the rows do not move where a measure reads

@pytest.mark.parametrize("overlays", [[], [SAMPLE, SANDBOX]], ids=["seed", "seed+sample+sandbox"])
def test_sources_are_unchanged_by_the_listing(overlays):
    rows = {r.measure_id: r for r in _sources(overlays)}
    f = rows["fin_funding_status"]
    assert (f.source, f.source_reason, f.ratified_by) == (
        "seed", FUNDING["reason"], FUNDING["ratified_by"])
    assert {k: r.source for k, r in rows.items() if k != "fin_funding_status"} == {
        v["fn"]: "asset" for v in engine.VERBS if v["fn"] != "fin_funding_status"}


# 4 ── refusals at load, each naming the file

def test_name_without_description_is_refused(tmp_path):
    _refused(tmp_path, {"measure_id": "fin_burn_rate", "source": "asset", "name": "N"},
             "together or neither", "description")


def test_description_without_name_is_refused(tmp_path):
    _refused(tmp_path, {"measure_id": "fin_burn_rate", "source": "asset", "description": "D"},
             "together or neither", "name")


def test_an_empty_name_is_refused(tmp_path):
    _refused(tmp_path, {"measure_id": "fin_burn_rate", "source": "asset", **LISTED, "name": "  "},
             "`name`", "non-empty")


@pytest.mark.parametrize("key,value", [("cells", ["PROGRAM_FINANCE"]), ("synonyms", ["runway"])])
def test_cells_and_synonyms_stay_refused_on_a_built_in_row(tmp_path, key, value):
    _refused(tmp_path, {"measure_id": "fin_burn_rate", "source": "asset", **LISTED, key: value},
             "built-in finance verb", key)


def test_a_listing_row_without_a_source_is_refused(tmp_path):
    _refused(tmp_path, {"measure_id": "fin_funding_status", **LISTED}, "source")


# 5 ── a source-only row is not listed

def test_a_source_only_row_is_a_source_and_not_listed(tmp_path):
    d = _dir(tmp_path, [FUNDING])
    no_seed = tmp_path / "no-seed"
    assert [r.measure_id for r in _sources([d], seed_dir=no_seed)] == ["fin_funding_status"]
    assert _askable([d], seed_dir=no_seed) == []


def test_an_overlay_listing_replaces_the_seed_listing_whole(tmp_path):
    d = _dir(tmp_path, [{"measure_id": "fin_burn_rate", "source": "asset", **LISTED}])
    (e,) = [e for e in _askable([d]) if e["verb"] == "mesh:finBurnRate"]
    assert (e["name"], e["description"]) == (LISTED["name"], LISTED["description"])


# 6 ── a declared row is not affected

def test_declared_rows_are_the_overlay_rows_whatever_the_seed_lists():
    with_seed = measure_verbs.load_measure_verbs(policy_dir=SEED_DIR, overlay_dirs=[SAMPLE],
                                                 builtins=BUILTINS)
    without = measure_verbs.load_measure_verbs(policy_dir=SEED_DIR.parent / "no-such-seed",
                                               overlay_dirs=[SAMPLE], builtins=BUILTINS)
    assert with_seed and {r.measure_id for r in with_seed} == {r.measure_id for r in without}
    assert {r.measure_id for r in with_seed} == {
        yaml.safe_load(p.read_text(encoding="utf-8"))["measure_id"] for p in SAMPLE.glob("*.yaml")}
