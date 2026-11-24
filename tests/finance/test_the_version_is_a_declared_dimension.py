"""A version is a declared dimension, and a flow row compares two of them.

Ruled 2026-11-23 (architect), step 2. The contract names a version column and its values
(`version_dimension: {column, values}`); a flow row says `value: {compare: {column: <amount>, by: <version
column>}}`; the person chooses the two versions as slots; a value outside the declared list is
refused. The paths are summed per version, joined on the full path and subtracted, a path in one
version only counting as zero on the other side. "Version and period are not searched in the data.
They resolve against the declared version list and the declared calendar."

CONTROL. Synthetic program B (tests/fixtures/fin_program_b): a six-level breakdown (program, four
WBS levels, control account), three versions, a 4-4-5 calendar. The sample-shaped control is the
EV fixture's levels plus a version column, built here. Both are served by ONE loaded engine.

The expected edges are computed HERE, from the dict that built the frame, and never through the
reader or the module.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_version_is_a_declared_dimension.py
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
from agent_fleet.finance_agent.slots import slots_for  # noqa: E402
from agent_fleet.utils import dataset_contracts  # noqa: E402
from tests.finance.test_a_dataset_series_row_draws_from_the_asset import CONTRACT as EV_CONTRACT  # noqa: E402
from tests.finance.test_a_dataset_series_row_draws_from_the_asset import CUM, ROWS  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    MeshUnavailable, NotEntitled, _clean_env, frame_of, ticketed, token,
)
from tests.finance.test_variance_decomposition_over_the_ev_fixture import ALLOWED, DENIED, PROGRAM  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
B_DIR = REPO / "tests" / "fixtures" / "fin_program_b"
B_CONTRACT = B_DIR / "contracts" / "program_b_versions.yaml"
SAMPLE_CAL = REPO / "policy" / "overlays" / "sample" / "fin_calendar"
PROG_B = "PRG-B"
URN_B = "urn:li:dataset:(urn:li:dataPlatform:s3,program_b_versions,PROD)"
URN_EV = "urn:li:dataset:(urn:li:dataPlatform:s3,ev_fixture,PROD)"
FN_B, FN_FILTER, FN_EV = "fin_flow_b_compare", "fin_flow_b_version", "fin_flow_ev_compare"
B_LEVELS = ["program_id", "wbs_2", "wbs_3", "wbs_4", "wbs_5", "control_account"]
SIGN = {"positive": 1, "negative": -1, "zero": 0}
PMB, CTR, GOV = "PMB", "EAC-CTR", "EAC-GOV"

# path (wbs_2, wbs_3, wbs_4, wbs_5, control_account) -> version -> the amounts of that (path, version)'s
# rows, one per period. Several rows per (path, version), so that `sum` matters. EAC-GOV less PMB:
#   CA-01 +39.75   CA-02 0 (a zero)   CA-03 -50   CA-04 +10   CA-05 -50   CA-06 +10   CA-07 -99.5
#   CA-08 0 (a zero)   CA-09 +33 (only in EAC-GOV)   CA-10 -75 (only in PMB)
PLAN = {
    ("1", "1.1", "1.1.1", "1.1.1.1", "CA-01"): {PMB: [100.0, 50.5], CTR: [120.0, 50.5], GOV: [130.25, 60.0]},
    ("1", "1.1", "1.1.1", "1.1.1.2", "CA-02"): {PMB: [150.0, 50.0], CTR: [180.0], GOV: [100.0, 100.0]},
    ("1", "1.1", "1.1.2", "1.1.2.1", "CA-03"): {PMB: [300.0, 25.0], CTR: [310.0], GOV: [250.0, 25.0]},
    ("1", "1.2", "1.2.1", "1.2.1.1", "CA-04"): {PMB: [75.25, 75.25], CTR: [150.5], GOV: [100.5, 60.0]},
    ("2", "2.1", "2.1.1", "2.1.1.1", "CA-05"): {PMB: [500.0], CTR: [500.0], GOV: [400.0, 50.0]},
    ("2", "2.1", "2.1.2", "2.1.2.1", "CA-06"): {PMB: [10.0, 20.0, 30.0], CTR: [60.0], GOV: [70.0]},
    ("2", "2.2", "2.2.1", "2.2.1.1", "CA-07"): {PMB: [1000.0], CTR: [950.0], GOV: [900.5]},
    ("3", "3.1", "3.1.1", "3.1.1.1", "CA-08"): {PMB: [40.0], CTR: [41.0], GOV: [20.0, 20.0]},
    ("3", "3.1", "3.1.1", "3.1.1.2", "CA-09"): {GOV: [33.0]},
    ("3", "3.2", "3.2.1", "3.2.1.1", "CA-10"): {PMB: [60.0, 15.0], CTR: [60.0]},
}


def b_frame():
    return pl.DataFrame(
        [{"program_id": PROG_B, "wbs_2": p[0], "wbs_3": p[1], "wbs_4": p[2], "wbs_5": p[3],
          "control_account": p[4], "period": f"P{i + 1}", "version": v, "amount": amount}
         for p, by_version in PLAN.items() for v, amounts in by_version.items()
         for i, amount in enumerate(amounts)],
        schema_overrides={"amount": pl.Float64})


def summed(version):
    """path -> the sum of the dict's rows of `version`; a path with no row of it is absent."""
    return {p: sum((Decimal(str(a)) for a in vs[version]), Decimal(0)) for p, vs in PLAN.items() if version in vs}


