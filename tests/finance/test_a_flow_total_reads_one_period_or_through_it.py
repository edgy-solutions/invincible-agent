"""A flow total reads one fiscal period, or the program through it, in CALENDAR order, through the REAL route.

A flow row lists `period` and `basis` (both or neither). `basis: period` reads the rows of that
period alone; `basis: cumulative` reads every period of the row's calendar up to and including it.
The cut is by position in the row's declared calendar, never by comparing labels as strings.

Synthetic program B's 4-4-5 calendar (`program_b_445`) is the control for that: its labels P1..P12
are not lexical (sorted as strings P10 falls before P2), so a string cut and a calendar cut read
different sets. The frame is built here, one amount per period, each a distinct power of two, so
that every set of periods has its own sum and a wrong set cannot hide in a coincidence. The
expected totals are computed HERE, with polars, from the same frame; none is copied from the engine.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_a_flow_total_reads_one_period_or_through_it.py
"""
from __future__ import annotations

import copy
import os
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent.entities import fiscal_periods  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    MeshUnavailable, NotEntitled, _clean_env, frame_of, ticketed, token,
)
from tests.finance.test_the_version_is_a_declared_dimension import (  # noqa: E402
    B_COMPARE, B_LEVELS, PLAN, URN_B as URN_BV, b_frame as bv_frame, _b_raw as bv_contract_raw,
)
from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402
    ALLOWED, DENIED, PROGRAM, ROW_URN,
)
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import b_frame  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SAMPLE_ROWS = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
SAMPLE_CAL = REPO / "policy" / "overlays" / "sample" / "fin_calendar"
B_DIR = REPO / "tests" / "fixtures" / "fin_program_b"
FN_B, FN_EV, FN_CMP = "fin_b_flow_wbs_by_period", "fin_flow_acwp_by_period", "fin_flow_b_compare_by_period"
PROG_B = "PRG-B"
URN_B = "urn:li:dataset:(urn:li:dataPlatform:s3,program_b,PROD)"
LABELS = [f"P{n}" for n in range(1, 13)]
SIGN = {"positive": 1, "negative": -1, "zero": 0}
#: one amount per period, each a distinct power of two: every subset of periods has its own sum
AMOUNT = {p: 0.25 * 2 ** i for i, p in enumerate(LABELS)}


# -- the data and the oracle ---------------------------------------------------------------------

def frame(rows_of_p13: int = 0):
    """Program B's frame with acwp = AMOUNT[period] on every row; optionally `rows_of_p13` rows
    moved to a period the calendar does not have."""
    f = b_frame().with_columns(pl.col("period").replace_strict(AMOUNT, return_dtype=pl.Float64).alias("acwp"))
    if rows_of_p13:
        f = f.with_row_index("i").with_columns(
            pl.when(pl.col("i") < rows_of_p13).then(pl.lit("P13")).otherwise(pl.col("period")).alias("period")
        ).drop("i")
    return f


def total_of(f, periods):
    """The sum of acwp over the rows of `periods`, exactly."""
    return sum((Decimal(str(v)) for v in f.filter(pl.col("period").is_in(list(periods)))["acwp"]), Decimal(0))


def root_value(env):
    (root,) = [e for e in env["rows"] if e["source"] is None]
    return SIGN[root["sign"]] * Decimal(root["value_exact"])


# -- the world: rows, contracts and frames in ONE engine ----------------------------------------

class Gate:
    """The client double: a subject not in `granted` is refused; a URN not in `frames` does not exist.
    `asked` lists every read that reached it."""

    def __init__(self, frames):
        self.frames, self.granted, self.asked = frames, {ALLOWED}, []

    def load(self):
        gate = self

        class Client:
            def __init__(self, **kw):
                self.who = kw["originator_email"]

            def get_dataframe_with_ticket(self, urn):
                gate.asked.append((self.who, urn))
                if urn not in gate.frames or self.who not in gate.granted:
                    raise NotEntitled("refused")
                return ticketed(gate.frames[urn].lazy(), urn, len(gate.asked))
        return Client, NotEntitled, MeshUnavailable


def _yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def b_row(**dataset):
    raw = _yaml(B_DIR / "measure_verbs" / f"{FN_B}.yaml")
    raw["inputs"]["dataset"].update(dataset)
    return raw


