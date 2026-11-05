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
SIGN = {"positive": 1, "negative": -1, "zero": 0}
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
    return {tuple(e["target"]): SIGN[e["sign"]] * e["value"] for e in edges}


def assert_conserved(edges, paths):
    """At EVERY node that has edges out of it, its signed children (sink included) sum to its
    signed value, where a node's value is read from the edge INTO it: the root's too, from the root
    edge, which must carry the input's total."""
    value_of = signed(edges)
    assert value_of[(ROOT,)] == sum((a for _p, a in paths), D(0))
    sources = {tuple(e["source"]) for e in edges if e["source"] is not None}
    assert (ROOT,) in sources
    for node in sources:
        kids = sum((SIGN[e["sign"]] * e["value"] for e in edges if tuple(e["source"] or ()) == node), D(0))
        assert kids == value_of[node], node


def test_conservation_holds_at_every_node_with_negative_flows():
    edges = edges_of()
    assert any(e["sign"] == "negative" for e in edges) and any(e["sign"] == "positive" for e in edges)
    assert_conserved(edges, PATHS)
    assert len({tuple(e["source"] or ()) for e in edges}) > 4   # several internal nodes, not just the root


@pytest.mark.parametrize("threshold", ["0", "0.05", "0.5", "0.99"])
def test_conservation_holds_at_every_threshold(threshold):
    assert_conserved(edges_of(threshold=threshold), PATHS)


def test_two_siblings_below_the_threshold_collapse_into_one_terminal_sink():
    edges = edges_of()
    under_a = [e for e in edges if e["source"] == [ROOT, "A"]]
    assert [e["target"][-1] for e in under_a] == ["a1", "a2", vd.OTHER_LABEL]
    sink = under_a[-1]
    assert (sink["value"], sink["sign"], sink["level"]) == (D("1"), "positive", 2)   # +5 and -4, signed
    assert not [e for e in edges if e["source"] == [ROOT, "A", vd.OTHER_LABEL]]  # terminal
    assert not [e for e in edges if e["target"][:3] in ([ROOT, "A", "a3"], [ROOT, "A", "a4"])]


def test_a_lone_child_below_the_threshold_keeps_its_name():
    under_b = [e["target"][-1] for e in edges_of() if e["source"] == [ROOT, "B"]]
    assert under_b == ["b1", "b3", "b2"]     # b3 is 1/51 of B: below 0.05, but alone (b2 is zero: outside)
    assert vd.OTHER_LABEL not in under_b


def test_a_zero_threshold_collapses_nothing():
    edges = edges_of(threshold="0")
    assert not [e for e in edges if e["target"][-1] == vd.OTHER_LABEL]
    assert {"a3", "a4"} <= {e["target"][-1] for e in edges}


def test_a_zero_net_child_is_emitted_at_zero_and_its_offsetting_children_hang_below_it():
    by_target = {tuple(e["target"]): e for e in edges_of()}
    b2 = by_target[(ROOT, "B", "b2")]
    assert (b2["value"], b2["sign"], b2["node_kind"], b2["level"]) == (D("0"), "zero", "item", 2)
    assert (by_target[(ROOT, "B", "b2", "p")]["sign"], by_target[(ROOT, "B", "b2", "p")]["value"]) == ("positive", D("7"))
    assert (by_target[(ROOT, "B", "b2", "q")]["sign"], by_target[(ROOT, "B", "b2", "q")]["value"]) == ("negative", D("7"))


def test_sign_is_one_of_three_words_and_zero_only_where_the_value_is_zero():
    edges = edges_of()
    assert {e["sign"] for e in edges} == {"positive", "negative", "zero"}
    assert all((e["sign"] == "zero") == (e["value"] == 0) for e in edges)


def test_zero_children_are_never_collapsed_and_do_not_make_up_the_two_below_count():
    # Under P: 100, 1 (below 0.05 of 101, alone), and two zeros. The zeros are not "below", so the
    # lone small child is still alone and keeps its name, and no sink is made.
    paths = [(("P", "big"), D("100")), (("P", "small"), D("1")),
             (("P", "z1"), D("0")), (("P", "z2"), D("0"))]
    edges = edges_of(paths)
    assert [e["target"][-1] for e in edges if e["source"] == [ROOT, "P"]] == ["big", "small", "z1", "z2"]
    assert not [e for e in edges if e["node_kind"] == "other"]
    # and the zeros stay out of the share total: small is 1/101, not 1/(101 + 2 x anything)
    assert_conserved(edges, paths)


def test_a_sink_whose_siblings_net_to_zero_is_emitted_with_sign_zero():
    paths = [(("P", "big"), D("100")), (("P", "s1"), D("2")), (("P", "s2"), D("-2"))]
    edges = edges_of(paths, threshold="0.05")
    (sink,) = [e for e in edges if e["node_kind"] == "other"]
    assert (sink["value"], sink["sign"], sink["source"]) == (D("0"), "zero", [ROOT, "P"])
    assert_conserved(edges, paths)


