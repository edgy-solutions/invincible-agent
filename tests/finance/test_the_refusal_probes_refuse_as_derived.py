"""The sandbox's refusal probes over dag-tools' planted-refusal assets, through the REAL engine route:
every planted case answers as derived here, offline.

The probes are the rows in policy/overlays/sandbox/measure_verbs/, which only values-sandbox.yaml
names. Each reads one of dag-tools 0.13.0's `mesh_demo_refusal` assets. The frames are built the way
`demo_ev_refusal._rows_for` materialises them: the installed CSV, typed by `mesh_demo_assets`' column
declarations; the missing-column asset drops its planted column, and the wrong-type asset leaves its
planted column to inference. The module cannot be imported here (it needs pandas, which the fleet
venv does not carry), so its constants and its case manifest are read from its source. A case
dag-tools adds that `EXPECTED` does not name is a red.

Four planted cases answer 200 on every probe today. Each is owed a refusal declared in the dataset
contract (ruled 2026-11-10), so each (case, probe) holds `OWED` and is a strict xfail asserting the
refusal, never a pass. The PR that declares a refusal names its rule here and the xfail goes:
* `wrong_type`: a dataset reader casts its level and scope columns to String, so `control_account`
  arriving as Float64 is read. Only the built-ins' schema check over `FIN_DATASET_URN` refuses it.
* `duplicate_work_package_period`: one work package appears twice at one period, and no reader
  checks a key, so the row is summed twice.
* `program_name_not_unique`, `work_package_in_two_accounts`: one program carries two names, and one
  work package sits under two control accounts. Neither repeats a row; no reader reads the column
  that varies.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_refusal_probes_refuse_as_derived.py
"""
from __future__ import annotations

import ast
import importlib.resources
from pathlib import Path

import pytest
import yaml

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    MeshUnavailable, NotEntitled, _clean_env, ticketed, token,
)

REPO = Path(__file__).resolve().parents[2]
PROBES = REPO / "policy" / "overlays" / "sandbox" / "measure_verbs"
DEMO = importlib.resources.files("dag_tools") / "user_deployment"
CSV = DEMO / "demo_data" / "ev_refusal_fixture.csv"
SERIES, PATH = "fin_probe_refusal_series", "fin_probe_refusal_path"
MISSING, WRONG = "fin_probe_missing_column", "fin_probe_wrong_type"

#: The refusal a gap case is owed and does not get yet. Its rule is named by the PR that declares it.
OWED = "owed"

#: dag-tools rule -> {probe: the reader rule its 502 names, None for a 200, or OWED}. `none` is the
#: control scope. Derived offline over the reader (asset_inputs), then held here at the route.
EXPECTED = {
    "none": {SERIES: None, PATH: None},
    "null_value": {SERIES: "null_value", PATH: None},
    "non_finite": {SERIES: "non_finite", PATH: None},
    "period_outside_calendar": {SERIES: "period_outside_calendar", PATH: None},
    "program_bac_not_unique": {SERIES: "varies_within_scope", PATH: None},
    "varies_within_path": {SERIES: None, PATH: "varies_within_path"},
    "program_name_not_unique": {SERIES: OWED, PATH: OWED},
    "work_package_in_two_accounts": {SERIES: OWED, PATH: OWED},
    "duplicate_work_package_period": {SERIES: OWED, PATH: OWED},
    "missing_column": {MISSING: "missing_column"},
    "wrong_type": {WRONG: OWED},
}
#: Planted cases no probe refuses today, and why. Each is owed a dataset-contract refusal.
UNREFUSED = {
    "wrong_type": "dataset readers cast level and scope columns to String",
    "duplicate_work_package_period": "no reader checks a key, so the duplicated row is summed twice",
    "program_name_not_unique": "no reader reads program_name, so its second value is never seen",
    "work_package_in_two_accounts": "no reader reads control_account, so its second value is never seen",
}


def cells():
    """Every (case, probe) as a pytest param; an OWED one is a strict xfail on the refusal assertion
    only, so any other failure (a crash, an unexpected status) stays red."""
    return [pytest.param(rule, fn, reader_rule, id=f"{rule}-{fn}", marks=[pytest.mark.xfail(
                strict=True, raises=AssertionError, reason=f"owed a contract refusal: {UNREFUSED.get(rule, 'UNRECORDED')}")]
                if reader_rule is OWED else [])
            for rule, by_probe in EXPECTED.items() for fn, reader_rule in by_probe.items()]


