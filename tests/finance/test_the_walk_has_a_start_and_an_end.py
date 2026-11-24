"""A flow row that subtracts serves the walk's two ends: `walk: {start, end}` (step 5).

For `value: {minus: [a, b]}` the START is column b's program total and the END is column a's, each as a
cent-quantized float and an exact plain decimal string; for `value: {compare: ...}` the start is version
b's total and the end version a's. The invariant: start + the signed sum of the level-1 edges = end, EXACTLY.
A column row has no `walk`. Under `per_path: once` a minus row's (a, b) PAIR must not vary within a path,
else the two totals would be ambiguous, though a - b held.

The expected totals are computed HERE with polars and Decimal from the frames, never through the reader or
the module. Program B's cost variance is a fixture row (tests/fixtures/fin_program_b), never shipped.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_walk_has_a_start_and_an_end.py
"""
from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import (  # noqa: E402,F401
    FN_SAMPLE, PROG_B, URN_B as URN_B_FLAT, b_frame, gate, members, post, rows,
)
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    MeshUnavailable, NotEntitled, _clean_env, token,
)
from tests.finance.test_the_version_is_a_declared_dimension import (  # noqa: E402,F401
    GOV, PMB, PROG_B as PROG_VB, URN_B as URN_VB, world as compare_world,
)
from tests.finance.test_variance_decomposition_eac_row import frame as ev_frame  # noqa: E402
from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402
    ALLOWED, DENIED, PROGRAM, Gate as EvGate,
)

REPO = Path(__file__).resolve().parents[2]
SAMPLE_ROWS = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
FN_B_CV = "fin_b_flow_cv"
FN_CV, FN_EAC = "fin_flow_cost_variance", "fin_flow_eac_variance"
SIGN = {"positive": 1, "negative": -1, "zero": 0}


def level1_signed(env):
    return sum((SIGN[e["sign"]] * Decimal(e["value_exact"]) for e in env["rows"] if e["level"] == 1), Decimal(0))


def assert_walk_holds(env, start_label, end_label):
    walk = env["walk"]
    assert set(walk) == {"start", "end"}
    assert walk["start"]["label"] == start_label and walk["end"]["label"] == end_label
    for end in walk.values():
        assert set(end) == {"label", "value", "value_exact"}
        assert isinstance(end["value_exact"], str) and not ({"E", "e"} & set(end["value_exact"])), end
        assert end["value"] == float(Decimal(end["value_exact"]).quantize(Decimal("0.01")))
    assert Decimal(walk["start"]["value_exact"]) + level1_signed(env) == Decimal(walk["end"]["value_exact"])


# -- 1. program B's cost variance ----------------------------------------------------------------

def b_cv_frame():
    """B's frame with `bcwp` a different figure from `acwp`, at most two decimals (so the cent-quantized
    level-1 edges sum exactly), and a few rows where it is lower, so both signs are drawn."""
    f = b_frame().with_columns((pl.col("acwp") * 1.1).round(2).alias("bcwp"))
    return f.with_columns(pl.when(pl.col("wbs_2") == "B-2.2").then(pl.col("acwp") * 0.9).otherwise(pl.col("bcwp"))
                          .round(2).alias("bcwp"))


def test_b_cost_variance_walks_from_acwp_to_bcwp(post, gate, rows):
    frame = b_cv_frame()
    assert all(Decimal(str(v)).as_tuple().exponent >= -2 for v in frame["bcwp"]), "control: bcwp has <= 2 decimals"
    assert frame["bcwp"].sum() != frame["acwp"].sum()
    gate.frames[URN_B_FLAT] = frame.lazy()
    status, env = post(FN_B_CV)
    assert status == 200, env
    assert rows[FN_B_CV].value_op == "minus" and rows[FN_B_CV].depth == 2
    want_start = sum((Decimal(str(v)) for v in frame["acwp"]), Decimal(0))
    want_end = sum((Decimal(str(v)) for v in frame["bcwp"]), Decimal(0))
    assert want_start != want_end
    walk = env["walk"]
    assert walk["start"]["label"] == "acwp" and walk["end"]["label"] == "bcwp"
    assert Decimal(walk["start"]["value_exact"]) == want_start
    assert Decimal(walk["end"]["value_exact"]) == want_end
    assert walk["start"]["value"] == float(want_start.quantize(Decimal("0.01")))
    assert walk["end"]["value"] == float(want_end.quantize(Decimal("0.01")))
    for end in walk.values():
        assert not ({"E", "e"} & set(end["value_exact"])), end
    assert {"positive", "negative"} <= {e["sign"] for e in env["rows"] if e["level"] == 2}
    assert Decimal(walk["start"]["value_exact"]) + level1_signed(env) == Decimal(walk["end"]["value_exact"])


# -- 2. a compare row ----------------------------------------------------------------------------

@pytest.fixture
def cpost(compare_world):
    with TestClient(engine.app) as c:
        def call(program=PROG_VB, **params):
            r = c.post("/measure/fin_flow_b_compare", json={"params": {"program_id": program, **params},
                                                              "user_email": ALLOWED},
                       headers={"Authorization": f"Bearer {token(ALLOWED)}"})
            return r.status_code, r.json()
        yield call


