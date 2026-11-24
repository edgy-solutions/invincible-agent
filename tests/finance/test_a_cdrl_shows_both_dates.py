"""The xlsx and docx CDRL title blocks show two labelled dates (architect ruling, 2026-11-21).

The sample templates used to carry one row, "As of". They now carry "Data as of" and "Generated",
filled by the profile rows' `as_of` and `generated_on` cells. On a seed-sourced build the data
as-of reads the sample wording and the generated cell holds the server's date; the two never
hold the same text.
"""
from __future__ import annotations

import sys
from pathlib import Path

import docx
import openpyxl
import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import cdrl  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_a_cdrl_is_an_export_profile import (  # noqa: E402,F401
    ALICE, PROFILE as XLSX, PROGRAM, SAMPLE, declared, profiles, served,
)

DOCX = "cdrl_a002_cost_performance_docx"
SAMPLE_WORDING = "sample data (notional seed): no as-of"
DATA, GENERATED = "2026-09-30", "2026-10-28"


@pytest.fixture(autouse=True)
def _server_clock(monkeypatch):
    monkeypatch.setattr(engine, "_request_date", lambda: GENERATED)


def _build(profiles, name, tmp_path, data_as_of=DATA):
    path, _ = cdrl.build_cdrl(
        engine.STATE, profiles[name], program_id=PROGRAM, data_as_of=data_as_of,
        generated_on=GENERATED, out_dir=tmp_path,
        run_source=lambda fn, params: engine._cdrl_source(fn, params, caller=ALICE))
    return path


def _route(served, name, ext):
    c, dist, _ = served
    r = c.post("/cdrl_export", json={"profile": name, "program_id": PROGRAM, "user_email": ALICE})
    assert r.status_code == 200, r.text
    return dist / r.json()["artifact_filename"]


def test_1_the_xlsx_shows_the_data_date_and_the_generated_date(profiles, tmp_path):
    ws = openpyxl.load_workbook(_build(profiles, XLSX, tmp_path))["EV Summary"]
    assert ws["A4"].value == "Data as of" and ws["B4"].value == DATA
    assert ws["A5"].value == "Generated" and ws["B5"].value == GENERATED
    assert ws["A6"].value == "CDRL item" and ws["B6"].value == "A001"


def test_2_the_docx_shows_the_data_date_and_the_generated_date(profiles, tmp_path):
    t1 = docx.Document(str(_build(profiles, DOCX, tmp_path))).tables[0]
    assert len(t1.rows) == 6
    assert (t1.cell(2, 0).text, t1.cell(2, 1).text) == ("Data as of", DATA)
    assert (t1.cell(3, 0).text, t1.cell(3, 1).text) == ("Generated", GENERATED)
    assert t1.cell(4, 0).text == "CDRL item"


def test_3_a_seed_sourced_xlsx_never_shows_the_generated_date_as_the_data_date(served):
    ws = openpyxl.load_workbook(_route(served, XLSX, "xlsx"))["EV Summary"]
    assert ws["B4"].value == SAMPLE_WORDING
    assert ws["B5"].value == GENERATED
    assert ws["B4"].value != ws["B5"].value


def test_3_a_seed_sourced_docx_never_shows_the_generated_date_as_the_data_date(served):
    t1 = docx.Document(str(_route(served, DOCX, "docx"))).tables[0]
    assert t1.cell(2, 1).text == SAMPLE_WORDING
    assert t1.cell(3, 1).text == GENERATED
    assert t1.cell(2, 1).text != t1.cell(3, 1).text
