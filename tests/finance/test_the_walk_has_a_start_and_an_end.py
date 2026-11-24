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

import copy
import os
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

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
    B_COMPARE, GOV, PMB, PROG_B as PROG_VB, URN_B as URN_VB, load as load_rows, world as compare_world,
)
from tests.finance.test_variance_decomposition_eac_row import frame as ev_frame  # noqa: E402
from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402
    ALLOWED, DENIED, PROGRAM, Gate as EvGate,
)

REPO = Path(__file__).resolve().parents[2]
SAMPLE_ROWS = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
FN_B_CV = "fin_b_flow_cv"
EV_URN = "urn:li:dataset:(urn:li:dataPlatform:s3,ev_fixture,PROD)"
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


def test_b_cost_variance_walks_from_actual_cost_to_earned_value(post, gate, rows):
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
    assert walk["start"]["label"] == "Actual cost" and walk["end"]["label"] == "Earned value"
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


# -- 6. render.walk_labels -----------------------------------------------------------------------

def test_a_declared_walk_label_replaces_the_column_name_and_its_absence_keeps_it(post, gate, rows, tmp_path,
                                                                                  monkeypatch):
    # one session: program B's cv row (declared labels) and the sample cv row (none), over their own assets
    sample = tmp_path / "sample_cv"
    sample.mkdir()
    shutil.copyfile(SAMPLE_ROWS / f"{FN_CV}.yaml", sample / f"{FN_CV}.yaml")
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", os.pathsep.join(
        [os.environ["MEASURE_VERB_OVERLAY_DIRS"], str(sample)]))
    declared = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", declared)
    for fn, row in declared.items():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + row.verb, fn)
    gate.frames[URN_B_FLAT] = b_cv_frame().lazy()
    gate.frames[EV_URN] = ev_frame().lazy()
    status, b_env = post(FN_B_CV)
    assert status == 200, b_env
    status, cv = post(FN_CV, program=PROGRAM)
    assert status == 200, cv
    assert declared[FN_B_CV].render["walk_labels"] == {"start": "Actual cost", "end": "Earned value"}
    assert "walk_labels" not in declared[FN_CV].render
    assert (b_env["walk"]["start"]["label"], b_env["walk"]["end"]["label"]) == ("Actual cost", "Earned value")
    assert (cv["walk"]["start"]["label"], cv["walk"]["end"]["label"]) == ("acwp", "bcwp")
    # the same structure either way, and each walk holds
    assert {k: set(v) for k, v in b_env["walk"].items()} == {k: set(v) for k, v in cv["walk"].items()}
    assert_walk_holds(b_env, "Actual cost", "Earned value")
    assert_walk_holds(cv, "acwp", "bcwp")


LABELS = {"start": "Start label", "end": "End label"}


def _declared_with(tmp_path, monkeypatch, name, edit):
    raw = yaml.safe_load((SAMPLE_ROWS / f"{name}.yaml").read_text(encoding="utf-8"))
    edit(raw)
    overlay = tmp_path / "wl"
    overlay.mkdir(exist_ok=True)
    (overlay / f"{name}.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(overlay))
    return engine._load_declared()


def test_the_sample_minus_row_loads_with_labels(tmp_path, monkeypatch):
    got = _declared_with(tmp_path, monkeypatch, FN_CV, lambda r: r["render"].update(walk_labels=dict(LABELS)))
    assert got[FN_CV].render["walk_labels"] == LABELS


@pytest.mark.parametrize("which, match", [
    ("column", r"walk_labels.*not \{minus.*column row serves no walk"),
    ("compare", r"walk_labels.*not \{minus.*compare row's ends are the two versions the caller names"),
])
def test_walk_labels_are_refused_where_the_row_does_not_subtract(which, match, tmp_path, monkeypatch):
    if which == "column":
        with pytest.raises(ValueError, match=match):
            _declared_with(tmp_path, monkeypatch, FN_SAMPLE, lambda r: r["render"].update(walk_labels=dict(LABELS)))
    else:
        row = copy.deepcopy(B_COMPARE)
        row["render"]["walk_labels"] = dict(LABELS)
        with pytest.raises(ValueError, match=match):
            load_rows(tmp_path, monkeypatch, {"fin_flow_b_compare": row})


BAD = [
    ("end missing", {"start": "S"}, r"exactly start and end"),
    ("extra key", {"start": "S", "end": "E", "middle": "M"}, r"exactly start and end"),
    ("empty start", {"start": "", "end": "E"}, r"start must be a non-empty string"),
    ("blank start", {"start": "   ", "end": "E"}, r"start must be a non-empty string"),
    ("int start", {"start": 3, "end": "E"}, r"start must be a non-empty string"),
    ("a list", ["S", "E"], r"must be a mapping"),
]


@pytest.mark.parametrize("labels, match", [b[1:] for b in BAD], ids=[b[0] for b in BAD])
def test_bad_walk_labels_are_refused_at_load(labels, match, tmp_path, monkeypatch):
    with pytest.raises(ValueError, match=match):
        _declared_with(tmp_path, monkeypatch, FN_CV, lambda r: r["render"].update(walk_labels=copy.deepcopy(labels)))


def test_the_folder_check_names_a_row_with_bad_walk_labels(tmp_path, monkeypatch):
    script = REPO / "scripts" / "check_measure_verbs.py"
    b_dir = REPO / "tests" / "fixtures" / "fin_program_b"
    cdir = tmp_path / "contracts"
    cdir.mkdir()
    shutil.copyfile(REPO / "contracts" / "ev_fixture.yaml", cdir / "ev_fixture.yaml")
    shutil.copyfile(b_dir / "contracts" / "program_b.yaml", cdir / "program_b.yaml")
    env = dict(os.environ, DATASET_CONTRACT_DIR=str(cdir), FIN_CALENDAR_OVERLAY_DIRS=os.pathsep.join(
        [str(REPO / "policy" / "overlays" / "sample" / "fin_calendar"), str(b_dir / "fin_calendar")]))
    env.pop("MEASURE_VERB_OVERLAY_DIRS", None)
    folder = tmp_path / "folder"
    folder.mkdir()
    raw = yaml.safe_load((b_dir / "measure_verbs" / "fin_b_flow_cv.yaml").read_text(encoding="utf-8"))
    run = lambda: subprocess.run([sys.executable, str(script), str(folder)], env=env, cwd=REPO,  # noqa: E731
                                 capture_output=True, text=True, timeout=300)
    (folder / "fin_b_flow_cv.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    p = run()
    assert p.returncode == 0, p.stdout + p.stderr         # control: the declared labels load
    raw["render"]["walk_labels"] = {"start": "Actual cost"}
    (folder / "fin_b_flow_cv.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    p = run()
    assert p.returncode == 1, p.stdout + p.stderr
    assert "fin_b_flow_cv.yaml" in p.stdout and "walk_labels" in p.stdout, p.stdout