def owed_answered(status, body):
    """Fails hard (not an AssertionError) unless an OWED cell answers 200 as today or the refusal."""
    if status not in (200, 502):
        pytest.fail(f"an owed case answered {status}: {body}")
    return status == 502 and body["detail"].get("error") == "asset_contract_violation" \
        and bool(body["detail"].get("rule"))
#: Cases a scoped read cannot address: dag-tools plants them with no scope.
UNADDRESSED = {"other_program_rows"}


def _module(name):
    return ast.parse((DEMO / f"{name}.py").read_text(encoding="utf-8"))


def _constants(tree):
    out = {}
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
        if isinstance(target, ast.Name) and getattr(node, "value", None) is not None:
            try:
                out[target.id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def scope_of(rule):
    """`demo_ev_refusal.refusal_scope`, held to the CSV by the manifest test below."""
    return "NP-PLANT-" + rule.upper().replace("_", "-")


REFUSAL = _module("demo_ev_refusal")
K = _constants(REFUSAL)
COLUMNS = _constants(_module("mesh_demo_assets"))


def _cases():
    """(rule, asset, scope or None) for each `RefusalCase` in dag-tools' manifest."""
    node = next(n for n in REFUSAL.body if isinstance(n, (ast.Assign, ast.AnnAssign))
                and "REFUSAL_CASES" in ast.unparse(n.targets[0] if isinstance(n, ast.Assign) else n.target))
    out = []
    for call in node.value.elts:
        kw = {k.arg: k.value for k in call.keywords}
        scope = kw["scope"]
        out.append((ast.literal_eval(kw["rule"]), K[kw["asset"].id],
                    None if isinstance(scope, ast.Constant) else scope_of(ast.literal_eval(scope.args[0]))))
    return out


CASES = _cases()


def _frame(asset):
    types = {**{c: pl.String for c in COLUMNS["EV_FIXTURE_STRING_COLUMNS"]},
             **{c: pl.Int64 for c in COLUMNS["EV_FIXTURE_INTEGER_COLUMNS"]},
             **{c: pl.Float64 for c in COLUMNS["EV_FIXTURE_FLOAT_COLUMNS"]}}
    if asset == K["WRONG_TYPE_ASSET"]:
        types.pop(K["WRONG_TYPE_PLANTED"])
    scopes = {s for _, a, s in CASES if a == asset and s} | (
        {scope_of("none")} if asset == K["ROW_LEVEL_ASSET"] else set())
    frame = pl.read_csv(CSV, schema_overrides=types).filter(pl.col(K["SCOPE_COLUMN"]).is_in(sorted(scopes)))
    return frame.drop(K["MISSING_COLUMN_PLANTED"]) if asset == K["MISSING_COLUMN_ASSET"] else frame


def _asset_of(urn):
    return urn.split(",")[1]


@pytest.fixture
def probes(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(PROBES))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    for fn, row in rows.items():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + row.verb, fn)
    return rows


def _policy(name):
    return yaml.safe_load((REPO / "policy" / name).read_text(encoding="utf-8"))


def _grants():
    return {(g["subject"], g["asset"]) for g in _policy("asset_grants.yaml")["grants"]}


def _members():
    return {p: set(v["grant_to"]) for p, v in _policy("program_members.yaml")["programs"].items()}


def _callers(probes):
    """(allowed, denied), DERIVED from the sandbox's policy copies: the subject granted every probe's
    asset, and a member of the control program who holds none of them."""
    urns = {r.dataset_urn for r in probes.values()}
    grants, members = _grants(), _members()
    allowed = {s for s, _ in grants if all((s, u) in grants for u in urns)}
    denied = {m for m in members.get(scope_of("none"), ()) if not any((m, u) in grants for u in urns)}
    assert len(allowed) == 1 and len(denied) == 1, (allowed, denied)
    return allowed.pop(), denied.pop()


