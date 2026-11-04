"""The flow-decomposition module (docs/plans/fin-variance-decomposition.md), on its own: pure,
Decimal, and conserving at every node, over a fixture with negative amounts.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_variance_decomposition_module.py
"""
from __future__ import annotations

import random
from decimal import Decimal

import pytest

from agent_fleet.finance_agent.measure_modules import variance_decomposition as vd

D = Decimal
ROOT = "R"
# A: shares of |139| are .72 .216 .036 .029; B: 50 and 1 (and a b2 that nets to zero); C: one child.
PATHS = [
    (("A", "a1", "x"), D("60")), (("A", "a1", "y"), D("40")), (("A", "a2", "p"), D("-30")),
    (("A", "a3", "p"), D("5")), (("A", "a4", "p"), D("-4")),
    (("B", "b1", "p"), D("50")), (("B", "b2", "p"), D("7")), (("B", "b2", "q"), D("-7")),
    (("B", "b3", "p"), D("1")),
    (("C", "c1", "x"), D("-20")),
]


def edges_of(paths=PATHS, threshold="0.05"):
    return vd.flow_edges(root=ROOT, paths=paths, other_threshold=D(threshold))


def signed(edges):
    return {tuple(e["target"]): e["sign"] * e["value"] for e in edges}


def assert_conserved(edges, paths):
    """At EVERY node that has edges out of it, its signed children (sink included) sum to its
    signed value, where a node's value is read from the edge INTO it (the root's from the input)."""
    value_of = signed(edges)
    value_of[(ROOT,)] = sum((a for _p, a in paths), D(0))
    sources = {tuple(e["source"]) for e in edges}
    assert (ROOT,) in sources
    for node in sources:
        kids = sum((e["sign"] * e["value"] for e in edges if tuple(e["source"]) == node), D(0))
        assert kids == value_of[node], node


def test_conservation_holds_at_every_node_with_negative_flows():
    edges = edges_of()
    assert any(e["sign"] == -1 for e in edges) and any(e["sign"] == 1 for e in edges)
    assert_conserved(edges, PATHS)
    assert len({tuple(e["source"]) for e in edges}) > 4   # several internal nodes, not just the root


@pytest.mark.parametrize("threshold", ["0", "0.05", "0.5", "0.99"])
def test_conservation_holds_at_every_threshold(threshold):
    assert_conserved(edges_of(threshold=threshold), PATHS)


def test_two_siblings_below_the_threshold_collapse_into_one_terminal_sink():
    edges = edges_of()
    under_a = [e for e in edges if e["source"] == [ROOT, "A"]]
    assert [e["target"][-1] for e in under_a] == ["a1", "a2", vd.OTHER_LABEL]
    sink = under_a[-1]
    assert (sink["value"], sink["sign"], sink["level"]) == (D("1"), 1, 2)   # +5 and -4, signed
    assert not [e for e in edges if e["source"] == [ROOT, "A", vd.OTHER_LABEL]]  # terminal
    assert not [e for e in edges if e["target"][:3] in ([ROOT, "A", "a3"], [ROOT, "A", "a4"])]


def test_a_lone_child_below_the_threshold_keeps_its_name():
    under_b = [e["target"][-1] for e in edges_of() if e["source"] == [ROOT, "B"]]
    assert under_b == ["b1", "b3"]           # b3 is 1/51 of B: below 0.05, but alone
    assert vd.OTHER_LABEL not in under_b


def test_a_zero_threshold_collapses_nothing():
    edges = edges_of(threshold="0")
    assert not [e for e in edges if e["target"][-1] == vd.OTHER_LABEL]
    assert {"a3", "a4"} <= {e["target"][-1] for e in edges}


def test_a_zero_net_child_gets_no_edge_and_its_subtree_goes_with_it():
    targets = {tuple(e["target"]) for e in edges_of()}
    assert (ROOT, "B", "b2") not in targets and (ROOT, "B", "b2", "p") not in targets


def test_a_parent_whose_children_sum_to_nothing_in_absolute_value_collapses_nothing():
    assert edges_of([(("A", "a"), D("0")), (("A", "b"), D("0"))]) == []


def test_nodes_are_paths_so_one_name_under_two_parents_stays_two_nodes():
    edges = edges_of()
    xs = [e for e in edges if e["target"][-1] == "x"]
    assert {tuple(e["target"]) for e in xs} == {(ROOT, "A", "a1", "x"), (ROOT, "C", "c1", "x")}
    assert signed(xs)[(ROOT, "C", "c1", "x")] == D("-20")


def test_edges_carry_exactly_source_target_value_sign_level():
    for e in edges_of():
        assert set(e) == {"source", "target", "value", "sign", "level"}
        assert isinstance(e["source"], list) and isinstance(e["target"], list)
        assert e["target"][:-1] == e["source"] and e["level"] == len(e["target"]) - 1
        assert e["value"] > 0 and e["sign"] in (1, -1)


def test_a_real_child_named_like_the_sink_is_refused_when_the_parent_also_gets_a_sink():
    clash = PATHS + [(("A", vd.OTHER_LABEL, "p"), D("500"))]
    with pytest.raises(ValueError, match=vd.OTHER_LABEL):
        edges_of(clash)
    # ...and is just a name where no sink is made
    ok = edges_of([(("B", vd.OTHER_LABEL, "p"), D("5"))])
    assert [e["target"] for e in ok if e["level"] == 2] == [[ROOT, "B", vd.OTHER_LABEL]]


def test_the_order_is_deterministic_whatever_the_input_order():
    want = edges_of()
    for seed in range(8):
        shuffled = list(PATHS)
        random.Random(seed).shuffle(shuffled)
        assert edges_of(shuffled) == want
    keys = [(e["level"], e["source"], -e["value"], e["target"]) for e in want]
    assert keys == sorted(keys)


def test_amounts_are_exact_decimals_with_no_float_in_the_way():
    tenths = [(("A", "a"), D("0.1")), (("A", "a"), D("0.2")), (("A", "b"), D("0.1")), (("A", "b"), D("0.2"))]
    edges = edges_of(tenths, threshold="0")
    assert [e["value"] for e in edges] == [D("0.6"), D("0.3"), D("0.3")]   # A, then a and b
    assert all(isinstance(e["value"], Decimal) for e in edges)


def test_the_module_is_versioned_and_names_no_case():
    import inspect
    src = inspect.getsource(vd)
    assert vd.VERSION == "1.0.0"
    import re
    for word in ("EAC", "WBS", "control account", "work package", "program", "cost"):
        assert not re.search(rf"b{word}", src, re.I), word
