"""The EAC variance row: a dataset-kind row whose value is a DIFFERENCE of two columns, taken ONCE
per terminal path. It is the measure's first user (ruled 2026-11-04).

A TEST overlay (tests/finance/overlays/variance_decomposition_eac/, never policy/) declares
`value: {minus: [eac, bac]}` with `per_path: once`. The frame is the EV fixture plus two columns
that repeat identically on each of a work package's six rows, so a sum would count each work
package six times and `once` is the only reading that is right. The expected edges are computed
HERE, from the dict that built the columns, and not through the module or the reader.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_variance_decomposition_eac_row.py
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    MeshUnavailable, NotEntitled, _clean_env, frame_of, token,
)
from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402
    ALLOWED, DENIED, PROGRAM, Gate,
)

OVERLAY = Path(__file__).parent / "overlays" / "variance_decomposition_eac"
FN = "fin_flow_eac_variance"
THRESHOLD = Decimal("0.05")     # the row's own; read back from the loaded row in the first test
SIGN = {"positive": 1, "negative": -1, "zero": 0}

# work package -> (control account, bac, eac), the figures of dag-tools #11 (Int64, repeated on each
# of a work package's six rows). eac - bac: WP-1101, WP-2102 and WP-3102 are exactly zero. Account
# nets are 1.1 -200000, 2.1 +150000, 3.1 +1100000, 4.1 -75000, 5.1 +90000. At the row's 0.05 only
# 4.1 falls below, alone, so nothing collapses; at 0.15 four accounts fall below and collapse into
# one "All other" sink (-35000). A zero-net node with nonzero children is in the module tests.
PLAN = {
    "WP-1101": ("1.1", 1200000, 1200000), "WP-1102": ("1.1", 1200000, 1000000),
    "WP-2101": ("2.1", 2400000, 2550000), "WP-2102": ("2.1", 1500000, 1500000),
    "WP-3101": ("3.1", 1800000, 2900000), "WP-3102": ("3.1", 900000, 900000),
    "WP-4101": ("4.1", 1500000, 1425000),
    "WP-5101": ("5.1", 900000, 1050000), "WP-5102": ("5.1", 600000, 540000),
}


def frame():
    return frame_of().with_columns(
        pl.col("work_package").replace_strict({w: v[1] for w, v in PLAN.items()}, return_dtype=pl.Int64).alias("bac"),
        pl.col("work_package").replace_strict({w: v[2] for w, v in PLAN.items()}, return_dtype=pl.Int64).alias("eac"))


@pytest.fixture
def flow_rows(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(OVERLAY))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + rows[FN].verb, FN)
    return rows


@pytest.fixture
def gate(tmp_path, flow_rows, monkeypatch):
    path = tmp_path / "diff.parquet"
    frame().write_parquet(path)
    g = Gate(pl.scan_parquet(path))
    monkeypatch.setattr(engine.asset_inputs, "_load_client", g.load)
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program == PROGRAM and caller_id in {ALLOWED, DENIED})
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    return g


@pytest.fixture
def post(gate):
    with TestClient(engine.app) as c:
        def call():
            r = c.post(f"/measure/{FN}", json={"params": {"program_id": PROGRAM}, "user_email": ALLOWED},
                       headers={"Authorization": f"Bearer {token(ALLOWED)}"})
            return r.status_code, r.json()
        yield call


def expected_edges(times=1, threshold=THRESHOLD):
    """The edge table by the stated rule: eac - bac once per work package (times = how often a
    work package is counted), zeros emitted, siblings under the threshold collapsed if two or more."""
    wp_net = {w: Decimal(eac - bac) * times for w, (_ca, bac, eac) in PLAN.items()}
    ca_net: dict[str, Decimal] = {}
    for w, (ca, _b, _e) in PLAN.items():
        ca_net[ca] = ca_net.get(ca, Decimal(0)) + wp_net[w]

    def split(parent, kids):
        total = sum((abs(v) for v in kids.values()), Decimal(0))
        small = [k for k, v in kids.items() if v != 0 and abs(v) < threshold * total]
        out, kept = [], []
        for k, v in kids.items():
            if len(small) > 1 and k in small:
                continue
            out.append((parent + [k], v, "item"))
            kept.append(k)
        if len(small) > 1:
            out.append((parent + ["All other"], sum((kids[k] for k in small), Decimal(0)), "other"))
        return out, kept

    level1, kept = split([PROGRAM], ca_net)
    edges = [(None, [PROGRAM], sum(ca_net.values(), Decimal(0)), "item")]   # the root edge
    edges += [([PROGRAM], t, v, kind) for t, v, kind in level1]
    for ca in kept:
        level2, _ = split([PROGRAM, ca], {w: wp_net[w] for w, v in PLAN.items() if v[0] == ca})
        edges += [([PROGRAM, ca], t, v, kind) for t, v, kind in level2]
    table = [(s, t, abs(v), "positive" if v > 0 else "negative" if v < 0 else "zero", len(t) - 1, kind)
             for s, t, v, kind in edges]
    return sorted(table, key=lambda e: (e[4], e[0] or [], -e[2], e[1]))


def served(rows):
    return [(e["source"], e["target"], Decimal(e["value_exact"]), e["sign"], e["level"], e["node_kind"])
            for e in rows]


def test_the_edges_equal_eac_less_bac_taken_once_per_work_package(post, flow_rows):
    assert flow_rows[FN].other_threshold == THRESHOLD
    status, env = post()
    assert status == 200, env
    assert served(env["rows"]) == expected_edges()
    assert len(env["rows"]) == 1 + 5 + 9 and not [e for e in env["rows"] if e["node_kind"] == "other"]
    assert env["method"]["version"] == "1.3.0" and env["render"]["value_label"] == "EAC variance"


def test_at_0_15_four_accounts_fold_into_one_sink_and_one_zero_is_drawn(post, flow_rows, monkeypatch):
    monkeypatch.setitem(engine.DECLARED, FN,
                        dataclasses.replace(flow_rows[FN], other_threshold=Decimal("0.15")))
    status, env = post()
    assert status == 200, env
    assert served(env["rows"]) == expected_edges(threshold=Decimal("0.15"))
    sink = [e for e in env["rows"] if e["node_kind"] == "other"]
    assert len(sink) == 1 and sink[0]["sign"] == "negative" and Decimal(sink[0]["value_exact"]) == 35000
    assert {tuple(e["target"]) for e in env["rows"] if e["sign"] == "zero"} == {(PROGRAM, "3.1", "WP-3102")}


def test_the_zero_edges_are_present_and_each_level_reconciles(post):
    _status, env = post()
    rows = env["rows"]
    zeros = {tuple(e["target"]) for e in rows if e["sign"] == "zero"}
    assert zeros == {(PROGRAM, "1.1", "WP-1101"), (PROGRAM, "2.1", "WP-2102"), (PROGRAM, "3.1", "WP-3102")}
    assert all(Decimal(e["value_exact"]) == 0 for e in rows if e["sign"] == "zero")
    value_of = {tuple(e["target"]): SIGN[e["sign"]] * Decimal(e["value_exact"]) for e in rows}
    assert value_of[(PROGRAM,)] == sum((Decimal(eac - bac) for _c, bac, eac in PLAN.values()), Decimal(0))
    (root,) = [e for e in rows if e["source"] is None]
    assert (root["target"], root["level"], root["sign"], root["value_exact"]) == ([PROGRAM], 0, "positive", "1065000.00")
    for node in {tuple(e["source"]) for e in rows if e["source"] is not None}:
        kids = sum((SIGN[e["sign"]] * Decimal(e["value_exact"]) for e in rows if e["source"] == list(node)),
                   Decimal(0))
        assert kids == value_of[node], node
    assert "3 edge(s) at zero" in env["verdict"] and "net 1065000.00" in env["verdict"]
    assert "0 'All other' sink(s)" in env["verdict"] and "across 14 edges over 2 levels" in env["verdict"]


def test_over_and_under_work_packages_carry_all_three_signs(post):
    _status, env = post()
    assert {"positive", "negative", "zero"} == {e["sign"] for e in env["rows"]}


def test_per_path_sum_counts_each_work_package_six_times_so_once_is_what_is_tested(post, flow_rows, monkeypatch):
    monkeypatch.setitem(engine.DECLARED, FN, dataclasses.replace(flow_rows[FN], per_path="sum"))
    status, env = post()
    assert status == 200, env
    assert served(env["rows"]) == expected_edges(times=6)
    assert served(env["rows"]) != expected_edges()


def test_eac_varying_within_a_work_package_is_a_502_varies_within_path_naming_no_value(post, gate):
    gate.frame = gate.frame.with_columns(
        pl.when((pl.col("work_package") == "WP-1101") & (pl.col("period") == pl.col("period").min()))
        .then(pl.col("eac") + 7777).otherwise(pl.col("eac")).alias("eac"))
    status, body = post()
    assert status == 502 and body["detail"]["error"] == "asset_contract_violation"
    assert body["detail"]["rule"] == "varies_within_path"
    assert body["detail"]["message"] == "eac, bac vary within one terminal path"
    assert "7777" not in str(body) and "WP-1101" not in str(body) and "rows" not in body


def test_a_null_in_bac_is_a_502_null_value(post, gate):
    gate.frame = gate.frame.with_columns(
        pl.when((pl.col("work_package") == "WP-1101") & (pl.col("period") == pl.col("period").min()))
        .then(None).otherwise(pl.col("bac")).alias("bac"))
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "null_value" and "bac" in body["detail"]["message"]


def test_a_missing_second_column_is_a_502_missing_column(post, gate):
    gate.frame = gate.frame.drop("bac")
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "missing_column" and "bac" in body["detail"]["message"]


def test_the_row_cap_counts_rows_read_before_the_reduction(post, monkeypatch):
    monkeypatch.setenv("FIN_ASSET_MAX_ROWS", "9")        # 9 distinct paths, but 54 rows read
    status, body = post()
    assert status == 422 and body["detail"]["error"] == "asset_too_large"
