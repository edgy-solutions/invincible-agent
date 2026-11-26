"""The "All other" row keeps its members: `members` on the sink edge, through the REAL engine route.

A sink edge (`node_kind: "other"`) collapses two or more small siblings into one row. Step 4 keeps
who they were: `members`, one `{target, value, value_exact, sign}` per collapsed child, ordered by
value descending then target, whose SIGNED values sum to the sink's signed value exactly. An item
edge carries no `members` key.

The module-level tests call `flow_edges` directly; the oracle is a plain walk over the frame with
polars sums and the stated collapse rule, never the module. The served tests use program B's
`fin_b_flow_wbs_ca` row (depth 5, through the control account) over B's frame, which has a sink of
all-positive members and a sink of MIXED signs (EXTRA_ACCOUNTS in the step 3 module). The route is
real; the mesh client is the step 3 gate double; the frame is built, never committed.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_remainder_keeps_its_members.py
"""
from __future__ import annotations

from decimal import Decimal

import pytest
import yaml

pl = pytest.importorskip("polars")

from agent_fleet.finance_agent.measure_modules import variance_decomposition as vd  # noqa: E402
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import (  # noqa: E402,F401
    B_DIR, EXTRA_ACCOUNTS, PROG_B, SIGN, WBS_COLUMNS, _clean_env, _load_with, b_frame, gate,
    members, post, rows,
)
from tests.planning.test_planning_archetypes_are_projected import _fns  # noqa: E402

D = Decimal
FN_CA = "fin_b_flow_wbs_ca"
THRESHOLD = D("0.15")
DEPTH = 5


# ── the oracle: polars sums and the stated collapse rule, NOT the module ─────────────────────

def expected_sinks(frame, columns, threshold):
    """{sink source path: [(member path, absolute net, sign), ...]} for every parent of `frame`
    under PROG_B, down `columns`. A parent's collapse: two or more nonzero children each below
    `threshold` of the sum of the nonzero children's absolute values."""
    f = frame.filter(pl.col("program_id") == PROG_B)
    out, frontier = {}, [[PROG_B]]
    for d, col in enumerate(columns):
        following = []
        for parent in frontier:
            sub = f
            for c, v in zip(columns[:d], parent[1:]):
                sub = sub.filter(pl.col(c) == v)
            kids = {r[0]: sum((D(str(x)) for x in r[1]), D(0))
                    for r in sub.group_by(col).agg(pl.col("acwp")).iter_rows()}
            total = sum((abs(v) for v in kids.values()), D(0))
            small = [k for k, v in kids.items() if v != 0 and abs(v) / total < threshold]
            if len(small) > 1:
                out[tuple(parent)] = sorted(
                    ((parent + [k], abs(kids[k]), "positive" if kids[k] > 0 else "negative") for k in small),
                    key=lambda m: (-m[1], m[0]))
            following += [parent + [k] for k in kids if not (len(small) > 1 and k in small)]
        frontier = following
    return out


def paths_of(frame, columns):
    """B's frame as `flow_edges` takes it: one (levels, amount) per control account, by polars."""
    grouped = frame.group_by(*columns).agg(pl.col("acwp"))
    return [(tuple(r[:-1]), sum((D(str(x)) for x in r[-1]), D(0))) for r in grouped.iter_rows()]


def signed_of(member):
    return SIGN[member["sign"]] * D(member["value_exact"] if "value_exact" in member else member["value"])


# ── the module, directly ─────────────────────────────────────────────────────────────────────

def test_the_members_are_the_collapsed_children_and_sum_to_the_sink():
    frame = b_frame()
    columns = WBS_COLUMNS[:DEPTH]
    edges = vd.flow_edges(root=PROG_B, paths=paths_of(frame, columns), other_threshold=THRESHOLD)
    want = expected_sinks(frame, columns, THRESHOLD)
    sinks = [e for e in edges if e["node_kind"] == "other"]
    assert sinks and len(sinks) == len(want), "control: the oracle and the module see the same sinks"
    assert {tuple(e["source"]) for e in sinks} == set(want)
    for sink in sinks:
        got = [(m["target"], m["value"], m["sign"]) for m in sink["members"]]
        assert got == want[tuple(sink["source"])], sink["source"]          # exactly the small ones, in order
        signed = sum((SIGN[m["sign"]] * m["value"] for m in sink["members"]), D(0))
        assert signed == SIGN[sink["sign"]] * sink["value"], sink["source"]   # exact, Decimal
        assert all(isinstance(m["value"], D) and m["target"][:-1] == sink["source"] for m in sink["members"])
    assert all("members" not in e for e in edges if e["node_kind"] != "other")