def test_conservation_holds_at_every_node_including_the_zero_ones():
    edges = edges_of()
    zero_nodes = {tuple(e["target"]) for e in edges if e["sign"] == "zero"}
    assert zero_nodes
    assert zero_nodes <= {tuple(e["source"] or ()) for e in edges}   # a zero node here has children to reconcile
    assert_conserved(edges, PATHS)


def test_a_parent_whose_children_sum_to_nothing_in_absolute_value_collapses_nothing():
    edges = edges_of([(("A", "a"), D("0")), (("A", "b"), D("0"))])
    assert [(e["target"][-1], e["sign"]) for e in edges] == [
        (ROOT, "zero"), ("A", "zero"), ("a", "zero"), ("b", "zero")]


def test_nodes_are_paths_so_one_name_under_two_parents_stays_two_nodes():
    edges = edges_of()
    xs = [e for e in edges if e["target"][-1] == "x"]
    assert {tuple(e["target"]) for e in xs} == {(ROOT, "A", "a1", "x"), (ROOT, "C", "c1", "x")}
    assert signed(xs)[(ROOT, "C", "c1", "x")] == D("-20")


def test_edges_carry_exactly_source_target_value_sign_level_node_kind():
    for e in edges_of():
        assert set(e) == {"source", "target", "value", "sign", "level", "node_kind"}
        assert isinstance(e["target"], list) and e["level"] == len(e["target"]) - 1
        if e["source"] is None:                       # the root edge
            assert e["target"] == [ROOT]
            continue
        assert isinstance(e["source"], list) and e["target"][:-1] == e["source"]
        assert e["value"] >= 0 and e["sign"] in ("positive", "negative", "zero")


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


@pytest.mark.parametrize("paths, value, sign", [
    (PATHS, None, None),
    ([(("A",), D("-30")), (("B",), D("10"))], D("20"), "negative"),
    ([(("A",), D("5")), (("B",), D("-5"))], D("0"), "zero"),
])
def test_the_root_has_one_edge_from_null_carrying_the_net_total(paths, value, sign):
    edges = edges_of(paths)
    roots = [e for e in edges if e["source"] is None]
    assert len(roots) == 1 and edges[0] is roots[0]                # one, and first in the order
    total = sum((a for _p, a in paths), D(0))
    assert (roots[0]["target"], roots[0]["level"], roots[0]["node_kind"]) == ([ROOT], 0, "item")
    assert roots[0]["value"] == abs(total) and SIGN[roots[0]["sign"]] * roots[0]["value"] == total
    if value is not None:
        assert (roots[0]["value"], roots[0]["sign"]) == (value, sign)
    assert [e for e in edges if e["target"] == [ROOT]] == roots   # no other edge reaches the root


def test_no_paths_is_no_edges_not_a_root_at_zero():
    assert edges_of([]) == []


def test_amounts_are_exact_decimals_with_no_float_in_the_way():
    tenths = [(("A", "a"), D("0.1")), (("A", "a"), D("0.2")), (("A", "b"), D("0.1")), (("A", "b"), D("0.2"))]
    edges = edges_of(tenths, threshold="0")
    assert [e["value"] for e in edges] == [D("0.6"), D("0.6"), D("0.3"), D("0.3")]   # root, A, a, b
    assert all(isinstance(e["value"], Decimal) for e in edges)


def test_the_module_is_versioned_and_names_no_case():
    import inspect
    src = inspect.getsource(vd)
    assert vd.VERSION == "1.3.0"
    import re
    for word in ("EAC", "WBS", "control account", "work package", "program", "cost"):
        assert not re.search(rf"b{word}", src, re.I), word


def test_every_edge_has_a_node_kind_and_the_sinks_are_exactly_the_other_edges():
    edges = edges_of()
    assert {e["node_kind"] for e in edges} <= {"item", "other"}
    sinks = [e for e in edges if e["target"][-1] == vd.OTHER_LABEL]
    others = [e for e in edges if e["node_kind"] == "other"]
    assert sinks and sinks == others
    assert all(e["target"][-1] == vd.OTHER_LABEL for e in others)
    assert all(e["target"][-1] != vd.OTHER_LABEL for e in edges if e["node_kind"] == "item")


def test_a_lone_child_below_the_threshold_is_an_item():
    (b3,) = [e for e in edges_of() if e["target"][-1] == "b3"]
    assert b3["node_kind"] == "item"


def test_a_zero_threshold_makes_no_other_edge():
    assert not [e for e in edges_of(threshold="0") if e["node_kind"] == "other"]