def diffs(a, b):
    """a less b over every path in either, a path missing from one counting as zero there."""
    sa, sb = summed(a), summed(b)
    return {p: sa.get(p, Decimal(0)) - sb.get(p, Decimal(0)) for p in {**sa, **sb}}


def edges_of(diff, root=PROG_B):
    """The edge table of `diff` (path -> signed amount) by the stated rule: every node carries the
    signed sum beneath it, nothing collapses (the row's threshold is 0), zeros are emitted."""
    nets = {}
    for path, amount in diff.items():
        for depth in range(1, len(path) + 1):
            nets[path[:depth]] = nets.get(path[:depth], Decimal(0)) + amount
    nets[()] = sum(diff.values(), Decimal(0))
    table = []
    for key, net in nets.items():
        source = None if not key else [root, *key[:-1]]
        table.append((source, [root, *key], abs(net),
                      "positive" if net > 0 else "negative" if net < 0 else "zero", len(key), "item"))
    return sorted(table, key=lambda e: (e[4], e[0] or [], -e[2], e[1]))


def served(rows):
    return [(e["source"], e["target"], Decimal(e["value_exact"]), e["sign"], e["level"], e["node_kind"])
            for e in rows]


def signed(rows):
    return {tuple(e["target"]): SIGN[e["sign"]] * Decimal(e["value_exact"]) for e in rows}


# -- the declarations --------------------------------------------------------------------------------

def _b_raw():
    return yaml.safe_load(B_CONTRACT.read_text(encoding="utf-8"))


def _plain_raw():
    raw = _b_raw()
    raw.pop("version_dimension")
    raw["contract_id"] = "program_b_plain"
    return raw


def _ev_versioned_raw():
    """The EV fixture's contract plus a version column: the sample-shaped control."""
    raw = yaml.safe_load(EV_CONTRACT.read_text(encoding="utf-8"))
    raw["columns"].append({"name": "version", "type": "string", "required": True})
    raw["grain"] = [*raw["grain"], "version"]
    raw["version_dimension"] = {"column": "version", "values": [PMB, CTR, GOV]}
    return raw


