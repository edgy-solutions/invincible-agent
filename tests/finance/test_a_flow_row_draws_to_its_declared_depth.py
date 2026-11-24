"""A flow row draws to a declared depth (`inputs.dataset.depth`), through the REAL engine route.

Synthetic program B (tests/fixtures/fin_program_b) has a work breakdown four WBS levels above its
control accounts and a two-level IPT breakdown beside it. Its WBS row declares `depth: 2`; its IPT
row declares none. The sample row (policy/overlays/sample/measure_verbs/fin_flow_acwp.yaml) and
both of B's rows are loaded into ONE engine. The route is real; the mesh client is a double holding
a gate per caller; the frames are real parquet built here (B's is never committed). The expected
edges are computed HERE, with polars and the stated collapse rule, from the same frames, and not
through the module.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_a_flow_row_draws_to_its_declared_depth.py
"""
from __future__ import annotations

import os
import re
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    MeshUnavailable, NotEntitled, _clean_env, frame_of, ticketed, token,
)
from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402
    ALLOWED, DENIED, PROGRAM, ROW_URN, THRESHOLD, expected_edges, served,
)

REPO = Path(__file__).resolve().parents[2]
SAMPLE_ROWS = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
SAMPLE_CAL = REPO / "policy" / "overlays" / "sample" / "fin_calendar"
B_DIR = REPO / "tests" / "fixtures" / "fin_program_b"
FN_SAMPLE, FN_WBS, FN_IPT, FN_ONCE = "fin_flow_acwp", "fin_b_flow_wbs", "fin_b_flow_ipt", "fin_b_flow_wbs_once"
PROG_B = "PRG-B"
URN_B = "urn:li:dataset:(urn:li:dataPlatform:s3,program_b,PROD)"
WBS_COLUMNS = ["wbs_1", "wbs_2", "wbs_3", "wbs_4", "control_account", "work_package"]
IPT_COLUMNS = ["ipt_1", "ipt_2", "work_package"]
SIGN = {"positive": 1, "negative": -1, "zero": 0}


# ── program B's frame, built here ─────────────────────────────────────────────────────────────

#: (wbs_1, wbs_2, the weight of one work package's period amount): B-1.2 and B-1.3 are light, so
#: they are small beside B-1.1 and collapse into one "All other" sink under B-1.
BRANCHES = [("B-1", "B-1.1", 100), ("B-1", "B-1.2", 3), ("B-1", "B-1.3", 3),
            ("B-2", "B-2.1", 60), ("B-2", "B-2.2", 60)]
PERIODS = [f"P{n}" for n in range(1, 13)]
#: Step 4 (the remainder keeps its members): extra control accounts, each ONE work package carrying
#: the SAME amount in every period, under two WBS-4 nodes. Under B-1.1.1.1 (beside CA-01) two small
#: positive accounts form a sink at the control-account level; under B-2.1.1.1 (beside CA-05) a
#: small positive and a small NEGATIVE account form a sink of MIXED signs. (wbs_1, wbs_2, wbs_3,
#: wbs_4, control account, the amount in every period). Every one is far below 15% of its parent.
EXTRA_ACCOUNTS = [
    ("B-1", "B-1.1", "B-1.1.1", "B-1.1.1.1", "CA-21", 1.0),
    ("B-1", "B-1.1", "B-1.1.1", "B-1.1.1.1", "CA-22", 0.25),
    ("B-2", "B-2.1", "B-2.1.1", "B-2.1.1.1", "CA-23", 1.0),
    ("B-2", "B-2.1", "B-2.1.1", "B-2.1.1.1", "CA-24", -0.5),
]
IPTS = [("IPT-A", "IPT-A1"), ("IPT-A", "IPT-A2"), ("IPT-B", "IPT-B1"), ("IPT-B", "IPT-B2")]