def ev_row():
    """A test-local copy of the sample's flow row, listing `period` and `basis`, under its own id."""
    raw = _yaml(SAMPLE_ROWS / "fin_flow_acwp.yaml")
    raw["measure_id"], raw["verb"] = FN_EV, "finFlowAcwpByPeriod"
    raw["name"] = "Actual cost flow, one period or through it"
    raw["synonyms"] = ["actual cost flow for a period"]
    raw["inputs"]["params"] = {"program_id": {"required": True}, "period": {"required": True},
                               "basis": {"required": True}}
    return raw


def contracts_raw(**program_b):
    """The contracts a world holds, as dicts: the sample's own, program B's with `program_b` changed."""
    b = _yaml(B_DIR / "contracts" / "program_b.yaml")
    b.update(program_b)
    return {"ev_fixture": _yaml(REPO / "contracts" / "ev_fixture.yaml"), "program_b": b}


def declare(monkeypatch, tmp_path, rows, contracts):
    """Write `rows` ({id: row dict}) and `contracts` ({name: raw dict}) to a fresh overlay and
    contract directory, point the engine at them, and load. Returns the loaded rows."""
    cdir, odir = tmp_path / "contracts", tmp_path / "overlay"
    cdir.mkdir(exist_ok=True)
    odir.mkdir(exist_ok=True)
    for name, raw in contracts.items():
        (cdir / f"{name}.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    for old in odir.glob("*.yaml"):      # a world is its rows alone: a second call in a test starts clean
        old.unlink()
    for fn, row in rows.items():
        (odir / f"{fn}.yaml").write_text(yaml.safe_dump(row, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(cdir))
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(odir))
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", os.pathsep.join([str(SAMPLE_CAL), str(B_DIR / "fin_calendar")]))
    return engine._load_declared()


def serve(monkeypatch, declared, frames):
    gate = Gate(frames)
    monkeypatch.setattr(engine, "DECLARED", declared)
    for fn, row in declared.items():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + row.verb, fn)
    monkeypatch.setattr(engine.asset_inputs, "_load_client", gate.load)
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program in {PROG_B, PROGRAM} and caller_id in {ALLOWED, DENIED})
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    return gate


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Program B's by-period row, program B's plain WBS row, and the sample's row listing the
    same params, in one engine: two calendars."""
    plain = _yaml(B_DIR / "measure_verbs" / "fin_b_flow_wbs.yaml")
    rows = declare(monkeypatch, tmp_path, {FN_B: b_row(), "fin_b_flow_wbs": plain, FN_EV: ev_row()}, contracts_raw())
    gate = serve(monkeypatch, rows, {URN_B: frame(), ROW_URN: frame_of()})
    gate.rows = rows
    return gate


def call_of(client):
    def call(fn, program=PROG_B, **params):
        r = client.post(f"/measure/{fn}", json={"params": {"program_id": program, **params}, "user_email": ALLOWED},
                        headers={"Authorization": f"Bearer {token(ALLOWED)}"})
        return r.status_code, r.json()
    return call


@pytest.fixture
def post(world):
    with TestClient(engine.app) as c:
        yield call_of(c)


# -- 1. the period alone, and through it: the order control --------------------------------------

def test_basis_period_reads_that_periods_rows_alone(post):
    status, env = post(FN_B, period="P10", basis="period")
    assert status == 200, env
    assert root_value(env) == total_of(frame(), ["P10"])
    assert root_value(env) != total_of(frame(), LABELS), "a period total is not the whole program's"


def test_cumulative_through_p10_is_p1_to_p10_and_excludes_p11_and_p12(post):
    through = LABELS[:10]
    lexical = [p for p in LABELS if p <= "P10"]
    assert sorted(lexical) == ["P1", "P10"] and set(lexical) != set(through), "the control must tell the two cuts apart"
    f = frame()
    assert total_of(f, through) != total_of(f, lexical)
    status, env = post(FN_B, period="P10", basis="cumulative")
    assert status == 200, env
    assert root_value(env) == total_of(f, through)
    assert root_value(env) != total_of(f, lexical)                       # not the string cut
    assert root_value(env) == total_of(f, LABELS) - total_of(f, ["P11", "P12"])


def test_cumulative_through_p2_excludes_p10(post):
    f = frame()
    lexical = [p for p in LABELS if p <= "P2"]
    assert "P10" in lexical, "the reverse control: a string cut through P2 takes P10"
    status, env = post(FN_B, period="P2", basis="cumulative")
    assert status == 200, env
    assert root_value(env) == total_of(f, ["P1", "P2"])
    assert root_value(env) != total_of(f, lexical)


def test_p9_and_p1_read_their_own_rows(post):
    f = frame()
    for period, basis, want in (("P1", "period", ["P1"]), ("P9", "period", ["P9"]), ("P9", "cumulative", LABELS[:9])):
        status, env = post(FN_B, period=period, basis=basis)
        assert status == 200, env
        assert root_value(env) == total_of(f, want), (period, basis)


# -- 2. refusals before the read, and over the rows --------------------------------------------

@pytest.mark.parametrize("params", [
    {"period": "P13", "basis": "period"},          # not a period of B's calendar
    {"period": "FY26-01", "basis": "cumulative"},   # a period of ANOTHER calendar
    {"period": "P1", "basis": "running"},           # not a basis
])
def test_a_period_or_basis_outside_the_declaration_refuses_before_the_read(post, world, params):
    status, env = post(FN_B, **params)
    assert status == 422, env
    detail = env["detail"]["not_in_model"]
    assert detail.startswith(("period is not a period of the row's calendar", "basis is not one of"))
    assert not any(label in detail for label in LABELS), "the message names the argument, never the labels"
    assert world.asked == [], "the asset was never read"


def test_a_row_whose_period_is_outside_the_calendar_refuses_period_outside_calendar(monkeypatch, tmp_path):
    rows = declare(monkeypatch, tmp_path, {FN_B: b_row()}, contracts_raw())
    serve(monkeypatch, rows, {URN_B: frame(rows_of_p13=3)})
    with TestClient(engine.app) as c:
        status, env = call_of(c)(FN_B, period="P10", basis="period")
    assert status == 502, env
    assert env["detail"]["error"] == "asset_contract_violation" and env["detail"]["rule"] == "period_outside_calendar"
    assert "P13" not in str(env), "the message names the column, never a value"


def test_a_period_the_asset_holds_no_rows_for_is_not_in_model_naming_it(monkeypatch, tmp_path):
    rows = declare(monkeypatch, tmp_path, {FN_B: b_row()}, contracts_raw())
    serve(monkeypatch, rows, {URN_B: frame().filter(pl.col("period") != "P7")})
    with TestClient(engine.app) as c:
        call = call_of(c)
        status, env = call(FN_B, period="P7", basis="period")
        assert (status, env["detail"]["not_in_model"].endswith("in period P7")) == (422, True), env
        status, env = call(FN_B, period="P1", basis="cumulative")
        assert status == 200, env                       # P7 missing from the data is no reason to refuse P1


def test_a_missing_period_is_asked_for_not_read_as_the_whole_program(post, world):
    status, env = post(FN_B)
    assert status == 422 and set(env["detail"]["needs_slots"]) == {"period", "basis"}, env
    assert world.asked == []


# -- 3. the load-time refusals, each with a control row that loads -------------------------------

def _loads(monkeypatch, tmp_path, rows, contracts):
    return declare(monkeypatch, tmp_path, rows, contracts)


def _without(row, *names):
    row = copy.deepcopy(row)
    for n in names:
        del row["inputs"]["params"][n]
    return row


@pytest.mark.parametrize("drop", ["basis", "period"])
def test_a_flow_row_listing_one_of_period_and_basis_is_refused(monkeypatch, tmp_path, drop):
    assert _loads(monkeypatch, tmp_path, {FN_B: b_row()}, contracts_raw())[FN_B]       # control: both load
    with pytest.raises(ValueError, match=rf"{FN_B}\.yaml.*lists \['(period|basis)'\].*together, or neither"):
        _loads(monkeypatch, tmp_path, {FN_B: _without(b_row(), drop)}, contracts_raw())


def test_period_and_basis_over_a_contract_with_no_period_column_are_refused(monkeypatch, tmp_path):
    no_column = {"period": {"calendar": "program_b_445"}}
    with pytest.raises(ValueError, match=rf"{FN_B}\.yaml.*declares no period column"):
        _loads(monkeypatch, tmp_path, {FN_B: b_row()}, contracts_raw(**no_column))
    # the same contract still serves the row that reads no period
    plain = _yaml(B_DIR / "measure_verbs" / "fin_b_flow_wbs.yaml")
    assert _loads(monkeypatch, tmp_path, {"fin_b_flow_wbs": plain}, contracts_raw(**no_column))["fin_b_flow_wbs"]


def _acwp_not_additive_over_period(contract):
    contract = copy.deepcopy(contract)
    (acwp,) = [c for c in contract["columns"] if c["name"] == "acwp"]
    acwp["additive_over"] = ["work_package"]
    return contract


def test_a_cumulative_sum_of_a_column_not_additive_over_its_periods_is_refused(monkeypatch, tmp_path):
    bad = _acwp_not_additive_over_period(contracts_raw()["program_b"])
    with pytest.raises(ValueError, match=rf"{FN_B}\.yaml.*cumulative read would sum \['acwp'\].*does not declare "
                                         r"additive over its periods"):
        _loads(monkeypatch, tmp_path, {FN_B: b_row()}, contracts_raw(columns=bad["columns"]))
    assert _loads(monkeypatch, tmp_path, {FN_B: b_row()}, contracts_raw())[FN_B]       # control: declared additive


def test_per_path_once_is_exempt_from_the_additive_guard(monkeypatch, tmp_path):
    bad = _acwp_not_additive_over_period(contracts_raw()["program_b"])
    rows = _loads(monkeypatch, tmp_path, {FN_B: b_row(per_path="once")}, contracts_raw(columns=bad["columns"]))
    assert rows[FN_B].per_path == "once"


def test_a_series_row_refuses_period_and_basis_and_says_it_is_a_flow_rows(monkeypatch, tmp_path):
    series = _yaml(SAMPLE_ROWS / "fin_ev_cumulative.yaml")
    assert _loads(monkeypatch, tmp_path, {"fin_ev_cumulative": series}, contracts_raw())
    series = copy.deepcopy(series)
    series["inputs"]["params"] = {**series["inputs"]["params"], "period": {"required": True}, "basis": {"required": True}}
    with pytest.raises(ValueError, match=r"fin_ev_cumulative\.yaml.*series row.*a flow row's only"):
        _loads(monkeypatch, tmp_path, {"fin_ev_cumulative": series}, contracts_raw())


# -- 4. compare composes: the period filter runs before the version split --------------------------

def _compare_world(monkeypatch, tmp_path):
    raw = bv_contract_raw()
    (amount,) = [c for c in raw["columns"] if c["name"] == "amount"]
    amount["additive_over"] = ["control_account", "period"]      # a test-local declaration: the guard needs it
    row = copy.deepcopy(B_COMPARE)
    row["measure_id"], row["verb"], row["name"] = FN_CMP, "xfinflowbcomparebyperiod", FN_CMP
    row["inputs"]["params"] = {p: {"required": True} for p in
                               ["program_id", "version_a", "version_b", "period", "basis"]}
    rows = declare(monkeypatch, tmp_path, {FN_CMP: row}, {"program_b_versions": raw})
    return serve(monkeypatch, rows, {URN_BV: bv_frame()})


def _plan_sums(version, upto, alone):
    """The sum of `version`'s amounts over the plan's rows at period index <= upto (== upto when
    `alone`): the plan lists a path's amounts one per period, P1 first."""
    out = {}
    for path, by_version in PLAN.items():
        amounts = by_version.get(version, [])
        kept = [a for i, a in enumerate(amounts) if (i == upto if alone else i <= upto)]
        if kept:
            out[path] = sum((Decimal(str(a)) for a in kept), Decimal(0))
    return out