def row_of(fn, contract, urn, levels, value, params, *, shape="FLOW_DECOMPOSITION"):
    return {
        "measure_id": fn, "verb": "x" + fn.replace("_", ""), "name": fn,
        "inputs": {"params": {p: {"required": True} for p in params},
                   "dataset": {"urn": urn, "banner": "SYNTHETIC test fixture.", "contract": contract,
                               "levels": levels, "value": value, "per_path": "sum"},
                   "other_threshold": "0"},
        "computation": {"module": "agent_fleet.finance_agent.measure_modules.variance_decomposition",
                        "function": "flow_edges", "version": "1.3.0",
                        "derived_from": {"authority": "Test fixture, no external method",
                                         "clause": "A signed sum split down a hierarchy",
                                         "citation": "name-only", "transcription": "each edge is the signed sum beneath its child"}},
        "render": {"shape": shape, "value_label": fn, "unit": "USD"},
        "policy": {"status": "sample", "cells": ["PROGRAM_FINANCE"], "granted_by": "seed",
                   "reason": "a test row over a synthetic fixture"},
    }


COMPARE = {"compare": {"column": "amount", "by": "version"}}
B_COMPARE = row_of(FN_B, "program_b_versions", URN_B, B_LEVELS, COMPARE, ["program_id", "version_a", "version_b"])
B_FILTER = row_of(FN_FILTER, "program_b_versions", URN_B, B_LEVELS, "amount", ["program_id", "version"])
EV_COMPARE = row_of(FN_EV, "ev_fixture", URN_EV, ["program_id", "control_account", "work_package"],
                    {"compare": {"column": "acwp", "by": "version"}}, ["program_id", "version_a", "version_b"])