def test_a_compare_row_walks_from_version_b_to_version_a(cpost, compare_world):
    status, env = cpost(version_a=GOV, version_b=PMB)
    assert status == 200, env
    assert env["walk"]["start"]["label"] == PMB and env["walk"]["end"]["label"] == GOV
    assert env["walk"]["start"]["value_exact"] == env["compare"]["total_b_exact"]
    assert env["walk"]["end"]["value_exact"] == env["compare"]["total_a_exact"]
    assert_walk_holds(env, PMB, GOV)
    status, swapped = cpost(version_a=PMB, version_b=GOV)
    assert swapped["walk"]["start"] == env["walk"]["end"] | {"label": GOV}
    # a total below a millionth would be "3E-8" through str(): the walk serves a plain decimal
    path = ("1", "1.1", "1.1.1", "1.1.1.1", "CA-01")
    tiny = [{"program_id": PROG_VB, "wbs_2": path[0], "wbs_3": path[1], "wbs_4": path[2], "wbs_5": path[3],
             "control_account": path[4], "period": "P1", "version": v, "amount": amount}
            for v, amount in ((GOV, 3e-8), (PMB, 1e-8))]
    compare_world.frames[URN_VB] = pl.DataFrame(tiny, schema_overrides={"amount": pl.Float64})
    assert str(Decimal(str(1e-8))) == "1E-8"            # the control: str() would have served this
    status, env = cpost(version_a=GOV, version_b=PMB)
    assert status == 200, env
    assert env["walk"]["start"] == {"label": PMB, "value": 0.0, "value_exact": "0.00000001"}
    assert env["walk"]["end"] == {"label": GOV, "value": 0.0, "value_exact": "0.00000003"}


# -- 3 to 5. the sample rows over the EV fixture -------------------------------------------------

@pytest.fixture
def ev_world(monkeypatch, tmp_path):
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    for fn in (FN_SAMPLE, FN_CV, FN_EAC):
        shutil.copyfile(SAMPLE_ROWS / f"{fn}.yaml", overlay / f"{fn}.yaml")
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(overlay))
    declared = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", declared)
    for fn, row in declared.items():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + row.verb, fn)
    g = EvGate(ev_frame().lazy())
    monkeypatch.setattr(engine.asset_inputs, "_load_client", g.load)
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program == PROGRAM and caller_id in {ALLOWED, DENIED})
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    return g


@pytest.fixture
def epost(ev_world):
    with TestClient(engine.app) as c:
        def call(fn):
            r = c.post(f"/measure/{fn}", json={"params": {"program_id": PROGRAM}, "user_email": ALLOWED},
                       headers={"Authorization": f"Bearer {token(ALLOWED)}"})
            return r.status_code, r.json()
        yield call


def test_a_column_row_has_no_walk(epost):
    status, env = epost(FN_SAMPLE)
    assert status == 200, env
    assert "walk" not in env
    status, control = epost(FN_CV)
    assert status == 200 and "walk" in control, "control: a minus row in the same session has one"


def test_the_sample_minus_rows_walk_too(epost, ev_world):
    frame = ev_world.frame.collect()
    status, cv = epost(FN_CV)
    assert status == 200, cv
    assert_walk_holds(cv, "acwp", "bcwp")                     # summed over every row: `per_path` is sum
    assert Decimal(cv["walk"]["start"]["value_exact"]) == sum((Decimal(str(v)) for v in frame["acwp"]), Decimal(0))
    assert Decimal(cv["walk"]["end"]["value_exact"]) == sum((Decimal(str(v)) for v in frame["bcwp"]), Decimal(0))
    status, eac = epost(FN_EAC)
    assert status == 200, eac
    assert_walk_holds(eac, "bac", "eac")
    once = frame.unique(subset=["work_package"])              # `once`: each work package counted once
    assert Decimal(eac["walk"]["start"]["value_exact"]) == sum((Decimal(str(v)) for v in once["bac"]), Decimal(0))
    assert Decimal(eac["walk"]["end"]["value_exact"]) == sum((Decimal(str(v)) for v in once["eac"]), Decimal(0))


# -- 5. the once pair rule -----------------------------------------------------------------------

def test_once_refuses_a_pair_that_varies_while_its_difference_holds(epost, ev_world):
    one_path = (pl.col("work_package") == "WP-1101")
    first = one_path & (pl.col("period") == pl.col("period").min())
    base = ev_world.frame.collect()
    # control: (eac, bac) = (5, 3) on every row of the path loads
    ev_world.frame = base.with_columns(
        pl.when(one_path).then(5).otherwise(pl.col("eac")).alias("eac"),
        pl.when(one_path).then(3).otherwise(pl.col("bac")).alias("bac")).lazy()
    status, env = epost(FN_EAC)
    assert status == 200, env
    # (5, 3) and (6, 4): the difference is 2 in both rows, the pair is not the same
    ev_world.frame = base.with_columns(
        pl.when(first).then(6).when(one_path).then(5).otherwise(pl.col("eac")).alias("eac"),
        pl.when(first).then(4).when(one_path).then(3).otherwise(pl.col("bac")).alias("bac")).lazy()
    status, body = epost(FN_EAC)
    assert status == 502 and body["detail"]["error"] == "asset_contract_violation", body
    assert body["detail"]["rule"] == "varies_within_path"
    assert body["detail"]["message"] == "eac, bac vary within one terminal path"
