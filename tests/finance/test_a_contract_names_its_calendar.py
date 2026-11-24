"""A calendar is a named declaration, and a contract says which one it uses.

Ruled 2026-11-23 (architect). A deployment with one calendar declares one and it is the default.
With several, a contract names one (`period.calendar`). With a dataset configured and no calendar
declared the engine is not ready: it does not start and then refuse every answer.

Program B's calendar (tests/fixtures/fin_program_b) is the control of a different shape: a 4-4-5
year whose labels P1..P12 are not in lexical order.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

pl = pytest.importorskip("polars")

from agent_fleet.finance_agent import asset_inputs, fiscal_calendar  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent.fiscal_calendar import FiscalCalendarError, load_calendars  # noqa: E402
from agent_fleet.utils import dataset_contracts  # noqa: E402
from agent_fleet.utils.dataset_contracts import ContractViolation  # noqa: E402
from tests.finance.test_a_dataset_series_row_draws_from_the_asset import (  # noqa: E402,F401
    CONTRACT, CUM, PROGRAM, ROW_URN, ROWS, frame_012,
)
from tests.finance.test_fin_inputs_resolver import _clean_env  # noqa: E402,F401

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "policy" / "overlays" / "sample" / "fin_calendar"
PROGRAM_B = REPO / "tests" / "fixtures" / "fin_program_b" / "fin_calendar"
ENV = "FIN_CALENDAR_OVERLAY_DIRS"
B = "program_b_445"
FY26 = "us_federal_fy26"


def _both(monkeypatch):
    monkeypatch.setenv(ENV, os.pathsep.join([str(SAMPLE), str(PROGRAM_B)]))


# -- 1. default_calendar ----------------------------------------------------------------------------

def test_default_calendar_is_empty_the_one_or_empty(monkeypatch):
    monkeypatch.setenv(ENV, "")
    assert fiscal_calendar.default_calendar().calendar_id == ""
    monkeypatch.setenv(ENV, str(SAMPLE))
    assert fiscal_calendar.default_calendar().calendar_id == FY26
    _both(monkeypatch)
    assert fiscal_calendar.default_calendar().calendar_id == ""


# -- 2. calendar_for --------------------------------------------------------------------------------

def test_calendar_for_none_with_one_declared_is_the_one(monkeypatch):
    monkeypatch.setenv(ENV, str(PROGRAM_B))
    assert fiscal_calendar.calendar_for(None).calendar_id == B


def test_calendar_for_none_with_none_declared_names_the_variable(monkeypatch):
    monkeypatch.setenv(ENV, "")
    with pytest.raises(FiscalCalendarError) as e:
        fiscal_calendar.calendar_for(None)
    assert ENV in str(e.value) and "dataset reads its periods in a declared calendar" in str(e.value)


def test_calendar_for_none_with_two_declared_names_both(monkeypatch):
    _both(monkeypatch)
    with pytest.raises(FiscalCalendarError) as e:
        fiscal_calendar.calendar_for(None)
    assert FY26 in str(e.value) and B in str(e.value) and "period.calendar" in str(e.value)


def test_calendar_for_an_undeclared_id_names_it_and_the_declared(monkeypatch):
    _both(monkeypatch)
    with pytest.raises(FiscalCalendarError) as e:
        fiscal_calendar.calendar_for("nope")
    assert "'nope'" in str(e.value) and FY26 in str(e.value) and B in str(e.value)
    assert fiscal_calendar.calendar_for(B).calendar_id == B


# -- 3. the parser ----------------------------------------------------------------------------------

def _raw(**over):
    raw = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    raw.pop("period", None)
    raw.update(over)
    return raw


def test_period_calendar_is_read():
    assert dataset_contracts._parse(_raw(period={"calendar": B, "column": "period"})).calendar == B


def test_an_absent_period_or_a_period_without_a_calendar_is_none():
    assert dataset_contracts._parse(_raw()).calendar is None
    assert dataset_contracts._parse(_raw(period={"column": "period"})).calendar is None


@pytest.mark.parametrize("bad", [{"calendar": 3}, {"calendar": ""}, ["x"]])
def test_a_malformed_period_is_refused(bad):
    with pytest.raises(ValueError, match="period"):
        dataset_contracts._parse(_raw(period=bad))


# -- 4. a dataset row's load ------------------------------------------------------------------------

def _load_row(tmp_path, monkeypatch, calendar):
    """Load the sample's cumulative series row over a contract in tmp naming `calendar` (None: none)."""
    cdir, overlay = tmp_path / "contracts", tmp_path / "overlay"
    cdir.mkdir(exist_ok=True)
    overlay.mkdir(exist_ok=True)
    raw = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    raw["period"] = {k: v for k, v in raw["period"].items() if k != "calendar"}
    if calendar is not None:
        raw["period"]["calendar"] = calendar
    (cdir / "ev_fixture.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    (overlay / f"{CUM}.yaml").write_bytes((ROWS / f"{CUM}.yaml").read_bytes())
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(cdir))
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(overlay))
    return engine._load_declared()