def b_frame():
    """Five WBS-2 branches, two WBS-3 under each, two WBS-4 under each, one control account under
    each WBS-4 and TWO work packages under each control account: 40 work packages, 12 periods; then
    `EXTRA_ACCOUNTS`, four more control accounts of one work package each. A
    control account's two work packages carry the SAME amount in every period. Amounts are
    multiples of 0.25, so every sum is exact."""
    rows, ca, wp = [], 0, 0
    for w1, w2, weight in BRANCHES:
        for i3 in (1, 2):
            for i4 in (1, 2):
                ca += 1
                for _ in range(2):
                    ipt_1, ipt_2 = IPTS[wp % 4]
                    wp += 1
                    for k, period in enumerate(PERIODS):
                        amount = weight + 0.25 * ((ca + k) % 4)
                        rows.append({
                            "program_id": PROG_B, "wbs_1": w1, "wbs_2": w2, "wbs_3": f"{w2}.{i3}",
                            "wbs_4": f"{w2}.{i3}.{i4}", "control_account": f"CA-{ca:02d}",
                            "work_package": f"WP-{wp:04d}", "ipt_1": ipt_1, "ipt_2": ipt_2,
                            "period": period, "bcws": amount, "bcwp": amount, "acwp": amount})
    for w1, w2, w3, w4, account, amount in EXTRA_ACCOUNTS:
        ipt_1, ipt_2 = IPTS[wp % 4]
        wp += 1
        for period in PERIODS:
            rows.append({
                "program_id": PROG_B, "wbs_1": w1, "wbs_2": w2, "wbs_3": w3, "wbs_4": w4,
                "control_account": account, "work_package": f"WP-{wp:04d}", "ipt_1": ipt_1,
                "ipt_2": ipt_2, "period": period, "bcws": amount, "bcwp": amount, "acwp": amount})
    return pl.DataFrame(rows)


def b_once_frame(frame):
    """The frame a `per_path: once` row can read: each work package carries ONE amount in every
    period (else the read refuses `varies_within_path`). Every work package of B-2.2 carries 7."""
    once = frame.with_columns(pl.col("acwp").first().over("work_package"))
    return once.with_columns(pl.when(pl.col("wbs_2") == "B-2.2").then(7.0).otherwise(pl.col("acwp")).alias("acwp"))


# ── the oracle: polars sums and the stated collapse rule, NOT the module ─────────────────────

def b_expected(frame, columns, threshold, depth=None):
    f = frame.filter(pl.col("program_id") == PROG_B)
    cols = columns[:depth] if depth else columns

    def split(parent, kids):
        total = sum((abs(v) for v in kids.values()), Decimal(0))
        small = [k for k, v in kids.items() if v != 0 and abs(v) / total < threshold]
        out, kept = [], []
        for k, v in kids.items():
            if len(small) > 1 and k in small:
                continue
            out.append((parent + [k], v))
            kept.append(k)
        if len(small) > 1:
            out.append((parent + ["All other"], sum((kids[k] for k in small), Decimal(0))))
        return out, kept

    edges = [(None, [PROG_B], sum((Decimal(str(v)) for v in f["acwp"]), Decimal(0)))]
    frontier = [[PROG_B]]
    for d, col in enumerate(cols):
        following = []
        for parent in frontier:
            sub = f
            for c, v in zip(cols[:d], parent[1:]):
                sub = sub.filter(pl.col(c) == v)
            kids = {r[0]: sum((Decimal(str(x)) for x in r[1]), Decimal(0))
                    for r in sub.group_by(col).agg(pl.col("acwp")).iter_rows()}
            out, kept = split(parent, kids)
            edges += [(parent, t, v) for t, v in out]
            following += [parent + [k] for k in kept]
        frontier = following
    table = [(s, t, abs(v), "positive" if v > 0 else "negative" if v < 0 else "zero", len(t) - 1) for s, t, v in edges]
    return sorted(table, key=lambda e: (e[4], e[0] or [], -e[2], e[1]))


def conserved(rows, program, root_value):
    value_of = {tuple(e["target"]): SIGN[e["sign"]] * Decimal(e["value_exact"]) for e in rows}
    assert value_of[(program,)] == root_value
    for node in {tuple(e["source"]) for e in rows if e["source"] is not None}:
        kids = sum((SIGN[e["sign"]] * Decimal(e["value_exact"]) for e in rows if e["source"] == list(node)),
                   Decimal(0))
        assert kids == value_of[node], node


def max_level(rows):
    return max(e["level"] for e in rows)


# ── the engine: the sample's row and B's rows in ONE engine ──────────────────────────────────

class Gate:
    """The client double: a subject not in `granted` is refused; a URN not in `frames` does not exist."""

    def __init__(self, frames):
        self.frames = frames
        self.granted = {ALLOWED}
        self.asked: list[tuple[str, str]] = []

    def load(self):
        gate = self

        class Client:
            def __init__(self, **kw):
                self.who = kw["originator_email"]

            def get_dataframe_with_ticket(self, urn):
                gate.asked.append((self.who, urn))
                if urn not in gate.frames or self.who not in gate.granted:
                    raise NotEntitled("refused")
                return ticketed(gate.frames[urn], urn, len(gate.asked))
        return Client, NotEntitled, MeshUnavailable