@pytest.mark.parametrize("basis, alone", [("period", True), ("cumulative", False)])
def test_a_compare_row_reads_each_side_over_the_same_periods(monkeypatch, tmp_path, basis, alone):
    _compare_world(monkeypatch, tmp_path)
    with TestClient(engine.app) as c:
        status, env = call_of(c)(FN_CMP, version_a="EAC-GOV", version_b="PMB", period="P2", basis=basis)
    assert status == 200, env
    a, b = _plan_sums("EAC-GOV", 1, alone), _plan_sums("PMB", 1, alone)
    sa, sb = sum(a.values(), Decimal(0)), sum(b.values(), Decimal(0))
    assert Decimal(env["compare"]["total_a_exact"]) == sa and Decimal(env["compare"]["total_b_exact"]) == sb
    assert Decimal(env["compare"]["difference_exact"]) == sa - sb
    assert env["compare"]["paths_only_in_a"] == len(a.keys() - b.keys())
    assert env["compare"]["paths_only_in_b"] == len(b.keys() - a.keys())
    assert env["period"] == "P2" and env["basis"] == basis
    # the control: the whole program (every period) is a different pair of totals
    whole_a, whole_b = _plan_sums("EAC-GOV", 99, False), _plan_sums("PMB", 99, False)
    assert (sum(whole_a.values(), Decimal(0)), sum(whole_b.values(), Decimal(0))) != (sa, sb)