def load(tmp_path, monkeypatch, rows, contracts=None):
    """Load `rows` ({name: row dict}) over `contracts` ({name: raw dict}; by default the fixture
    program B's own file, byte for byte) with both calendars declared."""
    cdir, odir = tmp_path / "contracts", tmp_path / "overlay"
    cdir.mkdir(exist_ok=True)
    odir.mkdir(exist_ok=True)
    if contracts is None:
        (cdir / B_CONTRACT.name).write_bytes(B_CONTRACT.read_bytes())
    for name, raw in (contracts or {}).items():
        (cdir / f"{name}.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    for fn, row in rows.items():
        (odir / f"{fn}.yaml").write_text(yaml.safe_dump(row, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(cdir))
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(odir))
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", os.pathsep.join([str(SAMPLE_CAL), str(B_DIR / "fin_calendar")]))
    return engine._load_declared()


# -- 1. the parser -----------------------------------------------------------------------------------

def _parse(**over):
    raw = _b_raw()
    raw.update(over)
    return dataset_contracts._parse(raw)


def test_version_is_read_with_its_values_in_declared_order():
    c = _parse()
    assert c.version_column == "version" and c.versions == (PMB, CTR, GOV)
    assert c.versions == tuple(_b_raw()["version_dimension"]["values"])
    assert _parse(version_dimension={"column": "version", "values": ["Z", "A", "M"]}).versions == ("Z", "A", "M")


def test_an_absent_version_is_none_and_empty():
    raw = _b_raw()
    del raw["version_dimension"]
    c = dataset_contracts._parse(raw)
    assert (c.version_column, c.versions) == (None, ())


def test_the_contracts_own_revision_is_not_the_version_dimension():
    both = _b_raw()
    both["version"] = "1.0.0"
    c = dataset_contracts._parse(both)
    assert c.versions == (PMB, CTR, GOV) and c.version_column == "version"
    alone = _b_raw()
    alone.pop("version_dimension")
    alone["version"] = "1.0.0"
    c = dataset_contracts._parse(alone)
    assert (c.version_column, c.versions) == (None, ())


@pytest.mark.parametrize("bad, match", [
    ({"column": "version", "values": ["A", "B"], "extra": 1}, "extra"),
    ({"column": "nope", "values": ["A", "B"]}, "not a declared column"),
    ({"column": "amount", "values": ["A", "B"]}, "a string"),
    ({"column": "version", "values": []}, "non-empty"),
    ({"column": "version", "values": ["A", "A"]}, "repeats"),
    ({"column": "version", "values": ["A", ""]}, "non-empty strings"),
    ({"column": "version", "values": ["A", 2024]}, "quote it"),
    ({"column": "version"}, "non-empty"),
    ({"values": ["A"]}, "not a declared column"),
    (["A"], "mapping"),
])
def test_a_malformed_version_is_refused(bad, match):
    with pytest.raises(ValueError, match=match):
        _parse(version_dimension=bad)


# -- 2. a row's load ---------------------------------------------------------------------------------

def _row(base, **over):
    row = copy.deepcopy(base)
    for k, v in over.items():
        row["inputs"]["dataset"][k] = v
    return row


def test_the_compare_row_loads(tmp_path, monkeypatch):
    rows = load(tmp_path, monkeypatch, {FN_B: B_COMPARE})
    assert rows[FN_B].value_op == "compare" and rows[FN_B].compare_by == "version"
    assert rows[FN_B].value_columns == ("amount",) and rows[FN_B].contract.versions == (PMB, CTR, GOV)


def test_a_by_that_is_not_the_contracts_version_column_is_refused(tmp_path, monkeypatch):
    row = _row(B_COMPARE, value={"compare": {"column": "amount", "by": "period"}})
    with pytest.raises(ValueError, match=r"'period'.*'version'"):
        load(tmp_path, monkeypatch, {FN_B: row})


def test_a_compare_row_over_a_contract_with_no_version_is_refused(tmp_path, monkeypatch):
    row = _row(B_COMPARE, contract="program_b_plain")
    with pytest.raises(ValueError, match="program_b_plain.*declares no version"):
        load(tmp_path, monkeypatch, {FN_B: row}, contracts={"program_b_plain": _plain_raw()})


def test_a_version_free_value_over_a_versioned_contract_is_refused(tmp_path, monkeypatch):
    row = row_of(FN_FILTER, "program_b_versions", URN_B, B_LEVELS, "amount", ["program_id"])
    with pytest.raises(ValueError, match=r"declares a version \('version'\).*lists `version`"):
        load(tmp_path, monkeypatch, {FN_FILTER: row})


def test_the_same_row_listing_version_loads(tmp_path, monkeypatch):
    rows = load(tmp_path, monkeypatch, {FN_FILTER: B_FILTER})
    assert rows[FN_FILTER].value_op == "column" and "version" in rows[FN_FILTER].params


def test_a_compare_row_missing_version_b_is_refused(tmp_path, monkeypatch):
    row = copy.deepcopy(B_COMPARE)
    del row["inputs"]["params"]["version_b"]
    with pytest.raises(ValueError, match="version_a and version_b"):
        load(tmp_path, monkeypatch, {FN_B: row})


def test_a_compare_row_listing_version_is_refused(tmp_path, monkeypatch):
    row = copy.deepcopy(B_COMPARE)
    row["inputs"]["params"]["version"] = {"required": True}
    with pytest.raises(ValueError, match="version_a and version_b"):
        load(tmp_path, monkeypatch, {FN_B: row})


def test_a_version_param_on_an_unversioned_contract_is_refused(tmp_path, monkeypatch):
    row = row_of(FN_FILTER, "program_b_plain", URN_B, B_LEVELS, "amount", ["program_id", "version"])
    with pytest.raises(ValueError, match="declares no version"):
        load(tmp_path, monkeypatch, {FN_FILTER: row}, contracts={"program_b_plain": _plain_raw()})


def test_a_multi_series_row_over_a_versioned_contract_is_refused(tmp_path, monkeypatch):
    series = yaml.safe_load((ROWS / f"{CUM}.yaml").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="a series by version is a later step"):
        load(tmp_path, monkeypatch, {CUM: series}, contracts={"ev_fixture": _ev_versioned_raw()})


# -- the served world: ONE loaded engine, both shapes ------------------------------------------------

def ev_frames():
    """The EV fixture over two versions. EAC-GOV differs from PMB by an amount on WP-1102, holds
    no WP-5102 (a path only in PMB) and holds WP-1199 (a path only in EAC-GOV)."""
    base = frame_of()
    pmb = base.with_columns(pl.lit(PMB).alias("version"))
    gov = base.filter(pl.col("work_package") != "WP-5102").with_columns(
        pl.when(pl.col("work_package") == "WP-1102").then(pl.col("acwp") + 1000).otherwise(pl.col("acwp")).alias("acwp"),
        pl.lit(GOV).alias("version"))
    extra = base.filter(pl.col("work_package") == "WP-1101").with_columns(
        pl.lit("WP-1199").alias("work_package"), pl.lit(GOV).alias("version"))
    return pl.concat([pmb, gov, extra.select(gov.columns)])


def ev_summed(frame, version):
    out = {}
    for r in frame.filter(pl.col("version") == version).iter_rows(named=True):
        key = (r["control_account"], r["work_package"])
        out[key] = out.get(key, Decimal(0)) + Decimal(str(r["acwp"]))
    return out


class Gate:
    def __init__(self, frames):
        self.frames, self.n = frames, 0

    def load(self):
        gate = self

        class Client:
            def __init__(self, **kw):
                self.who = kw["originator_email"]

            def get_dataframe_with_ticket(self, urn):
                gate.n += 1
                if urn not in gate.frames or self.who != ALLOWED:
                    raise NotEntitled("refused")
                return ticketed(gate.frames[urn].lazy(), urn, gate.n)
        return Client, NotEntitled, MeshUnavailable


@pytest.fixture
def world(monkeypatch, tmp_path):
    rows = load(tmp_path, monkeypatch, {FN_B: B_COMPARE, FN_FILTER: B_FILTER, FN_EV: EV_COMPARE},
                contracts={"program_b_versions": _b_raw(), "ev_fixture": _ev_versioned_raw()})
    monkeypatch.setattr(engine, "DECLARED", rows)
    for fn, r in rows.items():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + r.verb, fn)
    gate = Gate({URN_B: b_frame(), URN_EV: ev_frames()})
    monkeypatch.setattr(engine.asset_inputs, "_load_client", gate.load)
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program in {PROG_B, PROGRAM} and caller_id in {ALLOWED, DENIED})
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    gate.rows = rows
    return gate


