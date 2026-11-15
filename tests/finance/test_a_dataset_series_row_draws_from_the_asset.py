"""A dataset row drawn as MULTI_SERIES, proved over the EV fixture's 0.12.0 shape, through the REAL
engine route.

The two rows (policy/overlays/sample/measure_verbs/) read `status_period` and `eac_reported`, which
the fixture produces from dag-tools 0.12.0 (contracts/ev_fixture.yaml). They were test fixtures
until the fleet pinned 0.13.0, and ship as samples since. The frame here is the seed's frame (`frame_of`, the 0.11.0 shape)
with those two columns added as the 0.12.0 fixture carries them. The expected series are computed
HERE, with polars, from the same frame, and not through the module. Nothing says a cluster behaves
this way.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_a_dataset_series_row_draws_from_the_asset.py
"""
from __future__ import annotations

import copy
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import asset_inputs, measure_verbs, seed  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent.entities import FISCAL_PERIODS  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    _clean_env, frame_of, token,
)
from tests.finance.test_variance_decomposition_over_the_ev_fixture import Gate  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ROWS = Path(__file__).resolve().parents[2] / "policy" / "overlays" / "sample" / "measure_verbs"
CONTRACT = REPO / "contracts" / "ev_fixture.yaml"
CUM, EAC = "fin_ev_cumulative", "fin_eac_trend"
ROW_URN = "urn:li:dataset:(urn:li:dataPlatform:s3,ev_fixture,PROD)"
PROGRAM = seed.PROGRAM_ID
ALLOWED, DENIED = "alice@example.com", "mallory@example.com"
STATUS = "FY26-06"

#: `eac_reported` per work package, FY26-01..FY26-06, as dag-tools 0.12.0's fixture carries it.
EAC_REPORTED = {
    "WP-1101": [1200000] * 6,
    "WP-1102": [1200000, 1200000, 1100000, 1100000, 1000000, 1000000],
    "WP-2101": [2400000, 2400000, 2450000, 2450000, 2550000, 2550000],
    "WP-2102": [1500000] * 6,
    "WP-3101": [1800000, 1800000, 2200000, 2600000, 2900000, 2900000],
    "WP-3102": [900000] * 6,
    "WP-4101": [1500000, 1500000, 1500000, 1425000, 1425000, 1425000],
    "WP-5101": [900000, 900000, 975000, 975000, 1050000, 1050000],
    "WP-5102": [600000, 600000, 600000, 540000, 540000, 540000],
}


def frame_012():
    eac = pl.DataFrame([{"work_package": wp, "period": FISCAL_PERIODS[i], "eac_reported": v}
                        for wp, vs in EAC_REPORTED.items() for i, v in enumerate(vs)])
    return (frame_of().join(eac, on=["work_package", "period"], how="left", validate="1:1")
            .with_columns(pl.lit(STATUS).alias("status_period")))


@pytest.fixture
def series_rows(monkeypatch, tmp_path):
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    for p in ROWS.glob("*.yaml"):
        (overlay / p.name).write_bytes(p.read_bytes())
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(overlay))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    for fn in (CUM, EAC):
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + rows[fn].verb, fn)
    return rows


@pytest.fixture
def members(monkeypatch):
    held = {ALLOWED, DENIED}
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program == PROGRAM and caller_id in held)
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))


@pytest.fixture
def gate(tmp_path, series_rows, members, monkeypatch):
    path = tmp_path / "ev012.parquet"
    frame_012().write_parquet(path)
    g = Gate(pl.scan_parquet(path))
    monkeypatch.setattr(engine.asset_inputs, "_load_client", g.load)
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")   # FIN_DATASET_URN stays UNSET
    return g


@pytest.fixture
def post(gate):
    who = {"allowed": ALLOWED, "denied": DENIED}
    with TestClient(engine.app) as c:
        def call(role="allowed", params=None, fn=CUM):
            r = c.post(f"/measure/{fn}", json={"params": params or {"program_id": PROGRAM},
                                               "user_email": who[role]},
                       headers={"Authorization": f"Bearer {token(who[role])}"})
            return r.status_code, r.json()
        call.client = c
        yield call


# ── the oracle: polars sums, NOT the module ───────────────────────────────────────────────────