# -- 5. the slots -----------------------------------------------------------------------------------

def test_the_period_slot_lists_the_rows_own_calendar_in_calendar_order(world):
    row = world.rows[FN_B]
    labels = [p["label"] for p in _yaml(B_DIR / "fin_calendar" / "program_b_445.yaml")["periods"]]
    slots = {s["name"]: s for s in engine._declared_slots(row)}
    assert slots["period"]["values"] == labels == LABELS
    assert slots["period"]["values"] != list(fiscal_periods()), "not the default calendar's periods"
    assert slots["basis"]["values"] == ["period", "cumulative"]
    registered = [c for c in engine._registration_calls() if c["fn"] == FN_B]
    (call,) = registered
    by_name = {s["name"]: s for s in call["slots"]}
    assert by_name["period"]["values"] == labels and by_name["basis"]["values"] == ["period", "cumulative"]
    assert slots["period"]["required"] is True or "required" in slots["period"]


def test_the_samples_row_lists_the_samples_calendar_not_programs(world):
    ev = world.rows[FN_EV]
    cal = [p["label"] for p in _yaml(SAMPLE_CAL / "us_federal_fy26.yaml")["periods"]]
    slots = {s["name"]: s for s in engine._declared_slots(ev)}
    assert slots["period"]["values"] == cal and "P10" not in cal


