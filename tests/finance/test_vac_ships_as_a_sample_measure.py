"""VAC ships as the second sample measure behind the overlay contract -- a row, no code.

Why: the overlay contract (docs/contracts/finance-overlays.md) showed VAC as a doc-only example
and the sample shipped TCPI alone. Shipping `policy/overlays/sample/measure_verbs/fin_vac.yaml`
proves the engine serves a second row, an AMOUNT, from the yaml alone (test 3 of the 10-30 rule).
A shipped policy row is granted by `seed`, never a person or a placeholder (ruling 10-31).

Arms:
  a. the real loader over the sample dir declares `fin_vac_cpi`; module VERSION == row version.
  b. the engine serves it as ALICE on NP-MERIDIAN: output_uri, unit, each defined row equals
     `vac.vac_cpi` recomputed from the state, each undefined row says `no_work_performed`.
  c. the verdict restates the last period against the row's reference.
  d. registration carries `finVarianceAtCompletion` with the row's cells as domains.
  e. no production .py is needed: the loader and engine serve it from the yaml (the diff stat
     confirms no .py under agent_fleet/ or src/).
  g. every sample measure row is `granted_by: seed`.

Run: uv run --no-sync pytest tests/finance/test_vac_ships_as_a_sample_measure.py
"""
from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import replace
from decimal import Decimal

import pytest
import yaml
from fastapi.testclient import TestClient

from agent_fleet.finance_agent import main as engine
from agent_fleet.finance_agent import measure_verbs, measures
from agent_fleet.finance_agent.entities import periods_in
from agent_fleet.finance_agent.measure_modules import vac
from tests.finance.test_a_measure_is_an_overlay_row import (  # noqa: F401 -- fixtures by import
    ALICE, BUILTINS, PROGRAM, REPO, SAMPLE, Double, double,
)

VAC_YAML = SAMPLE / "fin_vac.yaml"
ROW_DOC = yaml.safe_load(VAC_YAML.read_text(encoding="utf-8"))


def _doc_example_unit():
    """The unit of the contract doc's VAC example: a second source, so a row edited alone reds."""
    text = (REPO / "docs" / "contracts" / "finance-overlays.md").read_text(encoding="utf-8")
    for block in re.findall(r"```yaml\n(# loads-as: measure_verb\n.*?)```", text, re.S):
        doc = yaml.safe_load(block)
        if doc["measure_id"] == "fin_vac_cpi":
            return doc["outputs"]["series"][0]["unit"]
    raise AssertionError("the doc has no fin_vac_cpi example")


@pytest.fixture
def declared(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(SAMPLE))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    for r in rows.values():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + r.verb, r.measure_id)
    return rows


@pytest.fixture
def client(declared):
    with TestClient(engine.app) as c:
        yield c


def _ask(client, user=ALICE):
    return client.post("/measure/fin_vac_cpi", json={"params": {"program_id": PROGRAM}, "user_email": user})


def _expected(state):
    program = next(p for p in state.programs if p.program_id == PROGRAM)
    ca = {c.ca_id for c in state.accounts_of(PROGRAM)}
    wps = {w.wp_id for w in state.work_packages if w.ca_id in ca}
    out, cum = [], [Decimal(0)] * 3
    for period in periods_in(None):
        t = measures._totals_exact(state, wps, [period])
        if t == (0, 0, 0):
            continue
        cum = [cum[i] + t[i] for i in range(3)]
        bac = Decimal(str(program.bac))
        # the doc's transcription, written out here and NOT via vac.vac_cpi: a wrong module must red
        out.append((period, bac - bac * cum[2] / cum[1] if cum[1] > 0 else None))
    return out


def test_a_the_real_loader_declares_it_and_the_module_version_equals_the_rows():
    rows = measure_verbs.load_measure_verbs(
        policy_dir=SAMPLE.parent / "no-seed", overlay_dirs=[SAMPLE], builtins=BUILTINS)
    by_id = {r.measure_id: r for r in rows}
    assert "fin_vac_cpi" in by_id
    assert by_id["fin_vac_cpi"].verb == "finVarianceAtCompletion"
    assert vac.VERSION == ROW_DOC["computation"]["version"]


def test_b_the_engine_serves_it_and_each_row_equals_the_independent_computation(double, client):
    r = _ask(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["output_uri"].endswith(ROW_DOC["outputs"]["output_uri"])
    assert body["series"][0]["unit"] == ROW_DOC["outputs"]["series"][0]["unit"] == _doc_example_unit()
    expected = _expected(engine.STATE)
    assert [x["period"] for x in body["rows"]] == [p for p, _ in expected]
    assert len(expected) >= 2
    defined = 0
    for got, (period, want) in zip(body["rows"], expected):
        if want is None:
            assert got["undefined"] == ROW_DOC["outputs"]["undefined"]["reason"], period
            assert got["vac"] is None
        else:
            defined += 1
            assert got["vac"] == pytest.approx(float(want)), period
    assert defined, "no defined period; the arm checks nothing"


def test_b_a_period_with_no_work_performed_is_undefined_with_its_reason(double, client, monkeypatch):
    state = copy.deepcopy(engine.STATE)
    program = next(p for p in state.programs if p.program_id == PROGRAM)
    ca = {c.ca_id for c in state.accounts_of(PROGRAM)}
    wps = {w.wp_id for w in state.work_packages if w.ca_id in ca}
    state.facts = [replace(f, bcwp=0) if f.wp_id in wps else f for f in state.facts]
    monkeypatch.setattr(engine, "STATE", state)
    body = _ask(client).json()
    assert body["rows"], "no periods"
    for row in body["rows"]:
        assert row["undefined"] == "no_work_performed"
        assert row["vac"] is None


def test_c_the_verdict_restates_the_last_period_against_the_reference(double, client):
    body = _ask(client).json()
    last = body["rows"][-1]
    ref = ROW_DOC["outputs"]["reference"]
    side = "above" if last["vac"] > ref["value"] else "below" if last["vac"] < ref["value"] else "at"
    label = ROW_DOC["outputs"]["series"][0]["label"]
    assert body["verdict"] == f"{label} {last['vac']:.2f}, {side} {ref['value']} ({ref['label']}) at {last['period']}"


def test_d_registration_carries_the_verb_with_the_rows_cells_as_domains(declared):
    calls = {c["verb"]: c for c in engine._registration_calls("http://engine")}
    c = calls["mesh:" + ROW_DOC["verb"]]
    assert c["endpoint_url"] == "http://engine/measure/fin_vac_cpi"
    assert c["output_uri"] == measures.FIN + ROW_DOC["outputs"]["output_uri"]
    assert list(declared["fin_vac_cpi"].cells) == ROW_DOC["policy"]["cells"]  # the registration call carries no cells key


def test_e_the_module_is_the_one_the_row_names_and_its_hash_travels(double, client):
    mod = REPO / "agent_fleet" / "finance_agent" / "measure_modules" / "vac.py"
    assert _ask(client).json()["method"]["module_sha256"] == hashlib.sha256(mod.read_bytes()).hexdigest()


def test_g_every_shipped_sample_measure_row_is_granted_by_seed():
    files = sorted(SAMPLE.glob("*.yaml"))
    assert {f.name for f in files} >= {"fin_tcpi.yaml", "fin_vac.yaml"}
    for f in files:
        assert yaml.safe_load(f.read_text(encoding="utf-8"))["policy"]["granted_by"] == "seed", f.name
