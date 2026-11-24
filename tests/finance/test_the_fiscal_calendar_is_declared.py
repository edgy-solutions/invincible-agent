"""The fiscal calendar is declared by the deployment, never a constant in engine-fin.

Ruled 2026-11-23 (architect). A deployment declares its periods (labels, order, dates, and the
fiscal year, quarter and half of each) in a `fin_calendar` overlay; the engine reads it. The sample
overlay carries the FY26 periods the engine used to hold, so the sandbox is unchanged. A period
outside the declared calendar is refused with the same rule id as before, and with no calendar
declared every period is.

These seals use temporary directories and monkeypatch the environment variable, so each reads the
declaration afresh.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

pl = pytest.importorskip("polars")

from agent_fleet.finance_agent import asset_inputs, entities, fiscal_calendar, seed, slots  # noqa: E402
from agent_fleet.finance_agent.entities import NotInModel, fiscal_periods, periods_in  # noqa: E402
from agent_fleet.finance_agent.fiscal_calendar import FiscalCalendarError, load_calendars  # noqa: E402
from agent_fleet.utils.dataset_contracts import ContractViolation  # noqa: E402
from tests.finance.test_a_dataset_series_row_draws_from_the_asset import (  # noqa: E402,F401
    _clean_env, frame_012, gate, members, post, series_rows,
)
from tests.finance.test_fin_inputs_resolver import frame_of  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "policy" / "overlays" / "sample" / "fin_calendar"
ENV = "FIN_CALENDAR_OVERLAY_DIRS"
LABEL = re.compile(r"\bFY\d{2}(-(\d{2}|Q\d|H\d))?\b")


def _periods(spec):
    """Contiguous monthly periods from 2030-01-01: [(label, fiscal_year, quarter, half), ...]."""
    out, d = [], date(2030, 1, 1)
    for label, fy, q, h in spec:
        end = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        out.append({"label": label, "start": d.isoformat(), "end": end.isoformat(),
                    "fiscal_year": fy, "quarter": q, "half": h})
        d = end + timedelta(days=1)
    return out


GOOD = [("A-1", "Y1", "Q1", "H1"), ("A-2", "Y1", "Q1", "H1"),
        ("A-3", "Y1", "Q2", "H1"), ("A-4", "Y1", "Q2", "H1")]


def _write(d: Path, name="cal.yaml", cid="test_cal", periods=None, **over):
    d.mkdir(parents=True, exist_ok=True)
    doc = {"calendar_id": cid, "periods": periods if periods is not None else _periods(GOOD)}
    doc.update(over)
    (d / name).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return d / name


# -- 1. the sample ----------------------------------------------------------------------------------

def test_the_sample_calendar_loads_and_is_the_fy26_the_engine_used_to_hold():
    cal = load_calendars([SAMPLE])["us_federal_fy26"]
    assert cal.calendar_id == "us_federal_fy26"
    assert list(cal.labels) == [f"FY26-{m:02d}" for m in range(1, 13)]
    assert cal.periods[0].start == date(2025, 10, 1) and cal.periods[-1].end == date(2026, 9, 30)
    for a, b in zip(cal.periods, cal.periods[1:]):
        assert b.start == a.end + timedelta(days=1)
    for kind, size in (("quarter", 3), ("half", 6)):
        counts: dict[str, int] = {}
        for p in cal.periods:
            counts[getattr(p, kind)] = counts.get(getattr(p, kind), 0) + 1
        assert set(counts.values()) == {size} and len(counts) == 12 // size, (kind, counts)
    assert cal.order["FY26-03"] == 2 and cal.row("FY26-02").end == date(2025, 11, 30)
    with pytest.raises(KeyError):
        cal.row("FY99-01")


def test_a_yaml_date_and_an_iso_string_are_both_dates(tmp_path):
    ps = _periods(GOOD)
    ps[0]["start"] = date.fromisoformat(ps[0]["start"])      # dumped as a YAML date
    _write(tmp_path, periods=ps)
    assert load_calendars([tmp_path])["test_cal"].periods[0].start == date(2030, 1, 1)


# -- 2. every refusal names the file ----------------------------------------------------------------

def _refused(tmp_path, fragment=None, **kw):
    f = _write(tmp_path, name="the_file.yaml", **kw)
    with pytest.raises(FiscalCalendarError) as e:
        load_calendars([tmp_path])
    assert f.name in str(e.value), str(e.value)
    if fragment:
        assert fragment in str(e.value)
    return e.value


def _with(i, **kw):
    ps = _periods(GOOD)
    ps[i].update(kw)
    return ps


def test_a_duplicate_label_is_refused(tmp_path):
    _refused(tmp_path, "duplicate label", periods=_with(1, label="A-1"))


def test_a_start_after_its_end_is_refused(tmp_path):
    _refused(tmp_path, "starts after it ends", periods=_with(0, start="2030-02-15"))


def test_a_gap_is_refused(tmp_path):
    ps = _periods(GOOD)
    for p in ps[2:]:       # one extra day after the second period
        p["start"] = (date.fromisoformat(p["start"]) + timedelta(days=1)).isoformat()
        p["end"] = (date.fromisoformat(p["end"]) + timedelta(days=1)).isoformat()
    _refused(tmp_path, "gap", periods=ps)


def test_an_overlap_is_refused(tmp_path):
    ps = _periods(GOOD)
    ps[1]["start"] = "2030-01-31"
    _refused(tmp_path, "overlaps", periods=ps)


def test_a_quarter_split_by_another_quarter_is_refused(tmp_path):
    ps = _periods([("A-1", "Y1", "Q1", "H1"), ("A-2", "Y1", "Q2", "H1"), ("A-3", "Y1", "Q1", "H1")])
    _refused(tmp_path, "quarter 'Q1' are not contiguous", periods=ps)


def test_a_quarter_spanning_two_halves_is_refused(tmp_path):
    ps = _periods([("A-1", "Y1", "Q1", "H1"), ("A-2", "Y1", "Q1", "H2")])
    _refused(tmp_path, "quarter 'Q1' spans two values of half", periods=ps)


def test_a_half_spanning_two_years_is_refused(tmp_path):
    ps = _periods([("A-1", "Y1", "Q1", "H1"), ("A-2", "Y2", "Q2", "H1")])
    _refused(tmp_path, "half 'H1' spans two values of fiscal_year", periods=ps)


def test_an_unknown_top_level_key_is_refused(tmp_path):
    _refused(tmp_path, "exactly the keys", extra="x")


def test_an_unknown_period_key_is_refused(tmp_path):
    _refused(tmp_path, "unknown key", periods=_with(0, colour="red"))


def test_a_missing_key_is_refused(tmp_path):
    ps = _periods(GOOD)
    del ps[1]["half"]
    _refused(tmp_path, "missing required key", periods=ps)
    f = tmp_path / "the_file.yaml"
    f.write_text("periods: []\n", encoding="utf-8")
    with pytest.raises(FiscalCalendarError, match="the_file.yaml"):
        load_calendars([tmp_path])


@pytest.mark.parametrize("bad", ["2030-1-01", "not a date", 20300101, "2030-02-30"])
def test_a_bad_date_is_refused(tmp_path, bad):
    _refused(tmp_path, "must be a date", periods=_with(0, start=bad))


def test_an_empty_periods_list_is_refused(tmp_path):
    _refused(tmp_path, "non-empty list", periods=[])


def test_two_calendar_ids_across_dirs_load_as_two(tmp_path):
    _write(tmp_path / "a", name="first.yaml", cid="one")
    _write(tmp_path / "b", name="second.yaml", cid="two")
    assert sorted(load_calendars([tmp_path / "a", tmp_path / "b"])) == ["one", "two"]


def test_two_calendar_ids_in_one_dir_load_as_two(tmp_path):
    _write(tmp_path, name="a.yaml", cid="one")
    _write(tmp_path, name="b.yaml", cid="two")
    assert sorted(load_calendars([tmp_path])) == ["one", "two"]


def test_the_same_id_twice_in_one_dir_is_refused_naming_both_files(tmp_path):
    _write(tmp_path, name="a.yaml", cid="one")
    _write(tmp_path, name="b.yaml", cid="one")
    with pytest.raises(FiscalCalendarError) as e:
        load_calendars([tmp_path])
    assert "a.yaml" in str(e.value) and "b.yaml" in str(e.value) and "'one'" in str(e.value)


# -- 3. composition ---------------------------------------------------------------------------------

def test_the_same_id_in_a_later_dir_replaces_the_earlier_file_whole(tmp_path):
    _write(tmp_path / "a", cid="same")
    later = _periods([("B-1", "Z1", "Q1", "H1"), ("B-2", "Z1", "Q1", "H1")])
    _write(tmp_path / "b", cid="same", periods=later)
    cals = load_calendars([tmp_path / "a", tmp_path / "b"])
    assert list(cals) == ["same"] and list(cals["same"].labels) == ["B-1", "B-2"]


# -- 4. no calendar declared ------------------------------------------------------------------------

@pytest.fixture
def no_calendar(monkeypatch):
    monkeypatch.setenv(ENV, "")


def test_with_no_calendar_the_empty_calendar_is_returned(no_calendar):
    assert load_calendars() == {}
    cal = fiscal_calendar.default_calendar()
    assert (cal.calendar_id, cal.periods, cal.source) == ("", (), "")
    assert fiscal_periods() == ()


@pytest.mark.parametrize("window", [None, ["FY26-01"], "FY26-01"])
def test_with_no_calendar_periods_in_refuses_and_names_the_variable(no_calendar, window):
    with pytest.raises(NotInModel) as e:
        periods_in(window)
    assert ENV in str(e.value) and "no fiscal calendar is declared" in str(e.value)


def test_with_no_calendar_the_state_read_refuses_period_outside_calendar(monkeypatch):
    frame = frame_of()                              # built under the sample, then the calendar goes
    assert asset_inputs.state_from_rows(frame, frame["program_id"][0]).facts
    monkeypatch.setenv(ENV, "")
    with pytest.raises(ContractViolation) as e:
        asset_inputs.state_from_rows(frame, frame["program_id"][0])
    assert e.value.rule == "period_outside_calendar"


def test_with_no_calendar_the_series_read_refuses_period_outside_calendar(post, monkeypatch):
    status, _ = post()
    assert status == 200                            # the control: the sample calendar serves it
    monkeypatch.setenv(ENV, "")
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "period_outside_calendar"


# -- 5. the engine reads the declaration, with a control --------------------------------------------

FY27 = [("FY27-01", "FY27", "FY27-Q1", "FY27-H1"), ("FY27-02", "FY27", "FY27-Q1", "FY27-H1"),
        ("FY27-03", "FY27", "FY27-Q1", "FY27-H1")]


PROGRAM_B = REPO / "tests" / "fixtures" / "fin_program_b" / "fin_calendar"
BOTH = pytest.mark.parametrize("cal_dir", [SAMPLE, PROGRAM_B], ids=["sample", "program_b"])


def _declared(cal_dir, monkeypatch):
    """Point the environment at `cal_dir`; the declared labels, in list order. Program B's are the
    non-lexical control: sorted, P10 falls before P2, so a sort cannot pass for the declared order."""
    monkeypatch.setenv(ENV, str(cal_dir))
    (cal,) = load_calendars([cal_dir]).values()
    labels = list(cal.labels)
    if cal_dir == PROGRAM_B:
        assert sorted(labels) != list(labels)
    return labels


@BOTH
def test_the_engine_reads_the_declared_labels_not_the_sample(cal_dir, monkeypatch):
    labels = _declared(cal_dir, monkeypatch)
    first3 = frame_of().filter(pl.col("period").is_in(["FY26-01", "FY26-02", "FY26-03"]))
    pid = first3["program_id"][0]
    mapping = dict(zip(["FY26-01", "FY26-02", "FY26-03"], labels))
    relabelled = first3.with_columns(pl.col("period").replace(mapping))
    assert asset_inputs.state_from_rows(relabelled, pid).facts
    assert periods_in(None) == labels
    assert fiscal_periods() == tuple(labels)
    assert entities.period_order() == {p: i for i, p in enumerate(labels)}
    if cal_dir == PROGRAM_B:
        with pytest.raises(ContractViolation) as e:      # FY26 is outside this deployment's calendar
            asset_inputs.state_from_rows(first3, pid)
        assert e.value.rule == "period_outside_calendar"
        with pytest.raises(NotInModel, match="unknown fiscal period"):
            periods_in(["FY26-01"])


def test_the_engine_reads_a_declared_fy27_calendar_not_the_sample(tmp_path, monkeypatch):
    _write(tmp_path, cid="fy27", periods=_periods(FY27))
    monkeypatch.setenv(ENV, str(tmp_path))
    first3 = frame_of().filter(pl.col("period").is_in(["FY26-01", "FY26-02", "FY26-03"]))
    pid = first3["program_id"][0]
    with pytest.raises(ContractViolation) as e:
        asset_inputs.state_from_rows(first3, pid)
    assert e.value.rule == "period_outside_calendar"
    relabelled = first3.with_columns(pl.col("period").str.replace("FY26", "FY27"))
    assert asset_inputs.state_from_rows(relabelled, pid).facts      # the control: same frame, FY27
    assert periods_in(None) == ["FY27-01", "FY27-02", "FY27-03"]


@BOTH
def test_the_series_read_follows_the_declared_calendar_too(cal_dir, monkeypatch, post, gate):
    # The rows loaded under the sample and their contract names the sample's calendar. Under the
    # sample it serves, in the declared order; once only program B is declared, that calendar is gone.
    labels = _declared(cal_dir, monkeypatch)
    status, body = post()
    if cal_dir == SAMPLE:
        assert status == 200 and [r["period"] for r in body["rows"]] == labels[:6]
    else:
        assert status == 502 and body["detail"]["rule"] == "period_outside_calendar"


# -- 6. registration and the seed follow the calendar -----------------------------------------------

@BOTH
def test_registration_attaches_the_declared_periods_when_given_none(cal_dir, monkeypatch):
    labels = _declared(cal_dir, monkeypatch)
    records = [{"name": name, "values": []} for name in sorted(slots._PERIOD_SLOTS)]
    out = slots.with_live_vocabularies(records)
    assert out and all(r["values"] == labels and r["values"] for r in out)


@BOTH
def test_the_seed_reports_the_first_six_declared_periods(cal_dir, monkeypatch):
    labels = _declared(cal_dir, monkeypatch)
    # `seed` fixes its reported periods at import: import a private copy under the declared calendar.
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("_seed_under_test", seed.__file__)
    copy = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = copy
    try:
        spec.loader.exec_module(copy)
    finally:
        sys.modules.pop(spec.name, None)
    assert copy.REPORTED_PERIODS == tuple(labels[:6])
    assert len(copy.REPORTED_PERIODS) == 6


# -- 7. the census: no period label in engine code --------------------------------------------------

def test_no_period_label_is_named_in_engine_code():
    hits = []
    for f in sorted((REPO / "agent_fleet" / "finance_agent").rglob("*.py")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if LABEL.search(line):
                hits.append(f"{f.name}:{n}")
    assert hits == []


def test_the_census_regex_sees_the_form():
    text = (SAMPLE / "us_federal_fy26.yaml").read_text(encoding="utf-8")
    assert len(LABEL.findall(text)) >= 12
    for planted in ("FY26", "FY26-01", "FY26-Q1", "FY26-H2"):
        assert LABEL.search(f"x = '{planted}'  # note")


def test_the_two_constants_are_gone():
    assert not hasattr(entities, "FISCAL_PERIODS") and not hasattr(entities, "PERIOD_ORDER")


# -- 8. the chart -----------------------------------------------------------------------------------

def test_the_sandbox_declares_the_sample_calendar_and_the_repo_dir_holds_one_loadable_file():
    sandbox = yaml.safe_load((REPO / "helm/invincible-agent/values-sandbox.yaml").read_text(encoding="utf-8"))

    def find(node):
        if isinstance(node, dict):
            if ENV in node:
                yield node[ENV]
            for v in node.values():
                yield from find(v)

    values = list(find(sandbox))
    assert len(values) == 1 and values[0].endswith("policy/overlays/sample/fin_calendar"), values
    assert len(list(SAMPLE.glob("*.yaml"))) == 1 and len(list(SAMPLE.iterdir())) == 1
    assert load_calendars([SAMPLE])["us_federal_fy26"].periods


def test_the_chart_gives_engine_fin_a_fin_calendar_overlay_row():
    values = yaml.safe_load((REPO / "helm/invincible-agent/values.yaml").read_text(encoding="utf-8"))
    rows = values["policyOverlay"]["components"]["engine-fin"]
    mine = [r for r in rows if r["dir"] == "fin_calendar"]
    assert len(mine) == 1 and mine[0]["env"] == ENV and mine[0]["optional"] is True


# -- 6a. gov's surviving mutants, killed under program B ---------------------------------------------
# Each of these sites ordered or listed periods correctly under the sample only because the sample's
# labels sort lexically. Under program B, P10 sorts before P2, so a plain sort, a lexical index or a
# hard-coded FY26 list gives a different answer. The relabelling puts the six seed periods on P7..P12,
# the stretch where the lexical and the declared order disagree.

_LATE_B = ["P7", "P8", "P9", "P10", "P11", "P12"]


def _seed_on_late_b():
    """The sample seed with its six reported periods relabelled onto program B's P7..P12."""
    import dataclasses
    mapping = dict(zip(seed.REPORTED_PERIODS, _LATE_B))
    state = seed.build_seed()
    state.facts[:] = [dataclasses.replace(f, period=mapping[f.period]) for f in state.facts]
    state.funding[:] = [dataclasses.replace(f, period=mapping[f.period]) for f in state.funding]
    return state


