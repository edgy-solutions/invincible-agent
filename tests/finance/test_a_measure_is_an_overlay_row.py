"""A measure is an overlay row: TCPI, declared in YAML, registered, asked and gated end to end.

Proposal `docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md`, Part 1.
The platform seeds no measure verb; a deployment declares one in an overlay
(`MEASURE_VERB_OVERLAY_DIRS`) and the engine registers it, serves it at `/measure/{measure_id}`
behind the same program-visibility gate as the built-ins (#130), and carries the method beside
every figure. The sample row lives in `policy/overlays/sample/measure_verbs/`.

Arms: 1 transcription seal, 2 refusals (one each), 3 composition, 4 registration, 5 the answer,
6 the gate. (The canvas arms are in `tests/planning/test_canvas_templates_have_an_overlay_layer.py`
and the contract seals that iterate `VERBS` extend to declared verbs in their own files.)

Run: uv run --no-sync pytest tests/finance/test_a_measure_is_an_overlay_row.py -q
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import measure_verbs, measures, seed  # noqa: E402
from agent_fleet.finance_agent.entities import periods_in  # noqa: E402
from agent_fleet.finance_agent.measure_modules import tcpi  # noqa: E402
from tests.finance.test_the_method_registry_rows import _evaluate  # noqa: E402

SAMPLE = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
SAMPLE_ROW = SAMPLE / "fin_tcpi.yaml"
PROGRAM = seed.PROGRAM_ID
ALICE, BOB, SVC = "alice@example.com", "bob@example.com", "svc:supervisor"
BUILTINS = (measures.OUTPUT_URI, [v["verb"].split(":", 1)[-1] for v in engine.VERBS])
ENVELOPE = {
    "error": "program_not_visible",
    "refusal": {"policy_id": "program_members",
                "missing_binding": "can_view_program(program)", "candidates": []},
    "message": "You are not a member of the program this request names.",
}


def _load(overlay_dirs, seed_dir=None, tmp=None):
    return measure_verbs.load_measure_verbs(
        policy_dir=seed_dir if seed_dir is not None else (tmp or Path("."))/"no-seed",
        overlay_dirs=list(overlay_dirs), builtins=BUILTINS)


# ── arm 1: the transcription, run ────────────────────────────────────────────────────────────

TRIPLES = [  # (bac, bcwp, acwp)
    (Decimal("1000"), Decimal("400"), Decimal("500")),    # CPI 0.8  -> TCPI > 1
    (Decimal("1000"), Decimal("500"), Decimal("400")),    # CPI 1.25 -> TCPI < 1
    (Decimal("2500.5"), Decimal("1250.25"), Decimal("1250.25")),   # CPI 1
    (Decimal("1000"), Decimal("999"), Decimal("1")),
]


def _sample_row():
    return _load([SAMPLE])[0]


@pytest.mark.parametrize("bac,bcwp,acwp", TRIPLES)
def test_1_the_module_computes_what_the_row_transcribes(bac, bcwp, acwp):
    row = _sample_row()
    lhs, _, rhs = row.transcription.partition("=")
    assert lhs.strip() == "TCPI"
    expected = _evaluate("EAC = " + rhs, {"BAC": bac, "BCWP": bcwp, "ACWP": acwp})
    assert tcpi.tcpi_bac(bac=bac, bcwp=bcwp, acwp=acwp) == expected


@pytest.mark.parametrize("bac,acwp", [(Decimal("1000"), Decimal("1000")),
                                      (Decimal("1000"), Decimal("1200")),
                                      (Decimal("0"), Decimal("0"))])
def test_1_undefined_exactly_when_bac_is_not_above_acwp(bac, acwp):
    assert tcpi.tcpi_bac(bac=bac, bcwp=Decimal("10"), acwp=acwp) is None
    # the control: one unit under the budget is defined
    assert tcpi.tcpi_bac(bac=acwp + 1, bcwp=Decimal("10"), acwp=acwp) is not None


# ── arm 2: refusals, one each, each naming the file and the reason ───────────────────────────

def _write(tmp_path, mutate, name="bad.yaml"):
    raw = yaml.safe_load(SAMPLE_ROW.read_text(encoding="utf-8"))
    mutate(raw)
    d = tmp_path / "ov"
    d.mkdir(exist_ok=True)
    (d / name).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return d


def _refused(tmp_path, mutate, *fragments):
    d = _write(tmp_path, mutate)
    with pytest.raises(measure_verbs.MeasureVerbError) as ei:
        _load([d], tmp=tmp_path)
    msg = str(ei.value)
    assert "bad.yaml" in msg, f"the refusal does not name the file: {msg}"
    for f in fragments:
        assert f in msg, f"expected {f!r} in: {msg}"


def test_2_formula_under_inputs(tmp_path):
    _refused(tmp_path, lambda r: r["inputs"].update(formula="bac - acwp"), "formula")


def test_2_state_name_outside_the_vocabulary(tmp_path):
    _refused(tmp_path, lambda r: r["inputs"]["state"].update(bac="program.secret"),
             "closed vocabulary", "program.secret")


def test_2_a_builtin_function_name_as_measure_id(tmp_path):
    _refused(tmp_path, lambda r: r.update(measure_id="fin_performance_indices"),
             "built-in finance verb")


def test_2_version_mismatch(tmp_path):
    _refused(tmp_path, lambda r: r["computation"].update(version="9.9.9"), "9.9.9", "1.0.0")


def test_2_kw_params_differ_from_state_keys(tmp_path):
    _refused(tmp_path, lambda r: r["inputs"]["state"].update(extra="period.acwp"),
             "must be the same set")


def test_2_an_impure_module(tmp_path, monkeypatch):
    pkg = tmp_path / "pkgs"
    pkg.mkdir()
    (pkg / "tmp_impure_measure.py").write_text(
        'import os\nVERSION = "1.0.0"\n\n'
        "def tcpi_bac(*, bac, bcwp, acwp):\n    return None\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(pkg))
    importlib.invalidate_caches()
    try:
        _refused(tmp_path,
                 lambda r: r["computation"].update(module="tmp_impure_measure"),
                 "imports", "os")
    finally:
        sys.modules.pop("tmp_impure_measure", None)


def test_2_a_top_level_formula_is_refused_not_ignored(tmp_path):
    # Spec F: `_build` read named keys only, so a top-level `formula` loaded and did nothing.
    _refused(tmp_path, lambda r: r.update(formula="BAC - EV"), "formula", "cannot carry a formula")


def test_2_the_control_for_the_top_level_formula_differs_only_by_that_key(tmp_path):
    d = _write(tmp_path, lambda r: None, name="good.yaml")
    assert [r.measure_id for r in _load([d], tmp=tmp_path)] == ["fin_tcpi"]
    (tmp_path / "x").mkdir()
    bad = _write(tmp_path / "x", lambda r: r.update(formula="BAC - EV"))
    with pytest.raises(measure_verbs.MeasureVerbError):
        _load([bad], tmp=tmp_path)


def test_2_policy_visibility(tmp_path):
    _refused(tmp_path, lambda r: r["policy"].update(visibility="public"), "visibility")


def test_2_mixed_units(tmp_path):
    _refused(tmp_path, lambda r: r["outputs"].update(
        series=[{"key": "a", "label": "A", "unit": "USD"}, {"key": "b", "label": "B"}]),
        "mixes units")


def test_2_bad_status(tmp_path):
    _refused(tmp_path, lambda r: r["policy"].update(status="final"), "policy.status")


def test_2_the_control_the_unmutated_row_loads(tmp_path):
    d = _write(tmp_path, lambda r: None, name="good.yaml")
    assert [r.measure_id for r in _load([d], tmp=tmp_path)] == ["fin_tcpi"]


# ── arm 3: composition ───────────────────────────────────────────────────────────────────────

def test_3_no_overlay_declares_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("MEASURE_VERB_OVERLAY_DIRS", raising=False)
    assert engine._load_declared() == {}
    assert _load([], tmp=tmp_path) == []


def test_3_the_sample_overlay_declares_exactly_fin_tcpi_and_fin_vac_cpi(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(SAMPLE))
    assert sorted(engine._load_declared()) == ["fin_tcpi", "fin_vac_cpi"]


def test_3_a_tombstone_in_a_later_overlay_removes_it(tmp_path):
    second = tmp_path / "second"
    second.mkdir()
    (second / "fin_tcpi.yaml").write_text("measure_id: fin_tcpi\ndeleted: true\n", encoding="utf-8")
    assert sorted(r.measure_id for r in _load([SAMPLE], tmp=tmp_path)) == ["fin_tcpi", "fin_vac_cpi"]
    assert [r.measure_id for r in _load([SAMPLE, second], tmp=tmp_path)] == ["fin_vac_cpi"]


# ── arm 4: registration ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def declared(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(SAMPLE))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    monkeypatch.setitem(engine.VERB_TO_FN, "mesh:finToCompletePerformanceIndex", "fin_tcpi")
    return rows


def test_4_registers_beside_the_builtins(declared, monkeypatch):
    row = declared["fin_tcpi"]
    calls = engine._registration_calls("http://engine")
    by_verb = {c["verb"]: c for c in calls}
    monkeypatch.setattr(engine, "DECLARED", {})
    n_builtin = len(engine._registration_calls("http://engine"))
    monkeypatch.setattr(engine, "DECLARED", declared)
    assert len(calls) == n_builtin + 2   # the sample ships fin_tcpi and fin_vac_cpi
    c = by_verb["mesh:finToCompletePerformanceIndex"]
    assert c["endpoint_url"] == "http://engine/measure/fin_tcpi"
    assert c["output_uri"] == measures.FIN + "ToCompletePerformanceIndexSeries"
    assert list(c["verb_synonyms"]) == list(row.synonyms)
    assert row.synonyms, "the sample row carries no synonyms"
    twin = by_verb["mesh:finPerformanceIndices"]
    keep = {"program_id", "window"}
    assert [s for s in c["slots"]] == [s for s in twin["slots"] if s["name"] in keep]
    assert {s["name"] for s in c["slots"]} == keep


def test_4_nothing_declared_registers_only_the_builtins(monkeypatch):
    monkeypatch.setattr(engine, "DECLARED", {})
    verbs = {c["verb"] for c in engine._registration_calls("http://engine")}
    assert verbs == {v["verb"] for v in engine.VERBS}
    assert "mesh:finToCompletePerformanceIndex" not in verbs


# ── arms 5 and 6: the answer and the gate ────────────────────────────────────────────────────

class Double:
    def __init__(self):
        self.calls = []

    def __call__(self, program, caller_id, **kw):
        self.calls.append((program, caller_id))
        return (program, caller_id) in {(PROGRAM, ALICE), (PROGRAM, SVC)}


@pytest.fixture
def double(monkeypatch):
    d = Double()
    monkeypatch.setattr(engine, "can_view_program", d)
    return d


@pytest.fixture
def client(declared):
    with TestClient(engine.app) as c:
        yield c


def _ask(client, user=ALICE, params=None):
    body = {"params": params if params is not None else {"program_id": PROGRAM}}
    if user is not None:
        body["user_email"] = user
    return client.post("/measure/fin_tcpi", json=body)


def _expected_rows(state):
    program = next(p for p in state.programs if p.program_id == PROGRAM)
    ca = {c.ca_id for c in state.accounts_of(PROGRAM)}
    wps = {w.wp_id for w in state.work_packages if w.ca_id in ca}
    out, cum = [], [Decimal(0)] * 3
    for period in periods_in(None):
        t = measures._totals_exact(state, wps, [period])
        if t == (0, 0, 0):
            continue
        cum = [cum[i] + t[i] for i in range(3)]
        out.append((period, tcpi.tcpi_bac(bac=Decimal(str(program.bac)),
                                          bcwp=cum[1], acwp=cum[2])))
    return out


def test_5_one_row_per_period_each_equal_to_the_independent_computation(double, client):
    r = _ask(client)
    assert r.status_code == 200, r.text
    body = r.json()
    expected = _expected_rows(engine.STATE)
    assert len(expected) >= 2
    assert [x["period"] for x in body["rows"]] == [p for p, _ in expected]
    for got, (period, want) in zip(body["rows"], expected):
        assert want is not None, "the seed itself spends its budget; use the fixture arm"
        assert Decimal(got["tcpi_exact"]) == want, period
        assert got["tcpi"] == pytest.approx(float(want)), period
        assert "undefined" not in got
    row = engine.DECLARED["fin_tcpi"]
    assert body["method"] == {
        "measure_id": "fin_tcpi", "name": row.name, "version": "1.0.0",
        "module_sha256": hashlib.sha256(
            (REPO / "agent_fleet" / "finance_agent" / "measure_modules" / "tcpi.py").read_bytes()
        ).hexdigest()}
    assert body["series"] == [dict(s) for s in row.series]
    assert body["reference"] == dict(row.reference)
    assert body["output_uri"] == measures.FIN + "ToCompletePerformanceIndexSeries"


def test_5_the_envelope_is_the_builtins_plus_method(double, client):
    builtin = client.post("/measure/fin_performance_indices",
                          json={"params": {"program_id": PROGRAM}, "user_email": ALICE})
    assert builtin.status_code == 200, builtin.text
    declared_keys = set(_ask(client).json())
    assert declared_keys == set(builtin.json()) | {"method"}


def test_5_a_budget_already_spent_is_undefined_with_its_reason(double, client, monkeypatch):
    state = copy.deepcopy(engine.STATE)
    program = next(p for p in state.programs if p.program_id == PROGRAM)
    ca = {c.ca_id for c in state.accounts_of(PROGRAM)}
    wps = {w.wp_id for w in state.work_packages if w.ca_id in ca}
    state.facts = [replace(f, acwp=f.acwp + 10 * program.bac) if f.wp_id in wps else f
                   for f in state.facts]
    monkeypatch.setattr(engine, "STATE", state)
    body = _ask(client).json()
    assert body["rows"], "no periods"
    for row in body["rows"]:
        assert row["undefined"] == "budget_spent"
        assert row["tcpi"] is None
        assert row.get("tcpi_exact") is None


def test_5_unknown_params_are_a_400_and_a_missing_program_a_422(double, client):
    assert _ask(client, params={"program_id": PROGRAM, "method": "CPI"}).status_code == 400
    r = _ask(client, params={"window": ["FY26-01"]})
    assert r.status_code in (403, 422)


def test_6_a_non_member_is_refused_byte_equal_with_nothing_computed(double, client, monkeypatch):
    ran = []
    real = engine._declared_envelope
    monkeypatch.setattr(engine, "_declared_envelope",
                        lambda *a, **k: ran.append(a) or real(*a, **k))
    builtin = client.post("/measure/fin_burn_rate",
                          json={"params": {"program_id": PROGRAM}, "user_email": BOB})
    r = _ask(client, user=BOB)
    assert r.status_code == 403
    assert r.json()["detail"] == ENVELOPE
    assert r.content == builtin.content, "the declared refusal differs from the built-in's"
    assert ran == []
    assert _ask(client, user=ALICE).status_code == 200  # control
    assert len(ran) == 1


def test_6_a_service_caller_is_refused_without_a_topaz_call(double, client):
    n = len(double.calls)
    r = _ask(client, user=SVC)
    assert r.status_code == 403 and r.json()["detail"] == ENVELOPE
    assert len(double.calls) == n, "a service caller reached the membership check"
    r = _ask(client, user=None)
    assert r.status_code == 403 and r.json()["detail"] == ENVELOPE


def test_6_an_undeclared_measure_stays_a_404(double, client):
    r = client.post("/measure/fin_nonesuch", json={"params": {"program_id": PROGRAM},
                                                   "user_email": ALICE})
    assert r.status_code == 404