def test_a_row_listing_neither_has_neither_slot(world):
    names = {s["name"] for s in engine._declared_slots(world.rows["fin_b_flow_wbs"])}
    assert "period" not in names and "basis" not in names


# -- 6. the answer names its period and its basis ---------------------------------------------------

def test_the_envelope_the_verdict_and_the_provenance_name_the_period_and_basis(post):
    status, env = post(FN_B, period="P10", basis="cumulative")
    assert status == 200, env
    assert (env["period"], env["basis"]) == ("P10", "cumulative")
    assert "period P10, cumulative" in env["verdict"] and "period P10, cumulative" in env["data_provenance"]
    status, alone = post(FN_B, period="P10", basis="period")
    assert (alone["period"], alone["basis"]) == ("P10", "period")
    assert "period P10 alone" in alone["verdict"] and "period P10 alone" in alone["data_provenance"]
    assert alone["artifact_id"] != env["artifact_id"], "a different basis is a different artifact"


def test_a_row_listing_neither_says_nothing_of_a_period(post):
    status, env = post("fin_b_flow_wbs")
    assert status == 200, env
    assert "period" not in env and "basis" not in env
    assert "period P" not in env["verdict"] and "Read:" not in env["data_provenance"]


# -- 7. one engine, two calendars: the sample's US federal row answers too ---------------------------

def test_the_samples_flow_row_reads_one_period_and_through_it(post):
    f = frame_of()
    cal = [p["label"] for p in _yaml(SAMPLE_CAL / "us_federal_fy26.yaml")["periods"]]
    held = [p for p in cal if p in set(f["period"])]
    assert len(held) >= 3
    mid = held[len(held) // 2]

    def total(periods):
        g = f.filter(pl.col("period").is_in(periods))
        return sum((Decimal(str(v)) for v in g["acwp"]), Decimal(0))

    status, env = post(FN_EV, program=PROGRAM, period=mid, basis="period")
    assert status == 200, env
    assert root_value(env) == total([mid])
    status, env = post(FN_EV, program=PROGRAM, period=mid, basis="cumulative")
    assert status == 200, env
    assert root_value(env) == total(held[:held.index(mid) + 1])
    assert root_value(env) != total(held)
    status, env = post(FN_EV, program=PROGRAM, period="P10", basis="period")
    assert status == 422, "program B's label is not a period of the sample's calendar"