def once_variant_of_the_wbs_row():
    """B's WBS row with only `per_path` changed (and the id and verb its own, as a row must be)."""
    raw = yaml.safe_load((B_DIR / "measure_verbs" / "fin_b_flow_wbs.yaml").read_text(encoding="utf-8"))
    raw["measure_id"], raw["verb"] = FN_ONCE, "finBFlowWbsActualCostOnce"
    raw["synonyms"] = ["program b wbs flow, counted once"]
    raw["inputs"]["dataset"]["per_path"] = "once"
    return raw


def use_dirs(monkeypatch, contracts, overlays):
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(contracts))
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", os.pathsep.join(str(o) for o in overlays))
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", os.pathsep.join([str(SAMPLE_CAL), str(B_DIR / "fin_calendar")]))


def contract_dir(tmp_path):
    cdir = tmp_path / "contracts"
    cdir.mkdir(exist_ok=True)
    shutil.copyfile(REPO / "contracts" / "ev_fixture.yaml", cdir / "ev_fixture.yaml")
    shutil.copyfile(B_DIR / "contracts" / "program_b.yaml", cdir / "program_b.yaml")
    return cdir


@pytest.fixture
def rows(monkeypatch, tmp_path):
    sample, variant = tmp_path / "sample", tmp_path / "variant"
    sample.mkdir()
    variant.mkdir()
    shutil.copyfile(SAMPLE_ROWS / f"{FN_SAMPLE}.yaml", sample / f"{FN_SAMPLE}.yaml")
    (variant / f"{FN_ONCE}.yaml").write_text(yaml.safe_dump(once_variant_of_the_wbs_row(), sort_keys=False),
                                             encoding="utf-8")
    use_dirs(monkeypatch, contract_dir(tmp_path), [sample, B_DIR / "measure_verbs", variant])
    declared = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", declared)
    for fn, row in declared.items():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + row.verb, fn)
    return declared


@pytest.fixture
def members(monkeypatch):
    held = {ALLOWED, DENIED}
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program in (PROGRAM, PROG_B) and caller_id in held)
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))


@pytest.fixture
def gate(tmp_path, rows, members, monkeypatch):
    ev, b = tmp_path / "ev.parquet", tmp_path / "b.parquet"
    frame_of().write_parquet(ev)
    b_frame().write_parquet(b)
    g = Gate({ROW_URN: pl.scan_parquet(ev), URN_B: pl.scan_parquet(b)})
    monkeypatch.setattr(engine.asset_inputs, "_load_client", g.load)
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    return g


@pytest.fixture
def post(gate):
    with TestClient(engine.app) as c:
        def call(fn, program=PROG_B):
            r = c.post(f"/measure/{fn}", json={"params": {"program_id": program}, "user_email": ALLOWED},
                       headers={"Authorization": f"Bearer {token(ALLOWED)}"})
            return r.status_code, r.json()
        yield call


# ── green ─────────────────────────────────────────────────────────────────────────────────────

def test_the_wbs_row_cut_at_two_equals_an_independent_sum_by_the_first_two_levels(post, rows):
    status, env = post(FN_WBS)
    assert status == 200, env
    frame = b_frame()
    want = b_expected(frame, WBS_COLUMNS, Decimal("0.15"), depth=2)
    assert served(env["rows"]) == want
    assert max_level(env["rows"]) == 2 and rows[FN_WBS].depth == 2
    # the same sums, grouped independently by (wbs_1, wbs_2)
    by_pair = {(r[0], r[1]): Decimal(str(r[2])) for r in
               frame.group_by("wbs_1", "wbs_2").agg(pl.col("acwp").sum()).iter_rows()}
    level2 = {tuple(e["target"][1:]): Decimal(e["value_exact"]) for e in env["rows"]
              if e["level"] == 2 and e["node_kind"] != "other"}
    assert level2 == {k: v for k, v in by_pair.items() if k[1] in ("B-1.1", "B-2.1", "B-2.2")}
    others = [e for e in env["rows"] if e["node_kind"] == "other"]
    assert [(e["source"], e["level"]) for e in others] == [([PROG_B, "B-1"], 2)]   # the collapse fired, at level 2
    assert Decimal(others[0]["value_exact"]) == by_pair[("B-1", "B-1.2")] + by_pair[("B-1", "B-1.3")]
    total = sum((Decimal(str(v)) for v in frame["acwp"]), Decimal(0))
    conserved(env["rows"], PROG_B, total)                                      # the root is the full total


