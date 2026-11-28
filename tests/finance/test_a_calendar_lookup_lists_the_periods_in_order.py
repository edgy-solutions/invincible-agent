"""`fin_calendar_periods`: the periods of the declared fiscal calendar in the calendar's own order, the
data's status period marked (ruled 2026-11-25). No amount, no verdict; asset only; read as the caller.

Two populations: the route over the EV fixture's contract (it declares a `status_period`), and the
reader over Program B's contract and its 4-4-5 calendar (`P1..P12`, non-lexical: sorted, P10 falls
before P2). A frame is read through a recording proxy, so the request the read made is asserted, not
only the output.

Run: uv run --no-sync pytest -c pyproject.toml --rootdir=. -p no:cacheprovider -p no:langsmith_plugin tests/finance/test_a_calendar_lookup_lists_the_periods_in_order.py
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import asset_inputs, fiscal_calendar, lookups  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent.entities import NotInModel  # noqa: E402
from agent_fleet.utils import dataset_contracts  # noqa: E402
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import b_frame  # noqa: E402
from tests.finance.test_fin_inputs_resolver import _clean_env, frame_of, token  # noqa: E402,F401
from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402
    ALLOWED, DENIED, Gate, PROGRAM, ROW_URN,
)

REPO = Path(__file__).resolve().parents[2]
SAMPLE_CAL = REPO / "policy" / "overlays" / "sample" / "fin_calendar"
B_DIR = REPO / "tests" / "fixtures" / "fin_program_b"
FN = "fin_calendar_periods"
STATUS = "FY26-06"


class Recorder:
    """A fake `read`: hands back a proxy over `lf` that records what the read selected."""

    def __init__(self, lf):
        self.lf, self.reads, self.selected = lf, 0, []

    def __call__(self, urn):
        self.reads += 1
        rec = self

        class Proxy:
            def __init__(self, lf):
                self.lf = lf

            def collect_schema(self):
                return self.lf.collect_schema()

            def filter(self, *a):
                return Proxy(self.lf.filter(*a))

            def select(self, cols):
                rec.selected.append(list(cols))
                return Proxy(self.lf.select(cols))

            def head(self, n):
                return Proxy(self.lf.head(n))

            def collect(self):
                return self.lf.collect()

        return Proxy(self.lf)


def ev_frame(status=STATUS):
    return frame_of().with_columns(pl.lit(status).alias("status_period"))


@pytest.fixture
def ev(monkeypatch):
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", str(SAMPLE_CAL))
    fiscal_calendar._cache.clear()
    yield dataset_contracts.load_contract("ev_fixture", REPO / "contracts")
    fiscal_calendar._cache.clear()


@pytest.fixture
def b(monkeypatch):
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", str(B_DIR / "fin_calendar"))
    fiscal_calendar._cache.clear()
    yield dataset_contracts.load_contract("program_b", B_DIR / "contracts")
    fiscal_calendar._cache.clear()


# -- the reader, over the 4-4-5 calendar -----------------------------------------------------------

def test_the_periods_come_in_the_calendars_own_order_never_sorted_by_label(b):
    read = Recorder(b_frame().lazy())
    got = asset_inputs.read_calendar_status(read, "urn", program_id="PRG-B", contract=b)
    answer = lookups.calendar_answer(got.calendar, got.status, got.status_column)
    declared = [p["label"] for p in yaml.safe_load(
        (B_DIR / "fin_calendar" / "program_b_445.yaml").read_text(encoding="utf-8"))["periods"]]
    labels = [p["label"] for p in answer["periods"]]
    assert labels == declared == [f"P{n}" for n in range(1, 13)]
    assert labels.index("P10") == labels.index("P9") + 1
    assert labels != sorted(labels)  # the control: a label sort would put P10 before P2
    assert [r["label"] for r in answer["rows"]] == labels
    assert answer["calendar_id"] == "program_b_445"


def test_no_status_period_declared_marks_nothing_and_still_makes_one_read(b):
    assert b.status_column is None
    read = Recorder(b_frame().lazy())
    got = asset_inputs.read_calendar_status(read, "urn", program_id="PRG-B", contract=b)
    answer = lookups.calendar_answer(got.calendar, got.status, got.status_column)
    assert read.reads == 1
    assert read.selected == [[b.scope]]  # the scope column alone
    assert answer["status_period"] is None and answer["status_column"] is None
    assert not any(p["status"] for p in answer["periods"])
    assert "no status period" in answer["title"]


def test_a_program_the_asset_does_not_hold_is_not_in_the_model(b):
    with pytest.raises(NotInModel):
        asset_inputs.read_calendar_status(Recorder(b_frame().lazy()), "urn", program_id="PRG-NONE", contract=b)


# -- the reader, over the EV fixture's status period -----------------------------------------------

def test_exactly_one_period_is_marked_and_it_is_the_datas_status_value(ev):
    read = Recorder(ev_frame().lazy())
    got = asset_inputs.read_calendar_status(read, "urn", program_id=PROGRAM, contract=ev)
    answer = lookups.calendar_answer(got.calendar, got.status, got.status_column)
    assert read.selected == [[ev.scope, "status_period"]]
    assert [p["label"] for p in answer["periods"] if p["status"]] == [STATUS]
    assert answer["status_period"] == STATUS and answer["status_column"] == "status_period"


def test_the_status_comes_from_the_data_mutate_the_frame_and_the_mark_moves(ev):
    marked = []
    for value in ("FY26-02", "FY26-11"):  # the control: the same contract and calendar, a different value
        got = asset_inputs.read_calendar_status(Recorder(ev_frame(value).lazy()), "urn",
                                                program_id=PROGRAM, contract=ev)
        marked.append([p["label"] for p in lookups.calendar_answer(
            got.calendar, got.status, got.status_column)["periods"] if p["status"]])
    assert marked == [["FY26-02"], ["FY26-11"]]


def test_a_status_value_outside_the_calendar_refuses_period_outside_calendar(ev):
    with pytest.raises(asset_inputs.ContractViolation) as exc:
        asset_inputs.read_calendar_status(Recorder(ev_frame("FY27-01").lazy()), "urn",
                                          program_id=PROGRAM, contract=ev)
    assert exc.value.rule == "period_outside_calendar"
    assert "FY27-01" not in exc.value.message  # names the rule, never a row's value


# -- the route -------------------------------------------------------------------------------------

@pytest.fixture
def route(tmp_path, monkeypatch, ev):
    path = tmp_path / "ev.parquet"
    ev_frame().write_parquet(path)
    gate = Gate(pl.scan_parquet(path))
    monkeypatch.setattr(engine.asset_inputs, "_load_client", gate.load)
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program == PROGRAM and caller_id in {ALLOWED, DENIED})
    monkeypatch.setenv("FIN_DATASET_URN", ROW_URN)
    monkeypatch.setenv("FIN_DATASET_BANNER", "SYNTHETIC TEST ASSET - not a real program.")
    monkeypatch.setenv("FIN_DATASET_CONTRACT", "ev_fixture")
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    with TestClient(engine.app) as c:
        def post(who=ALLOWED, params=None, fn=FN):
            r = c.post(f"/measure/{fn}", json={"params": params or {"program_id": PROGRAM}, "user_email": who},
                       headers={"Authorization": f"Bearer {token(who)}"})
            return r.status_code, r.json()
        post.gate = gate
        yield post


def test_the_route_answers_a_table_with_the_status_row_marked_and_the_reads_provenance(route):
    status, env = route()
    assert status == 200, env
    assert env["measure"] == FN and env["output_uri"].endswith("FiscalCalendarPeriods")
    assert env["row_identity"] == {"key": "label"} and "class" not in env["target"]
    assert [r["label"] for r in env["rows"] if r["status"]] == [STATUS]
    assert env["data_source"] == {"kind": "asset", "urn": ROW_URN}
    assert env["data_provenance"].endswith(f"Source: {ROW_URN}") and len(env["sources"]) == 1
    assert not {"value_unit", "verdict", "series"} & set(env)  # no amounts, no verdict
    assert len(route.gate.asked) == 1


def test_a_denied_read_refuses_and_the_same_request_with_a_grant_answers(route):
    status, env = route(DENIED)
    assert status == 403 and env["detail"]["status"] == "access_denied", env
    route.gate.granted.add(DENIED)  # the control: the same request, a grant
    status, env = route(DENIED)
    assert status == 200, env


def test_no_dataset_configured_the_verb_refuses_and_never_answers_from_the_seed(route, monkeypatch):
    monkeypatch.delenv("FIN_DATASET_URN")
    status, env = route()
    assert status == 422 and env["detail"]["error"] == "no_dataset", env
    assert "none is configured" in env["detail"]["message"]
    assert route.gate.asked == []  # nothing was read
