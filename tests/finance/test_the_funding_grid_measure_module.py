"""The fifth measure module — and it pays the three debts `48ceed9` recorded.

EXTRACTION RECORD (ADR-0053 §7), as commands:

    seal_path        tests/finance/test_engine_f_contracts.py
    seal_last_commit git log -1 --format=%h -- tests/finance/test_engine_f_contracts.py
    seal_age_days    git log -1 --format=%cd --date=short -- <that path>, against the run date

R-029 CHECK 2, via `scripts/extraction_equivalence.py`: **0 shared-key values moved, no field
added or removed.**

── THE DEBTS THIS FILE PAYS ─────────────────────────────────────────────────────────────────
R-029's check on `fin_funding_status` found six survivors. Three were real and were sealed at
verb level in `48ceed9`. **Three were equivalent mutants against the reference seed**, and were
recorded rather than forced:

    the max(0, ...) floor on `shortfall`   — no line in the seed is over-obligated
    the `gap` / `shortfall` split          — same reason: the floor never engages
    the row ordering                       — the seed arrives already sorted

**All three are constructible now**, because this module takes cells as arguments instead of
reaching into state — an over-obligated line and an out-of-order series are one line each.
*A rule becomes checkable by being lifted*, fifth instance, and pinning them was owed by the
commit that lifted the verb.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agent_fleet.finance_agent.measure_modules import funding_grid as M

#: A verdict stub. The real one is the engine's judgement; what is under test here is the
#: arithmetic and the shape around it, so this returns something deterministic and legible.
def _verdict(authorized, obligated, expended):
    if expended >= authorized:
        return "met"
    if obligated >= authorized:
        return "pledged-not-firm"
    return "short"


_ORDER = {"P1": 1, "P2": 2, "P3": 3}


def _cells(*rows):
    return list(rows)


def test_an_OVER_OBLIGATED_line_floors_the_shortfall_but_not_the_gap():
    """⚠ DEBT ONE. The reference seed has no over-obligated line, so the floor never engaged
    and removing it was an equivalent mutant.

    Committing more than was authorised is a real condition. It is **not a negative
    shortfall** — so `shortfall` floors at zero and `gap` carries the signed figure beside it.
    **Two fields because one number cannot say both**, and with no over-obligated line in the
    fixture that distinction was pure assertion.
    """
    rows = M.build(_cells(("L1", "Line one", "P1", 100, 130, 90)),
                   verdict=_verdict, order=_ORDER.__getitem__)
    row = rows[0]
    assert row["shortfall"] == 0, "an over-obligated line has no shortfall, not a negative one"
    assert row["gap"] == -30, "the signed figure must survive the floor applied to its neighbour"
    assert row["unobligated_balance"] == -30


def test_a_NORMAL_line_gives_the_same_number_to_both(  ):
    """THE CONTROL for the pair above: where the floor does not engage, `shortfall` and `gap`
    agree — which is why the seed could not tell them apart, and why the over-obligated case is
    the only one that can."""
    rows = M.build(_cells(("L1", "Line one", "P1", 100, 60, 40)),
                   verdict=_verdict, order=_ORDER.__getitem__)
    assert rows[0]["shortfall"] == rows[0]["gap"] == 40


def test_at_risk_measures_against_SPEND_and_does_not_collapse_into_shortfall():
    """Exposure, not a funding gap. Against `obligated` the two become one number."""
    rows = M.build(_cells(("L1", "Line one", "P1", 100, 60, 25)),
                   verdict=_verdict, order=_ORDER.__getitem__)
    assert rows[0]["at_risk"] == 75          # authorised - expended
    assert rows[0]["shortfall"] == 40        # authorised - obligated
    assert rows[0]["at_risk"] != rows[0]["shortfall"]


def test_the_two_BALANCES_are_one_subtraction_apart_and_are_not_swapped():
    """`unobligated` is authorised−committed; `unexpended` is committed−spent. Both plausible
    under either name, and the field name gives no hint which operands it was taken over."""
    rows = M.build(_cells(("L1", "Line one", "P1", 100, 60, 25)),
                   verdict=_verdict, order=_ORDER.__getitem__)
    assert rows[0]["unobligated_balance"] == 40
    assert rows[0]["unexpended_balance"] == 35
    assert rows[0]["unobligated_balance"] != rows[0]["unexpended_balance"]


def test_OUT_OF_ORDER_cells_come_back_sorted_by_subject_then_period():
    """⚠ DEBT TWO. The seed arrives already sorted, so removing the sort entirely left every
    row where it was — an equivalent mutant.

    A grid renderer relies on the ordering, and a caller handing cells in arrival order must
    still get a grid. This is the fixture the seed could not provide.
    """
    rows = M.build(
        _cells(("L2", "Two", "P3", 10, 5, 1),
               ("L1", "One", "P2", 10, 5, 1),
               ("L2", "Two", "P1", 10, 5, 1),
               ("L1", "One", "P1", 10, 5, 1)),
        verdict=_verdict, order=_ORDER.__getitem__,
    )
    assert [(r["subject_id"], r["period"]) for r in rows] == [
        ("L1", "P1"), ("L1", "P2"), ("L2", "P1"), ("L2", "P3"),
    ]


def test_the_period_ORDER_is_the_callers_and_not_alphabetical():
    """Periods sort by the caller's key, not by string. `FY26-10` after `FY26-09` is only true
    by luck of formatting, and a fiscal calendar that wraps would break a lexical sort
    silently."""
    reversed_order = {"P1": 3, "P2": 2, "P3": 1}
    rows = M.build(
        _cells(("L1", "One", "P1", 10, 5, 1), ("L1", "One", "P3", 10, 5, 1)),
        verdict=_verdict, order=reversed_order.__getitem__,
    )
    assert [r["period"] for r in rows] == ["P3", "P1"]


def test_the_verdict_and_its_IPMDAR_name_are_declared_together():
    """Two vocabularies for one fact. Declared in one table so they cannot drift — each is what
    a different reader looks at."""
    for state, ipmdar in M.IPMDAR_NAME.items():
        rows = M.build(_cells(("L1", "One", "P1", 10, 5, 1)),
                       verdict=lambda *_: state, order=_ORDER.__getitem__)
        assert rows[0]["state"] == state
        assert rows[0]["funding_state"] == ipmdar


def test_an_unknown_verdict_RAISES_rather_than_emitting_a_cell_with_no_name():
    """A verdict the vocabulary does not carry would otherwise produce a row whose
    `funding_state` is missing — a cell a grid draws blank while reporting success."""
    with pytest.raises(KeyError):
        M.build(_cells(("L1", "One", "P1", 10, 5, 1)),
                verdict=lambda *_: "not-a-state", order=_ORDER.__getitem__)


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