def test_the_verdict_says_k_of_n_levels(post, rows):
    _s, env = post(FN_WBS)
    row = rows[FN_WBS]
    assert "over 2 of 6 levels" in env["verdict"]
    assert f"over {row.depth} of {len(row.levels) - 1} levels" in env["verdict"]
    assert max_level(env["rows"]) == row.depth, "the verdict restates a table drawn to the depth it names"
    _s, sample = post(FN_SAMPLE, PROGRAM)
    n = len(rows[FN_SAMPLE].levels) - 1
    assert f"over {n} levels" in sample["verdict"] and not re.search(r"over \d+ of \d+ levels", sample["verdict"])


def test_the_same_engine_serves_the_sample_at_full_depth_and_b_cut(post, rows):
    status, env = post(FN_SAMPLE, PROGRAM)
    assert status == 200, env
    assert rows[FN_SAMPLE].depth is None
    assert served(env["rows"]) == expected_edges(frame_of(), THRESHOLD)       # as before, full depth
    assert max_level(env["rows"]) == len(rows[FN_SAMPLE].levels) - 1
    status, ipt = post(FN_IPT)
    assert status == 200, ipt
    assert rows[FN_IPT].depth is None and max_level(ipt["rows"]) == 3
    assert served(ipt["rows"]) == b_expected(b_frame(), IPT_COLUMNS, Decimal("0.15"))
    status, wbs = post(FN_WBS)
    assert status == 200 and max_level(wbs["rows"]) == 2


def test_once_dedups_on_the_full_path_before_the_cut(post, gate, rows):
    frame = b_once_frame(b_frame())
    pair = frame.filter(pl.col("control_account") == "CA-20").select("work_package", "acwp").unique()
    assert pair.height == 2 and pair["acwp"].n_unique() == 1, "control: two work packages, ONE amount"
    gate.frames[URN_B] = frame.lazy()
    status, env = post(FN_ONCE)
    assert status == 200, env
    assert rows[FN_ONCE].per_path == "once" and rows[FN_ONCE].depth == 2
    once = frame.unique(subset=["work_package"])                            # each work package counted once
    assert served(env["rows"]) == b_expected(once, WBS_COLUMNS, Decimal("0.15"), depth=2)
    branch = {tuple(e["target"][1:]): Decimal(e["value_exact"]) for e in env["rows"] if e["level"] == 2}
    assert branch[("B-2", "B-2.2")] == Decimal("56"), "eight work packages of 7 each: every one counted"


# ── refusals at load ──────────────────────────────────────────────────────────────────────────

def _load_with(monkeypatch, tmp_path, raw, name):
    overlay = tmp_path / "bad"
    overlay.mkdir(exist_ok=True)
    (overlay / f"{name}.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    use_dirs(monkeypatch, contract_dir(tmp_path), [overlay])
    return engine._load_declared()


WBS_LEVELS = yaml.safe_load((B_DIR / "measure_verbs" / "fin_b_flow_wbs.yaml").read_text(encoding="utf-8"))["inputs"]["dataset"]["levels"]


@pytest.mark.parametrize("bad", [0, len(WBS_LEVELS), True, "2", 1.5], ids=["zero", "one_past", "bool", "string", "float"])
def test_a_bad_depth_is_refused_at_load(bad, monkeypatch, tmp_path):
    raw = once_variant_of_the_wbs_row()
    raw["measure_id"], raw["verb"] = "fin_b_bad_depth", "finBBadDepth"
    raw["inputs"]["dataset"]["per_path"] = "sum"
    raw["inputs"]["dataset"]["depth"] = bad
    with pytest.raises(ValueError) as caught:
        _load_with(monkeypatch, tmp_path, raw, "fin_b_bad_depth")
    message = str(caught.value)
    assert f"inputs.dataset.depth must be an integer from 1 to {len(WBS_LEVELS) - 1}" in message, message
    assert "fin_b_bad_depth" in message, "the refusal names the file"


def test_a_series_row_does_not_take_depth(monkeypatch, tmp_path):
    raw = yaml.safe_load((SAMPLE_ROWS / "fin_ev_cumulative.yaml").read_text(encoding="utf-8"))
    raw["inputs"]["dataset"]["depth"] = 2
    with pytest.raises(ValueError, match=r"carries \['depth'\]") as caught:
        _load_with(monkeypatch, tmp_path, raw, "fin_series_with_depth")
    assert "fin_series_with_depth" in str(caught.value)