@pytest.fixture
def post(world):
    with TestClient(engine.app) as c:
        def call(fn=FN_B, program=PROG_B, **params):
            r = c.post(f"/measure/{fn}", json={"params": {"program_id": program, **params}, "user_email": ALLOWED},
                       headers={"Authorization": f"Bearer {token(ALLOWED)}"})
            return r.status_code, r.json()
        yield call


# -- 3. the slots ------------------------------------------------------------------------------------

def test_the_compare_row_registers_both_versions_with_the_contracts_list(world):
    row = world.rows[FN_B]
    slots = {s["name"]: s for s in engine._declared_slots(row)}
    assert set(slots) == {"program_id", "version_a", "version_b"}
    for name in ("version_a", "version_b"):
        assert slots[name]["values"] == list(row.contract.versions)
        assert slots[name]["required"] is True and slots[name]["kind"] == "spoken-mandatory"
    (method,) = [s for s in slots_for("fin_eac_calculation") if s["name"] == "method"]
    assert set(slots["version_a"]) == set(method)
    call = next(c for c in engine._registration_calls() if c["fn"] == FN_B)
    assert [s["name"] for s in call["slots"]] == ["program_id", "version_a", "version_b"]
    assert call["slots"][1]["values"] == list(row.contract.versions)


def test_the_filter_row_registers_one_version_slot(world):
    slots = {s["name"]: s for s in engine._declared_slots(world.rows[FN_FILTER])}
    assert set(slots) == {"program_id", "version"}
    assert slots["version"]["values"] == list(world.rows[FN_FILTER].contract.versions)


# -- 4. the served compare ---------------------------------------------------------------------------

def test_the_compare_serves_a_less_b_with_the_zero_fill(post):
    status, env = post(version_a=GOV, version_b=PMB)
    assert status == 200, env
    assert served(env["rows"]) == edges_of(diffs(GOV, PMB))
    # the controls the plan promises: both signs, a zero, and a path in one version only
    assert {"positive", "negative", "zero"} == {e["sign"] for e in env["rows"]}
    assert {tuple(e["target"][1:]) for e in env["rows"] if e["sign"] == "zero" and e["level"] == 5} == {
        ("1", "1.1", "1.1.1", "1.1.1.2", "CA-02"), ("3", "3.1", "3.1.1", "3.1.1.1", "CA-08")}
    by_target = signed(env["rows"])
    assert by_target[(PROG_B, "3", "3.1", "3.1.1", "3.1.1.2", "CA-09")] == Decimal("33")      # only in GOV
    assert by_target[(PROG_B, "3", "3.2", "3.2.1", "3.2.1.1", "CA-10")] == Decimal("-75")     # only in PMB