def per_period(frame, columns):
    """{period: {column: Decimal sum over the program's work packages}}, in calendar order."""
    f = (frame.filter(pl.col("program_id") == PROGRAM).group_by("period")
         .agg([pl.col(c).sum() for c in columns]))
    out = {r["period"]: {c: Decimal(str(r[c])) for c in columns} for r in f.iter_rows(named=True)}
    return dict(sorted(out.items(), key=lambda kv: FISCAL_PERIODS.index(kv[0])))


def exact(rows, key):
    return [Decimal(r[f"{key}_exact"]) for r in rows]


# ── green ─────────────────────────────────────────────────────────────────────────────────────

def test_the_cumulative_series_equal_an_independent_running_sum(post):
    status, env = post()
    assert status == 200, env
    sums = per_period(frame_012(), ["bcws", "bcwp", "acwp"])
    assert [r["period"] for r in env["rows"]] == list(sums) == list(FISCAL_PERIODS[:6])
    for key, col in (("pv", "bcws"), ("ev", "bcwp"), ("ac", "acwp")):
        running, want = Decimal(0), []
        for s in sums.values():
            running += s[col]
            want.append(running)
        assert exact(env["rows"], key) == want, key
    bac = Decimal(str(frame_012()["program_bac"].unique().item()))
    assert exact(env["rows"], "bac") == [bac] * 6
    assert all(isinstance(r[k], float) for r in env["rows"] for k in ("pv", "ev", "ac", "bac"))
    # the running sum is the module's: the reader handed it period amounts
    first = next(iter(sums.values()))
    assert env["rows"][1]["inputs"]["bcws"] != str(exact(env["rows"], "pv")[1])
    assert Decimal(env["rows"][0]["inputs"]["bcws"]) == first["bcws"]


def test_the_eac_trend_is_the_reported_stock_summed_over_work_packages_never_over_periods(post):
    status, env = post(fn=EAC)
    assert status == 200, env
    want = [s["eac_reported"] for s in per_period(frame_012(), ["eac_reported"]).values()]
    assert exact(env["rows"], "eac") == want
    assert want[0] != want[-1]                                   # positive control: it moves
    assert exact(env["rows"], "eac")[-1] < sum(want)             # and is not accumulated


def test_the_envelope_names_the_series_the_reference_the_status_and_the_source(post, gate, series_rows):
    _status, env = post()
    row = series_rows[CUM]
    assert env["render"]["shape"] == "MULTI_SERIES"
    assert env["series"] == [dict(s) for s in row.series]
    assert [s["key"] for s in env["series"] if s.get("cumulative")] == ["pv", "ev", "ac"]
    assert env["reference"] == {"series": "bac", "label": "BAC"}
    assert env["status_period"] == STATUS
    assert env["data_source"] == {"kind": "asset", "urn": ROW_URN}
    assert env["data_provenance"].startswith("SYNTHETIC") and ROW_URN in env["data_provenance"]
    assert env["measure"] == CUM and env["output_uri"].endswith("DeclaredMeasureSeries")
    assert env["artifact_id"].startswith(f"fin:{CUM}:")
    assert env["method"]["version"] == "1.0.0" and env["method"]["module_sha256"] == row.module_sha256
    assert env["verdict"].endswith(f"at {FISCAL_PERIODS[5]}; reported through {STATUS}")
    assert "Planned value" in env["verdict"] and "Budget at completion" in env["verdict"]
    assert set(env["rows"][0]["inputs"]) == {"bcws", "bcwp", "acwp", "bac"}
    assert gate.asked == [(ALLOWED, ROW_URN)]                     # read as the caller


def test_the_status_period_is_served_from_the_data_not_the_row(post, gate):
    gate.frame = gate.frame.with_columns(pl.lit("FY26-04").alias("status_period"))
    _status, env = post()
    assert env["status_period"] == "FY26-04" and env["verdict"].endswith("reported through FY26-04")


@pytest.mark.parametrize("fn", [CUM, EAC])
def test_the_brief_leads_with_the_rows_verdict_not_a_pointer(post, fn):
    # The census in test_every_verb_says_what_it_found cannot serve a dataset row (it needs a bearer
    # holding the asset grant), so the headline the brief reads is asserted here, where it is served.
    from agent_fleet.graph_host.graphs.fin_program_brief import _headline
    status, env = post(fn=fn)
    assert status == 200, env
    headline = _headline(env)
    assert headline == env["verdict"] and headline.strip()
    assert headline != "reported (see artifact)"