def test_under_program_b_an_out_of_order_window_comes_back_in_declared_order(monkeypatch):
    # gov E8: `periods_in` sorts by the declared order, not by the label.
    _declared(PROGRAM_B, monkeypatch)
    assert periods_in(["P10", "P2"]) == ["P2", "P10"]
    assert periods_in(["P12", "P1", "P9", "P10"]) == ["P1", "P9", "P10", "P12"]


def test_under_program_b_the_funding_grid_orders_periods_as_declared(monkeypatch):
    # gov E16: the grid's `order` is the declared index, not a lexical one.
    from agent_fleet.finance_agent import measures
    state = _seed_on_late_b()
    _declared(PROGRAM_B, monkeypatch)
    rows = measures.fin_funding_status(state, program_id=state.funding[0].program_id)
    by_line: dict[str, list[str]] = {}
    for r in rows:
        by_line.setdefault(r["subject_id"], []).append(r["period"])
    assert by_line and all(ps == _LATE_B for ps in by_line.values()), by_line


def test_under_program_b_registration_offers_the_declared_periods_the_state_carries(monkeypatch):
    # gov E12: `_registration_calls` reads the declared calendar, filtered to the state's periods.
    from agent_fleet.finance_agent import main as engine
    monkeypatch.setattr(engine, "STATE", _seed_on_late_b())
    _declared(PROGRAM_B, monkeypatch)
    window_values = [s["values"] for c in engine._registration_calls() for s in c["slots"]
                     if s["name"] in slots._PERIOD_SLOTS]
    assert window_values and all(v == _LATE_B for v in window_values), window_values[:2]