def test_a_series_row_whose_contract_names_a_calendar_loads_with_it(tmp_path, monkeypatch):
    _both(monkeypatch)
    rows = _load_row(tmp_path, monkeypatch, B)
    assert rows[CUM].calendar_id == B


def test_a_contract_naming_none_with_two_declared_is_refused_at_load(tmp_path, monkeypatch):
    _both(monkeypatch)
    with pytest.raises(ValueError, match="ev_fixture"):
        _load_row(tmp_path, monkeypatch, None)


def test_a_contract_naming_an_undeclared_calendar_is_refused_at_load(tmp_path, monkeypatch):
    _both(monkeypatch)
    with pytest.raises(ValueError, match="nope"):
        _load_row(tmp_path, monkeypatch, "nope")


def test_with_no_calendar_declared_a_dataset_row_is_refused_at_load_not_per_request(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, "")
    with pytest.raises(ValueError, match=ENV):
        _load_row(tmp_path, monkeypatch, None)


def test_with_one_declared_a_contract_naming_none_loads_with_the_one(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, str(PROGRAM_B))
    assert _load_row(tmp_path, monkeypatch, None)[CUM].calendar_id == B


# -- 5. the series read under program B -------------------------------------------------------------

def _b_frame(period_of):
    """frame_012 twice over, the periods remapped by `period_of` (12 distinct), rows reversed."""
    base = frame_012()
    old = [f"FY26-{m:02d}" for m in range(1, 7)]
    a = base.with_columns(pl.col("period").replace(dict(zip(old, period_of[:6]))))
    b = base.with_columns(pl.col("period").replace(dict(zip(old, period_of[6:]))))
    return pl.concat([a, b]).reverse()


def _read(frame, labels):
    contract = dataset_contracts.load_contract("ev_fixture", CONTRACT.parent)
    return asset_inputs.read_dataset_series(
        lambda urn: frame.lazy(), ROW_URN, scope="program_id", period="period", status="status_period",
        per_period=("bcws", "bcwp", "acwp"), per_program=("program_bac",), program_id=PROGRAM,
        contract=contract, calendar=labels)


def _b_labels():
    return tuple(next(iter(load_calendars([PROGRAM_B]).values())).labels)


def test_the_series_read_returns_program_b_periods_in_declared_order():
    labels = _b_labels()
    assert sorted(labels) != list(labels)
    frame = _b_frame(labels).with_columns(pl.lit("P6").alias("status_period"))
    got = [p for p, _ in _read(frame, labels).periods]
    assert got == list(labels)
    assert got.index("P10") > got.index("P9") and got.index("P2") < got.index("P10")


def test_a_period_of_another_calendar_is_outside_program_b():
    labels = _b_labels()
    frame = _b_frame(labels).with_columns(pl.lit("P6").alias("status_period"))
    frame = frame.with_columns(pl.when(pl.col("period") == "P1").then(pl.lit("FY26-01"))
                               .otherwise(pl.col("period")).alias("period"))
    with pytest.raises(ContractViolation) as e:
        _read(frame, labels)
    assert e.value.rule == "period_outside_calendar"


# -- 6. boot with the URN set -----------------------------------------------------------------------

@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("FIN_DATASET_URN", ROW_URN)
    monkeypatch.setenv("FIN_DATASET_BANNER", "SYNTHETIC TEST ASSET")
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    monkeypatch.setattr(asset_inputs, "_load_client", lambda: None)


def test_boot_with_a_dataset_and_one_calendar_passes(configured, monkeypatch):
    monkeypatch.setenv(ENV, str(SAMPLE))
    asset_inputs.check_config()


def test_boot_with_a_dataset_and_no_calendar_is_not_ready(configured, monkeypatch):
    monkeypatch.setenv(ENV, "")
    with pytest.raises(RuntimeError, match="no fiscal calendar is declared"):
        asset_inputs.check_config()


def test_boot_with_a_dataset_and_two_calendars_is_not_ready(configured, monkeypatch):
    _both(monkeypatch)
    with pytest.raises(RuntimeError) as e:
        asset_inputs.check_config()
    assert "2 fiscal calendars" in str(e.value) and FY26 in str(e.value) and B in str(e.value)


def test_boot_with_a_broken_calendar_is_not_ready(configured, tmp_path, monkeypatch):
    (tmp_path / "bad.yaml").write_text("periods: []\n", encoding="utf-8")
    monkeypatch.setenv(ENV, str(tmp_path))
    with pytest.raises(RuntimeError, match="bad.yaml"):
        asset_inputs.check_config()
