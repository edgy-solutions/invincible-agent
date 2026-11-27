"""A finance row may declare `render.shape: WATERFALL` over the walk's edges (ruled 2026-11-26).

A WATERFALL row is a flow row (the flow form of `inputs.dataset`) drawn between the walk's start and end,
so the engine refuses at LOAD a row that serves no walk: only `{minus: [a, b]}` and a compare row serve
one. The served envelope is the same as the row's FLOW_DECOMPOSITION twin's, but for `render.shape`.
CONTROL throughout: the twin as FLOW_DECOMPOSITION.

Run: uv run --no-sync pytest -c pyproject.toml --rootdir=. -q -p no:cacheprovider tests/finance/test_a_row_declares_the_waterfall.py
"""
from __future__ import annotations

import copy
import re
from decimal import Decimal

import pytest
import yaml

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import measure_verbs  # noqa: E402
from tests.finance.test_a_dataset_measure_row_loads import (  # noqa: E402
    RAW, STATE_ROW, load as load_one,
)
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import (  # noqa: E402,F401
    ALLOWED, B_DIR, PROG_B, URN_B as URN_B_FLAT, Gate, contract_dir, members, use_dirs,
)
from tests.finance.test_fin_inputs_resolver import _clean_env, token  # noqa: E402,F401
from tests.finance.test_the_version_is_a_declared_dimension import (  # noqa: E402
    B_COMPARE, FN_B, GOV, PMB, PROG_B as PROG_VB, URN_B as URN_VB,
    Gate as VGate, _b_raw, b_frame as vb_frame, load as load_rows,
)
from tests.finance.test_the_walk_has_a_start_and_an_end import b_cv_frame, level1_signed  # noqa: E402

FN_CV = "fin_b_flow_cv"
FN_CV_WF = "fin_b_waterfall_cv"
FN_CMP_WF = "fin_waterfall_b_compare"
NO_WALK = "this row serves no walk"


def waterfall_of(raw, measure_id):
    raw = copy.deepcopy(raw)
    raw["measure_id"] = measure_id
    raw["verb"] = "x" + measure_id.replace("_", "")
    raw["render"]["shape"] = "WATERFALL"
    if "menu" in raw:
        raw["menu"]["archetype"] = "mesh:Waterfall"
    return raw


# -- a minus row ---------------------------------------------------------------------------------

@pytest.fixture
def minus_world(monkeypatch, tmp_path):
    cv = yaml.safe_load((B_DIR / "measure_verbs" / f"{FN_CV}.yaml").read_text(encoding="utf-8"))
    variant = tmp_path / "variant"
    variant.mkdir()
    (variant / f"{FN_CV_WF}.yaml").write_text(
        yaml.safe_dump(waterfall_of(cv, FN_CV_WF), sort_keys=False), encoding="utf-8")
    use_dirs(monkeypatch, contract_dir(tmp_path), [B_DIR / "measure_verbs", variant])
    declared = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", declared)
    for fn, row in declared.items():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + row.verb, fn)
    return declared


@pytest.fixture
def mpost(minus_world, members, monkeypatch):
    g = Gate({URN_B_FLAT: b_cv_frame().lazy()})
    monkeypatch.setattr(engine.asset_inputs, "_load_client", g.load)
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    with TestClient(engine.app) as c:
        def call(fn):
            r = c.post(f"/measure/{fn}", json={"params": {"program_id": PROG_B}, "user_email": ALLOWED},
                       headers={"Authorization": f"Bearer {token(ALLOWED)}"})
            return r.status_code, r.json()
        yield call


def test_a_waterfall_over_a_minus_value_serves_its_shape_a_walk_and_the_twins_rows(mpost, minus_world):
    assert minus_world[FN_CV_WF].archetype == "WATERFALL" and minus_world[FN_CV].archetype == "FLOW_DECOMPOSITION"
    assert minus_world[FN_CV_WF].value_op == "minus"
    status, env = mpost(FN_CV_WF)
    assert status == 200, env
    c_status, twin = mpost(FN_CV)
    assert c_status == 200, twin
    assert env["render"]["shape"] == "WATERFALL"
    assert twin["render"]["shape"] == "FLOW_DECOMPOSITION"          # CONTROL
    assert env["walk"] and env["walk"] == twin["walk"]
    assert env["rows"] == twin["rows"]                               # the module's order, never re-sorted
    assert env["render"]["other_label"] == twin["render"]["other_label"]
    assert env.get("verdict") == twin.get("verdict")
    ticket = re.compile(r"tkt-[0-9]+")                                   # the double counts its calls
    assert ticket.sub("tkt", env["data_provenance"]) == ticket.sub("tkt", twin["data_provenance"])