def test_the_root_is_total_a_less_total_b_exactly_and_the_block_is_exact_strings(post):
    status, env = post(version_a=GOV, version_b=PMB)
    block = env["compare"]
    (root,) = [e for e in env["rows"] if e["source"] is None]
    assert isinstance(block["total_a_exact"], str) and isinstance(block["total_b_exact"], str)
    assert SIGN[root["sign"]] * Decimal(root["value_exact"]) == Decimal(block["total_a_exact"]) - Decimal(block["total_b_exact"])
    assert Decimal(block["total_a_exact"]) == sum(summed(GOV).values(), Decimal(0))
    assert Decimal(block["total_b_exact"]) == sum(summed(PMB).values(), Decimal(0))
    assert block["version_a"] == GOV and block["version_b"] == PMB
    only_a = [p for p in summed(GOV) if p not in summed(PMB)]
    only_b = [p for p in summed(PMB) if p not in summed(GOV)]
    assert (block["paths_only_in_a"], block["paths_only_in_b"]) == (len(only_a), len(only_b)) == (1, 1)
    assert f"comparing {GOV} with {PMB}: 1 path(s) only in {GOV}, 1 only in {PMB}" in env["verdict"]


# -- 5. swapping a and b -----------------------------------------------------------------------------

def test_swapping_a_and_b_negates_every_edge_and_swaps_the_counts(post):
    _s, fwd = post(version_a=GOV, version_b=PMB)
    status, rev = post(version_a=PMB, version_b=GOV)
    assert status == 200, rev
    assert served(rev["rows"]) == edges_of(diffs(PMB, GOV))
    f, r = signed(fwd["rows"]), signed(rev["rows"])
    assert set(f) == set(r) and all(r[k] == -f[k] for k in f)
    assert (rev["compare"]["paths_only_in_a"], rev["compare"]["paths_only_in_b"]) == (
        fwd["compare"]["paths_only_in_b"], fwd["compare"]["paths_only_in_a"])
    assert rev["compare"]["total_a_exact"] == fwd["compare"]["total_b_exact"]


# -- 6. the filter row -------------------------------------------------------------------------------

def test_the_filter_row_reads_the_one_version_alone(post):
    status, env = post(FN_FILTER, version=PMB)
    assert status == 200, env
    only_pmb = served(env["rows"])
    assert only_pmb == edges_of(summed(PMB))
    assert env["version"] == PMB
    # the control: summed over every version the figures differ, so the filter is what is tested
    every = {}
    for v in (PMB, CTR, GOV):
        for p, a in summed(v).items():
            every[p] = every.get(p, Decimal(0)) + a
    assert only_pmb != edges_of(every)


# -- 7. refusals -------------------------------------------------------------------------------------

def test_a_version_outside_the_list_is_a_422_naming_the_declared_versions(post):
    status, body = post(version_a="FOO", version_b=PMB)
    assert status == 422
    msg = body["detail"]["not_in_model"]
    assert "version_a" in msg and all(v in msg for v in (PMB, CTR, GOV))
    status, body = post(version_a=GOV, version_b="BAR")
    assert status == 422 and "version_b" in body["detail"]["not_in_model"]
    status, body = post(FN_FILTER, version="FOO")
    assert status == 422 and "version" in body["detail"]["not_in_model"]


def test_a_equal_to_b_is_a_422(post):
    status, body = post(version_a=PMB, version_b=PMB)
    assert status == 422 and "not_in_model" in body["detail"]
    assert "same version" in body["detail"]["not_in_model"]
    assert "compare" not in body and "rows" not in body