@pytest.fixture
def post(probes, monkeypatch):
    allowed, denied = _callers(probes)
    members = _members()
    frames = {r.dataset_urn: _frame(_asset_of(r.dataset_urn)).lazy() for r in probes.values()}
    asked = []

    class Client:
        def __init__(self, **kw):
            self.who = kw["originator_email"]

        def get_dataframe_with_ticket(self, urn):
            asked.append((self.who, urn))
            if urn not in frames or (self.who, urn) not in _grants():
                raise NotEntitled("refused")
            return ticketed(frames[urn], urn, len(asked))

    monkeypatch.setattr(engine.asset_inputs, "_load_client", lambda: (Client, NotEntitled, MeshUnavailable))
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: caller_id in members.get(program, ()))
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")   # FIN_DATASET_URN stays UNSET
    who = {"allowed": allowed, "denied": denied}
    with TestClient(engine.app) as c:
        def call(fn, program, role="allowed"):
            r = c.post(f"/measure/{fn}", json={"params": {"program_id": program}, "user_email": who[role]},
                       headers={"Authorization": f"Bearer {token(who[role])}"})
            return r.status_code, r.json()
        call.asked = asked
        yield call


# ── the table is dag-tools' manifest, and the probes read its assets ─────────────────────────

def test_the_manifest_is_the_tables_and_the_csv_holds_its_scopes():
    rules = {rule for rule, _, _ in CASES}
    assert rules | {"none"} == set(EXPECTED) | UNADDRESSED, rules
    assert {rule for rule, _, scope in CASES if scope is None} == UNADDRESSED
    # The control on `scope_of` and on the manifest read: the CSV holds exactly these scopes.
    csv = set(pl.read_csv(CSV, infer_schema=False)[K["SCOPE_COLUMN"]])
    assert csv == {s for _, _, s in CASES if s} | {scope_of("none")}, csv


def test_every_probe_reads_a_planted_asset_and_every_case_is_reached(probes):
    assert {_asset_of(r.dataset_urn) for r in probes.values()} == {
        K["ROW_LEVEL_ASSET"], K["MISSING_COLUMN_ASSET"], K["WRONG_TYPE_ASSET"]}
    asset_of_case = {rule: asset for rule, asset, _ in CASES} | {"none": K["ROW_LEVEL_ASSET"]}
    for rule, by_probe in EXPECTED.items():
        assert set(by_probe) == {fn for fn, r in probes.items()
                                 if _asset_of(r.dataset_urn) == asset_of_case[rule]}, rule


def test_the_owed_cases_are_exactly_the_recorded_gaps():
    owed = {rule for rule, by_probe in EXPECTED.items() if OWED in by_probe.values()}
    assert owed == set(UNREFUSED), owed
    assert all(set(EXPECTED[rule].values()) == {OWED} for rule in UNREFUSED)
    # No planted case other than the control may answer 200 on every probe and go unrecorded.
    silent = {rule for rule, by_probe in EXPECTED.items()
              if rule != "none" and all(v is None for v in by_probe.values())}
    assert silent == set(), silent


def test_the_probes_are_policed_like_any_row_and_reach_no_menu(probes):
    for fn, row in probes.items():
        assert row.kind == "dataset" and row.cells == ("PROGRAM_FINANCE",) and row.menu is None, fn
        assert row.granted_by == "seed" and row.banner.startswith("SYNTHETIC"), fn


# ── every planted case through the real route ─────────────────────────────────────────────────

@pytest.mark.parametrize("rule,fn,reader_rule", cells())
def test_each_planted_case_answers_as_derived(post, rule, fn, reader_rule):
    status, body = post(fn, scope_of(rule))
    if reader_rule is OWED:
        assert owed_answered(status, body), (rule, fn, "answered 200: the refusal is owed")
    elif reader_rule is None:
        assert status == 200, (rule, fn, body)
    else:
        assert status == 502 and body["detail"]["rule"] == reader_rule, (rule, fn, body)


def test_the_control_caller_is_refused_the_asset_and_sees_no_figure(post, probes):
    status, body = post(SERIES, scope_of("none"), role="denied")
    assert status == 403 and body["detail"]["status"] == "access_denied"
    assert body["detail"]["denied_assets"] == [probes[SERIES].dataset_urn]
    assert "rows" not in body and "rows" not in body["detail"]