def test_the_waterfall_balances_exactly_start_plus_the_level_one_edges_is_end(mpost):
    status, env = mpost(FN_CV_WF)
    assert status == 200, env
    walk = env["walk"]
    start, end = Decimal(walk["start"]["value_exact"]), Decimal(walk["end"]["value_exact"])
    assert start != end
    assert start + level1_signed(env) == end


def test_the_waterfall_row_names_the_waterfall_class(minus_world):
    assert measure_verbs.archetype_class("WATERFALL") == "mesh:Waterfall"
    row = minus_world[FN_CV_WF]
    assert row.menu["archetype"] == "mesh:Waterfall" == measure_verbs.archetype_class(row.archetype)


def test_a_waterfall_is_a_computed_shape_and_a_dataset_shape_only():
    assert "WATERFALL" in measure_verbs.COMPUTED_SHAPES
    assert "WATERFALL" in measure_verbs._SHAPES_OF_KIND[measure_verbs.KIND_DATASET]
    assert "WATERFALL" not in measure_verbs._SHAPES_OF_KIND[measure_verbs.KIND_STATE]


# -- a compare row -------------------------------------------------------------------------------

@pytest.fixture
def compare_world(monkeypatch, tmp_path):
    rows = load_rows(tmp_path, monkeypatch,
                     {FN_B: B_COMPARE, FN_CMP_WF: waterfall_of(B_COMPARE, FN_CMP_WF)},
                     contracts={"program_b_versions": _b_raw()})
    monkeypatch.setattr(engine, "DECLARED", rows)
    for fn, r in rows.items():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + r.verb, fn)
    g = VGate({URN_VB: vb_frame()})
    monkeypatch.setattr(engine.asset_inputs, "_load_client", g.load)
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program == PROG_VB and caller_id == ALLOWED)
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    return rows


def test_a_waterfall_over_a_compare_loads_and_serves_a_balanced_walk(compare_world):
    assert compare_world[FN_CMP_WF].archetype == "WATERFALL" and compare_world[FN_CMP_WF].value_op == "compare"
    with TestClient(engine.app) as c:
        def call(fn):
            r = c.post(f"/measure/{fn}", json={"params": {"program_id": PROG_VB, "version_a": GOV,
                                                          "version_b": PMB}, "user_email": ALLOWED},
                       headers={"Authorization": f"Bearer {token(ALLOWED)}"})
            return r.status_code, r.json()
        status, env = call(FN_CMP_WF)
        assert status == 200, env
        c_status, twin = call(FN_B)
        assert c_status == 200, twin
    assert env["render"]["shape"] == "WATERFALL" and twin["render"]["shape"] == "FLOW_DECOMPOSITION"
    assert env["walk"] and env["walk"] == twin["walk"] and env["rows"] == twin["rows"]
    walk = env["walk"]
    assert Decimal(walk["start"]["value_exact"]) + level1_signed(env) == Decimal(walk["end"]["value_exact"])


# -- the load-time refusals ----------------------------------------------------------------------

def test_a_waterfall_with_a_plain_column_value_is_refused_at_load_its_flow_twin_loads(tmp_path):
    (twin,) = load_one(copy.deepcopy(RAW), tmp_path)                 # CONTROL: the same row, FLOW_DECOMPOSITION
    assert twin.archetype == "FLOW_DECOMPOSITION" and twin.value_op == "column"
    raw = copy.deepcopy(RAW)
    raw["render"]["shape"] = "WATERFALL"
    if "menu" in raw:
        raw["menu"]["archetype"] = "mesh:Waterfall"
    (tmp_path / "w").mkdir()
    with pytest.raises(measure_verbs.MeasureVerbError) as err:
        load_one(raw, tmp_path / "w")
    msg = str(err.value)
    assert raw["measure_id"] in msg and "WATERFALL" in msg and NO_WALK in msg
    assert "walk's start and end" in msg and "minus" in msg and "compare" in msg


def test_a_state_row_declaring_a_waterfall_is_refused_by_the_kind_check(tmp_path):
    raw = yaml.safe_load(STATE_ROW.read_text(encoding="utf-8"))
    raw["render"]["shape"] = "WATERFALL"
    with pytest.raises(measure_verbs.MeasureVerbError, match=r"render\.shape 'WATERFALL' does not match a state row"):
        load_one(raw, tmp_path)
