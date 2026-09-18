"""The sixth and last measure module — and it pays the two debts `7e2f8a5` recorded.

R-029 CHECK 2, via `scripts/extraction_equivalence.py`: **0 shared-key values moved, no field
added or removed.**

── THE DEBTS ────────────────────────────────────────────────────────────────────────────────
R-029's check on `fin_variance_analysis` found four survivors, and **three were equivalent
mutants against the reference seed**: the materiality floor never fires there and the depth
limit is never reached — measured, stop reasons `{decomposed: 4, leaf: 3}`, with **no
`explained` and no `depth`.**

Those are the two rules the verb's docstring argues for at greatest length — *"materiality IS A
FRACTION OF THE ROOT VARIANCE, not of the parent's"* and *"a truncated tree that looks complete
is the failure this field exists to prevent"* — and **nothing but prose asserted either**.

Both are one call to construct now. *A rule becomes checkable by being lifted*, sixth instance.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agent_fleet.finance_agent.measure_modules import decomposition_policy as M


def _child(entity_id, variance):
    return {"entity_id": entity_id, "variance": variance}


# ── THE DEPTH LIMIT — unreachable in the seed ────────────────────────────────────────────────

def test_a_node_at_the_LIMIT_stops_with_depth_and_says_so():
    """⚠ DEBT ONE. No node in the reference seed reaches the limit, so mis-reporting this
    reason — or moving the limit by one — changed nothing there."""
    assert M.stop_reason(has_children=True, variance=100, floor=1,
                         depth=3, max_depth=3) == "depth"


def test_the_limit_is_INCLUSIVE_so_off_by_one_is_visible():
    """`depth >= max_depth`, not `>`. One level either side of the boundary, which is the only
    arrangement that can tell the two comparisons apart."""
    assert M.stop_reason(has_children=True, variance=100, floor=1,
                         depth=2, max_depth=3) == "decomposed"
    assert M.stop_reason(has_children=True, variance=100, floor=1,
                         depth=3, max_depth=3) == "depth"


def test_a_LEAF_is_reported_as_a_leaf_even_at_the_depth_limit():
    """ORDER IS THE POLICY. A leaf is a fact about the model; reporting it as `depth` would
    blame the limit for the data's shape, and a reader would widen the limit expecting more."""
    assert M.stop_reason(has_children=False, variance=100, floor=1,
                         depth=9, max_depth=3) == "leaf"


def test_an_IMMATERIAL_node_stops_as_explained_even_below_the_depth_limit():
    """The second test in the order, ahead of `depth`, so a node that was going to stop anyway
    is not reported as truncated."""
    assert M.stop_reason(has_children=True, variance=5, floor=100,
                         depth=0, max_depth=9) == "explained"


def test_every_reason_stop_reason_can_return_is_DECLARED():
    """A reason absent from the vocabulary is one a consumer cannot switch on."""
    produced = {
        M.stop_reason(has_children=False, variance=1, floor=0, depth=0, max_depth=9),
        M.stop_reason(has_children=True, variance=1, floor=100, depth=0, max_depth=9),
        M.stop_reason(has_children=True, variance=100, floor=1, depth=3, max_depth=3),
        M.stop_reason(has_children=True, variance=100, floor=1, depth=0, max_depth=9),
    }
    assert produced == set(M.STOP_REASONS)


# ── THE MATERIALITY FLOOR — also unreachable in the seed ─────────────────────────────────────

def test_the_floor_is_a_fraction_of_the_ROOT_and_not_of_the_parent():
    """⚠ DEBT TWO, and the rule the docstring argues hardest for.

    Against the PARENT, a 1,000 variance inside a 2,000 account is 50% and drills. Against the
    ROOT it is noise. **The root is the question that was asked, so the root is the scale that
    matters** — a parent-relative floor drills deepest exactly where the amounts are smallest.
    """
    assert M.materiality_floor(-1_130_000, 0.05) == pytest.approx(56_500)
    assert M.materiality_floor(1_130_000, 0.05) == pytest.approx(56_500), (
        "the floor is an ABSOLUTE magnitude; a negative root must not invert it"
    )

    # The parent-relative reading, shown failing to be what this computes.
    parent_relative = abs(2_000) * 0.05
    assert M.materiality_floor(-1_130_000, 0.05) != parent_relative


def test_an_IMMATERIAL_contributor_is_dropped_and_its_value_becomes_the_RESIDUAL():
    """Contributors that do not sum to their parent's variance is the arithmetic lie this
    engine is most likely to tell — a reader adds the rows, finds they fall short, and cannot
    tell whether something was hidden or the maths is wrong."""
    kids = [_child("big", 900), _child("small", 40), _child("tiny", 10)]
    material, residual = M.partition(kids, variance=950, floor=100)

    assert [c["entity_id"] for c in material] == ["big"]
    assert residual == 50, "the residual must account for every dropped contributor"
    assert M.immaterial_count(kids, material) == 2


def test_the_residual_is_ZERO_when_nothing_was_dropped():
    """So a caller can test it rather than comparing lengths, and an absent residual means
    absent rather than unknown."""
    kids = [_child("a", 500), _child("b", 450)]
    material, residual = M.partition(kids, variance=950, floor=100)
    assert len(material) == 2 and residual == 0


def test_the_floor_is_on_the_MAGNITUDE_so_a_large_favourable_child_survives():
    """A +900 contributor inside a -1,000 root is material. Comparing the signed value against
    a positive floor would drop every favourable contributor — and those are precisely the rows
    that explain why a variance is smaller than its worst component."""
    kids = [_child("favourable", 900), _child("noise", 10)]
    material, residual = M.partition(kids, variance=-100, floor=100)
    assert [c["entity_id"] for c in material] == ["favourable"]
    assert residual == -1000


# ── SHARE OF ROOT ────────────────────────────────────────────────────────────────────────────

def test_share_of_root_is_NODE_OVER_ROOT_and_None_on_a_zero_root():
    assert M.share_of_root(-565_000, -1_130_000) == pytest.approx(0.5)
    assert M.share_of_root(100, 0) is None, (
        "a decomposition of nothing has no shares; every substitute is a proportion nobody "
        "computed"
    )


def test_a_favourable_contributor_in_an_unfavourable_root_has_TWO_DISAGREEING_SIGNS():
    """Positive variance, negative share — **and both are correct**, which is why the producer
    emits a `favourable` verdict rather than letting a card colour from either."""
    assert M.share_of_root(120_000, -1_130_000) < 0


def test_the_module_declares_a_version_and_imports_nothing_from_the_engine():
    assert M.VERSION == "1.0.0"
    tree = ast.parse(pathlib.Path(M.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    bad = [n for n in imported if any(x in n for x in
           ("entities", "seed", "state", "agent_fleet", "requests", "httpx", "neo4j",
            "urllib", "datetime", "time", "random", "os"))]
    assert not bad, f"a measure module may carry no engine dependency; imports {bad}"