def test_the_row_urn_is_read_and_the_environments_is_never_consulted(post, gate, monkeypatch):
    monkeypatch.setenv("FIN_DATASET_URN", "urn:li:dataset:(urn:li:dataPlatform:s3,other,PROD)")
    status, env = post(fn=EAC)
    assert status == 200 and gate.asked == [(ALLOWED, ROW_URN)]


def test_a_program_the_asset_does_not_hold_is_a_422_not_a_seed_answer(post, monkeypatch):
    monkeypatch.setattr(engine, "can_view_program", lambda *a, **k: True)
    status, body = post(params={"program_id": "NP-NOBODY"})
    assert status == 422 and "not_in_model" in body["detail"]


# ── refusals at the route ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", [CUM, EAC])
def test_a_denied_caller_is_a_403_access_denied_with_no_figure(post, fn):
    status, body = post("denied", fn=fn)
    assert status == 403 and body["detail"]["status"] == "access_denied"
    assert body["detail"]["denied_assets"] == [ROW_URN]
    assert "rows" not in body and "rows" not in body["detail"]


def test_the_0_11_0_shape_is_a_502_missing_column_naming_the_new_column(post, gate):
    gate.frame = frame_of().lazy()
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "missing_column"
    assert "status_period" in body["detail"]["message"]


@pytest.mark.parametrize("fn", [CUM, EAC])
def test_a_required_column_the_row_never_names_is_still_a_502_missing_column(post, gate, fn):
    # No series row reads program_name; the contract requires it, and the read is held to the contract.
    gate.frame = gate.frame.drop("program_name")
    status, body = post(fn=fn)
    assert status == 502 and body["detail"]["rule"] == "missing_column"
    assert "program_name" in body["detail"]["message"]


def test_a_status_that_varies_within_the_program_is_a_502_naming_the_rule(post, gate):
    gate.frame = gate.frame.with_columns(
        pl.when(pl.col("work_package") == "WP-1101").then(pl.lit("FY26-05"))
        .otherwise(pl.col("status_period")).alias("status_period"))
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "not_determined_by"
    assert "status_period" in body["detail"]["message"] and "program_id" in body["detail"]["message"]
    assert "FY26-05" not in str(body)


def test_a_per_program_column_that_varies_is_a_502_naming_the_rule(post, gate):
    gate.frame = gate.frame.with_columns(
        pl.when(pl.col("work_package") == "WP-1101").then(pl.col("program_bac") + 1)
        .otherwise(pl.col("program_bac")).alias("program_bac"))
    status, body = post(fn=EAC)
    assert status == 502 and body["detail"]["rule"] == "not_determined_by"
    assert "program_bac" in body["detail"]["message"] and "program_id" in body["detail"]["message"]


@pytest.mark.parametrize("column,value", [("period", "FY27-01"), ("status_period", "2026-06")])
def test_a_period_or_status_outside_the_calendar_is_a_502(post, gate, column, value):
    gate.frame = gate.frame.with_columns(pl.lit(value).alias(column)) if column == "status_period" else \
        gate.frame.with_columns(pl.when(pl.int_range(pl.len()) == 0).then(pl.lit(value))
                                .otherwise(pl.col(column)).alias(column))
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "period_outside_calendar"
    assert value not in str(body)


def test_a_null_summed_value_is_a_502_naming_the_rule(post, gate):
    gate.frame = gate.frame.with_columns(
        pl.when(pl.col("work_package") == "WP-1101").then(None).otherwise(pl.col("bcwp")).alias("bcwp"))
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "null_value"


def test_the_window_param_is_refused_for_this_kind(post):
    status, body = post(params={"program_id": PROGRAM, "window": ["FY26-01"]})
    assert status == 400 and "window" in body["detail"]


@pytest.mark.parametrize("fn", [CUM, EAC])
def test_a_package_naming_a_series_row_asks_its_grant_and_the_builder_refuses_it_by_name(
        post, gate, series_rows, monkeypatch, tmp_path, fn):
    """As for a flow row: the page's embedded `measures.py` cannot recompute the row, so the builder
    refuses it by name with nothing written, after the row's own asset grant was asked."""
    monkeypatch.setattr(engine, "_repo_root", lambda: Path(__file__).resolve().parents[2])
    dist = tmp_path / "dist"
    monkeypatch.setattr(engine, "_dist_dir", lambda root: dist)
    monkeypatch.setattr("build_cost_package.algorithm_sha", lambda: "0" * 40)
    body = {"user_email": ALLOWED, "recipient_scope": f"program_office.{PROGRAM}",
            "canvas": {"template_id": "program_finance", "template_hash": "h",
                       "panels": [{"panel": 0, "verb": "mesh:" + series_rows[fn].verb,
                                   "params": {"program_id": PROGRAM}}]}}
    r = post.client.post("/package_export", json=body,
                         headers={"Authorization": f"Bearer {token(ALLOWED)}"})
    assert r.status_code == 503, r.text
    assert fn in r.json()["detail"] and "embedded measures.py" in r.json()["detail"]
    assert (ALLOWED, series_rows[fn].dataset_urn) in gate.asked and not dist.exists()