def test_a_missing_version_is_asked_for_by_its_declared_list(post):
    status, body = post(version_a=GOV)
    assert status == 422 and body["detail"]["needs_slots"] == ["version_b"]
    assert all(v in body["detail"]["question"] for v in (PMB, CTR, GOV))
    status, body = post(FN_FILTER)
    assert status == 422 and body["detail"]["needs_slots"] == ["version"]


def test_a_row_carrying_a_version_outside_the_list_is_a_502_naming_no_value(post, world):
    frame = world.frames[URN_B]
    world.frames[URN_B] = frame.with_columns(
        pl.when(pl.col("control_account") == "CA-03").then(pl.lit("FOO")).otherwise(pl.col("version")).alias("version"))
    status, body = post(version_a=GOV, version_b=PMB)
    assert status == 502 and body["detail"]["error"] == "asset_contract_violation"
    assert body["detail"]["rule"] == "version_outside_list"
    assert "version" in body["detail"]["message"] and "FOO" not in str(body) and "CA-03" not in str(body)
    status, body = post(FN_FILTER, version=PMB)
    assert status == 502 and body["detail"]["rule"] == "version_outside_list"


def test_a_null_version_is_a_502_null_value(post, world):
    frame = world.frames[URN_B]
    world.frames[URN_B] = frame.with_columns(
        pl.when(pl.col("control_account") == "CA-03").then(None).otherwise(pl.col("version")).alias("version"))
    status, body = post(version_a=GOV, version_b=PMB)
    assert status == 502 and body["detail"]["rule"] == "null_value" and "version" in body["detail"]["message"]


def test_the_cap_counts_the_rows_read_across_all_versions(post, world, monkeypatch):
    frame = world.frames[URN_B]
    in_the_two = frame.filter(pl.col("version").is_in([GOV, PMB])).height
    assert in_the_two < frame.height
    monkeypatch.setenv("FIN_ASSET_MAX_ROWS", str(in_the_two))
    status, body = post(version_a=GOV, version_b=PMB)
    assert status == 422 and body["detail"]["error"] == "asset_too_large"
    monkeypatch.setenv("FIN_ASSET_MAX_ROWS", str(frame.height))
    status, _body = post(version_a=GOV, version_b=PMB)
    assert status == 200


# -- 8. two shapes, one engine build -----------------------------------------------------------------

def test_the_six_level_and_the_sample_shaped_compare_serve_through_one_engine(post, world):
    frame = world.frames[URN_EV]
    b_status, b_env = post(version_a=GOV, version_b=PMB)
    ev_status, ev_env = post(FN_EV, program=PROGRAM, version_a=GOV, version_b=PMB)
    assert b_status == 200 and ev_status == 200, (b_env, ev_env)
    assert served(b_env["rows"]) == edges_of(diffs(GOV, PMB))
    a, b = ev_summed(frame, GOV), ev_summed(frame, PMB)
    expected = edges_of({p: a.get(p, Decimal(0)) - b.get(p, Decimal(0)) for p in {**a, **b}}, root=PROGRAM)
    assert served(ev_env["rows"]) == expected
    assert max(e["level"] for e in b_env["rows"]) == 5 and max(e["level"] for e in ev_env["rows"]) == 2
    assert (ev_env["compare"]["paths_only_in_a"], ev_env["compare"]["paths_only_in_b"]) == (1, 1)
    assert {"WP-1199", "WP-5102"} <= {e["target"][-1] for e in ev_env["rows"]}


# -- 9. the artifact id ------------------------------------------------------------------------------

def test_the_artifact_id_follows_the_versions_chosen(post):
    ids = {(a, b): post(version_a=a, version_b=b)[1]["artifact_id"]
           for a, b in ((GOV, PMB), (CTR, PMB), (PMB, GOV))}
    assert len(set(ids.values())) == 3
    assert post(version_a=GOV, version_b=PMB)[1]["artifact_id"] == ids[(GOV, PMB)]


# -- 10. the difference and its percent of b ---------------------------------------------------------