def test_members_order_ties_by_target_and_carry_their_own_signs():
    paths = [(("big",), D("100")), (("b",), D("2")), (("a",), D("2")), (("c",), D("-3")), (("d",), D("1"))]
    (sink,) = [e for e in vd.flow_edges(root="R", paths=paths, other_threshold=D("0.1"))
               if e["node_kind"] == "other"]
    assert [(m["target"][-1], m["value"], m["sign"]) for m in sink["members"]] == [
        ("c", D("3"), "negative"), ("a", D("2"), "positive"), ("b", D("2"), "positive"),
        ("d", D("1"), "positive")]
    assert sink["value"] == D("2") and sink["sign"] == "positive"     # 2 + 2 - 3 + 1


def test_a_zero_net_sibling_is_never_a_member():
    paths = [(("big", "x"), D("100")), (("s1", "x"), D("3")), (("s2", "x"), D("-2")),
             (("zero", "x"), D("5")), (("zero", "y"), D("-5"))]
    edges = vd.flow_edges(root="R", paths=paths, other_threshold=D("0.15"))
    (sink,) = [e for e in edges if e["node_kind"] == "other"]
    named = {m["target"][-1] for m in sink["members"]}
    assert named == {"s1", "s2"} and "zero" not in named
    zero = [e for e in edges if e["target"] == ["R", "zero"]]          # the control: it IS an item edge
    assert len(zero) == 1 and zero[0]["sign"] == "zero" and zero[0]["node_kind"] == "item"
    assert zero[0]["value"] == 0 and "members" not in zero[0]
    assert sum((SIGN[m["sign"]] * m["value"] for m in sink["members"]), D(0)) == SIGN[sink["sign"]] * sink["value"]


# ── served, with exact money ─────────────────────────────────────────────────────────────────

def test_b_served_sinks_carry_members_with_exact_money(post, rows):
    status, env = post(FN_CA)
    assert status == 200, env
    assert rows[FN_CA].depth == DEPTH
    sinks = [e for e in env["rows"] if e["node_kind"] == "other"]
    want = expected_sinks(b_frame(), WBS_COLUMNS[:DEPTH], THRESHOLD)
    assert sinks and len(sinks) == len(want), "control: at least one sink is served, as many as the oracle finds"
    mixed = 0
    for sink in sinks:
        assert sink["members"], sink
        for m in sink["members"]:
            assert isinstance(m["value"], float) and isinstance(m["value_exact"], str), m
            assert m["target"][:-1] == sink["source"], "a member's parent is the sink's source"
        assert sum((signed_of(m) for m in sink["members"]), D(0)) == SIGN[sink["sign"]] * D(sink["value_exact"])
        got = [(m["target"], D(m["value_exact"]), m["sign"]) for m in sink["members"]]
        assert got == want[tuple(sink["source"])]
        mixed += len({m["sign"] for m in sink["members"]}) > 1
    assert mixed, "control: a sink whose members differ in sign is served"
    assert all("members" not in e for e in env["rows"] if e["node_kind"] != "other")


# ── through the projector, to the card ───────────────────────────────────────────────────────

def test_the_members_reach_the_card_verbatim(post):
    status, env = post(FN_CA)
    assert status == 200, env
    ns = _fns()
    raw = [{"persona": "PROGRAM_FINANCE_ANALYST", "expert_response": env}]
    got = ns["_project_planning_archetype"]("FLOW_DECOMPOSITION", raw, "PROGRAM_FINANCE_ANALYST", None)
    assert got is not None and got["rows"] == env["rows"]
    assert [e["members"] for e in got["rows"] if "members" in e], "control: members were served to carry"


# ── the version is the pin ───────────────────────────────────────────────────────────────────

def test_a_row_pinned_to_the_old_version_is_refused_naming_both(monkeypatch, tmp_path):
    raw = yaml.safe_load((B_DIR / "measure_verbs" / f"{FN_CA}.yaml").read_text(encoding="utf-8"))
    assert raw["computation"]["version"] == vd.VERSION == "1.4.0"       # control: the real row is current
    raw["computation"]["version"] = "1.3.0"
    with pytest.raises(ValueError) as caught:
        _load_with(monkeypatch, tmp_path, raw, FN_CA)
    assert "'1.3.0'" in str(caught.value) and "'1.4.0'" in str(caught.value), str(caught.value)