def test_the_verbs_register_like_any_declared_row(series_rows):
    calls = {c["verb"]: c for c in engine._registration_calls()}
    for fn in (CUM, EAC):
        c = calls["mesh:" + series_rows[fn].verb]
        assert c["fn"] == fn and c["domains"] == ["PROGRAM_FINANCE"]
        assert [s["name"] for s in c["slots"]] == ["program_id"]


# ── the runner holds the module to its declared result ────────────────────────────────────────

@pytest.mark.parametrize("body", ["return []", "return [{'eac': p['eac']} for p in periods]",
                                  "return [{'eac': 1.0, 'bac': p['bac']} for p in periods]"])
def test_a_module_returning_the_wrong_shape_is_a_defect_not_a_refusal(body, tmp_path):
    mod = tmp_path / "wrong_series_mod.py"
    mod.write_text('VERSION = "1.0.0"\nREADS = {"eac_trend": frozenset({"eac", "bac"})}\n'
                   'SERIES = {"eac_trend": ("eac", "bac")}\n\n'
                   f'def eac_trend(*, periods):\n    {body}\n', encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        raw = mutated(EAC, lambda r: r["computation"].update(module="wrong_series_mod"))
        (row,) = load(raw, tmp_path)
        read = asset_inputs.SeriesRead(periods=[("FY26-01", {"eac_reported": Decimal(1)})],
                                       constants={"program_bac": Decimal(2)}, status=STATUS)
        with pytest.raises(RuntimeError, match="fin_eac_trend"):
            measure_verbs.run_dataset_series(read, row)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("wrong_series_mod", None)


# ── the loader ────────────────────────────────────────────────────────────────────────────────

def raw_of(fn):
    return yaml.safe_load((ROWS / f"{fn}.yaml").read_text(encoding="utf-8"))


def mutated(fn, edit):
    raw = copy.deepcopy(raw_of(fn))
    edit(raw)
    return raw


def load(raw, tmp_path):
    seed_dir, ov = tmp_path / "seed", tmp_path / "ov"
    seed_dir.mkdir(exist_ok=True)
    ov.mkdir(exist_ok=True)
    (ov / "row.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return measure_verbs.load_measure_verbs(seed_dir, [ov], builtins=((), ()))


def test_both_rows_load_with_their_fields(tmp_path):
    for fn in (CUM, EAC):
        (row,) = load(raw_of(fn), tmp_path)
        assert row.kind == measure_verbs.KIND_DATASET and row.dataset_urn == ROW_URN
        assert (row.scope_column, row.period_column, row.status_column) == ("program_id", "period", "status_period")
        assert row.reference == {"series": "bac", "label": "BAC"}


def _ds(r):
    return r["inputs"]["dataset"]


REFUSED = {
    "reads_more_than_the_row_names": (CUM, lambda r: _ds(r)["per_program"].clear(), "must be the same set"),
    "returns_other_than_the_series": (EAC, lambda r: (r["render"]["series"].pop(), r["render"].pop("target")),
                                      "must be the same set"),
    "target_names_an_undeclared_series": (EAC, lambda r: r["render"]["target"].update(series="pv"),
                                          "not a declared series key"),
    "target_is_not_the_sdk_shape": (EAC, lambda r: r["render"]["target"].update(value=1.0),
                                    "MeasureSeriesReference"),
    "series_is_not_the_sdk_shape": (CUM, lambda r: r["render"]["series"][0].update(colour="red"),
                                    "MeasureSeries shape"),
    "series_mix_units": (CUM, lambda r: r["render"]["series"][3].pop("unit"), "mixes units"),
    "series_repeat_a_key": (EAC, lambda r: r["render"]["series"][1].update(key="eac"), "repeats a key"),
    "other_threshold": (CUM, lambda r: r["inputs"].update(other_threshold="0.1"), "collapses nothing"),
    "flow_keys_in_the_dataset": (CUM, lambda r: _ds(r).update(levels=["program_id"]), "per_program only"),
    "no_per_period": (EAC, lambda r: _ds(r).pop("per_period"), "at least one entry"),
    "period_as_a_keyword": (EAC, lambda r: _ds(r)["per_period"].update(period="bcws"), "other than 'period'"),
    "keyword_in_both_maps": (EAC, lambda r: _ds(r)["per_period"].update(bac="bac"), "in both"),
    "column_named_twice": (EAC, lambda r: _ds(r).update(status="period"), "named twice"),
    "no_scope": (EAC, lambda r: _ds(r).pop("scope"), "inputs.dataset.scope"),
    "no_series": (EAC, lambda r: r["render"].pop("series"), "render.series"),
    # The contract the row is read under, and the row's columns held to it (ruled 2026-11-10).
    "no_contract": (EAC, lambda r: _ds(r).pop("contract"), "inputs.dataset.contract is required"),
    "unknown_contract": (EAC, lambda r: _ds(r).update(contract="no_such_contract"), "has no file"),
    "per_period_undeclared": (EAC, lambda r: _ds(r)["per_period"].update(eac="eac_typo"), "does not declare"),
    "per_period_a_string": (EAC, lambda r: _ds(r)["per_period"].update(eac="program_name"), "in a role"),
    "period_a_number": (EAC, lambda r: _ds(r).update(period="bcws"), "in a role"),
    "scope_not_the_contracts": (EAC, lambda r: _ds(r).update(scope="work_package"), "scopes a read by"),
    "per_program_not_determined": (EAC, lambda r: _ds(r)["per_program"].update(bac="bac"),
                                   "declares no dependency"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_each_invalid_series_row_is_refused(case, tmp_path):
    fn, edit, match = REFUSED[case]
    with pytest.raises(measure_verbs.MeasureVerbError, match=match):
        load(mutated(fn, edit), tmp_path)


def test_a_state_row_naming_a_reference_series_is_refused(tmp_path):
    raw = yaml.safe_load((REPO / "policy" / "overlays" / "sample" / "measure_verbs" / "fin_tcpi.yaml")
                         .read_text(encoding="utf-8"))
    raw["render"]["target"] = {"series": "tcpi", "label": "itself"}
    with pytest.raises(measure_verbs.MeasureVerbError, match="its reference is a value"):
        load(raw, tmp_path)


def test_a_module_without_reads_and_series_is_refused(tmp_path):
    mod = tmp_path / "bare_series_mod.py"
    mod.write_text('VERSION = "1.0.0"\n\ndef eac_trend(*, periods):\n    return []\n', encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        with pytest.raises(measure_verbs.MeasureVerbError, match=r"must declare READS"):
            load(mutated(EAC, lambda r: r["computation"].update(module="bare_series_mod")), tmp_path)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("bare_series_mod", None)


def test_a_flow_function_wired_to_a_series_row_is_refused(tmp_path):
    raw = mutated(EAC, lambda r: r["computation"].update(
        module="agent_fleet.finance_agent.measure_modules.variance_decomposition", function="flow_edges",
        version="1.3.0"))
    with pytest.raises(measure_verbs.MeasureVerbError, match="exactly"):
        load(raw, tmp_path)


# ── the rows are coded to the contract ────────────────────────────────────────────────────────

def test_each_row_reads_columns_the_contract_says_reduce_the_way_the_row_reduces_them():
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    cols = {c["name"]: c for c in contract["columns"]}
    for fn in (CUM, EAC):
        ds = _ds(raw_of(fn))
        assert (ds["urn"], ds["banner"]) == (contract["dataset"]["urn"], contract["dataset"]["banner"])
        assert ds["scope"] == contract["scope"] and ds["period"] == contract["period"]["column"]
        assert ds["status"] == contract["status_period"]
        for col in ds["per_period"].values():          # summed over a program's rows at one period
            assert "work_package" in cols[col].get("additive_over", ()), (fn, col)
        by_program = {c for d in contract["dependencies"] if d["by"] == "program_id" for c in d["determines"]}
        for col in [*ds["per_program"].values(), ds["status"]]:   # one value across the program
            assert col in by_program, (fn, col)
        named = [ds["status"], *ds["per_period"].values(), *ds["per_program"].values()]
        since = {cols[c]["produced_since"] for c in named}
        assert max(since, key=lambda v: tuple(map(int, v.split(".")))) == "0.12.0", (fn, since)