def tiny(world, a, b):
    """Program B holding ONE path whose version totals are exactly `a` (EAC-GOV) and `b` (PMB)."""
    path = ("1", "1.1", "1.1.1", "1.1.1.1", "CA-01")
    rows = [{"program_id": PROG_B, "wbs_2": path[0], "wbs_3": path[1], "wbs_4": path[2], "wbs_5": path[3],
             "control_account": path[4], "period": "P1", "version": v, "amount": amt}
            for v, amt in ((GOV, a), (PMB, b))]
    world.frames[URN_B] = pl.DataFrame(rows, schema_overrides={"amount": pl.Float64})


def test_the_difference_is_exact_and_equals_the_root_edge(post):
    status, env = post(version_a=GOV, version_b=PMB)
    block = env["compare"]
    diff = Decimal(block["total_a_exact"]) - Decimal(block["total_b_exact"])
    assert isinstance(block["difference_exact"], str) and block["difference_exact"] == format(diff, "f")
    (root,) = [e for e in env["rows"] if e["source"] is None]
    assert SIGN[root["sign"]] * Decimal(root["value_exact"]) == Decimal(block["difference_exact"])
    assert block["difference_percent_of_b"] == format(diff / abs(Decimal(block["total_b_exact"])), "f")


def test_the_percent_is_a_fraction_of_b(post, world):
    tiny(world, 250.0, 200.0)
    status, env = post(version_a=GOV, version_b=PMB)
    assert status == 200, env
    assert Decimal(env["compare"]["difference_percent_of_b"]) == Decimal("0.25")
    assert Decimal(env["compare"]["difference_exact"]) == Decimal(50)
    assert env["compare"]["difference_percent_of_b"] == format(Decimal(50) / Decimal(200), "f")


def test_a_cent_on_a_billion_is_served_without_an_exponent(post, world):
    """str(Decimal) writes a quotient this small as "1E-11"; the wire holds plain decimals only."""
    tiny(world, 1_000_000_000.01, 1_000_000_000.00)
    status, env = post(version_a=GOV, version_b=PMB)
    assert status == 200, env
    block = env["compare"]
    assert block["difference_exact"] == "0.01"
    assert block["difference_percent_of_b"] == "0.00000000001"
    assert "E" not in env["verdict"].split(" less ", 1)[1]


def test_a_zero_b_total_leaves_the_percent_null_and_the_verdict_says_undefined(post, world):
    tiny(world, 250.0, 0.0)
    status, env = post(version_a=GOV, version_b=PMB)
    assert status == 200, env
    assert env["compare"]["difference_percent_of_b"] is None
    assert Decimal(env["compare"]["difference_exact"]) == Decimal(250)
    assert "undefined" in env["verdict"] and f"{PMB}'s total is zero" in env["verdict"]


def test_a_negative_b_total_gives_a_percent_of_the_differences_sign(post, world):
    tiny(world, -100.0, -200.0)
    status, env = post(version_a=GOV, version_b=PMB)
    assert status == 200, env
    diff = Decimal(env["compare"]["difference_exact"])
    pct = Decimal(env["compare"]["difference_percent_of_b"])
    assert diff == Decimal(100) and pct == Decimal("0.5")
    assert (pct > 0) == (diff > 0)
    tiny(world, -300.0, -200.0)
    _s, fall = post(version_a=GOV, version_b=PMB)
    assert Decimal(fall["compare"]["difference_exact"]) < 0 and Decimal(fall["compare"]["difference_percent_of_b"]) < 0


def test_swapping_a_and_b_negates_the_difference(post):
    _s, fwd = post(version_a=GOV, version_b=PMB)
    _s, rev = post(version_a=PMB, version_b=GOV)
    assert Decimal(rev["compare"]["difference_exact"]) == -Decimal(fwd["compare"]["difference_exact"])
    assert fwd["compare"]["difference_exact"] != "0"


def test_the_verdict_names_the_difference_and_percent_as_served(post):
    _s, env = post(version_a=GOV, version_b=PMB)
    block = env["compare"]
    assert f"{GOV} less {PMB} is {block['difference_exact']}, {block['difference_percent_of_b']} of {PMB}" in env["verdict"]
