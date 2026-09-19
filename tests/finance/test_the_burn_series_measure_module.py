"""The third measure module — and it pays the debt the burn-rate findings commit recorded.

EXTRACTION RECORD, as commands rather than numbers (ADR-0053 §7):

    seal_path        tests/finance/test_engine_f_contracts.py
    seal_last_commit git log -1 --format=%h -- tests/finance/test_engine_f_contracts.py
    seal_age_days    git log -1 --format=%cd --date=short -- <that path>, against the run date

At this run (2026-09-14): `803071e`, dated 2026-09-02 — **twelve days**.

R-029 CHECK 1 found **six survivors**; five were real and are sealed in `b42ce8f`, recorded in
`docs/plans/the-burn-rate-figures-a-reader-acts-on-were-unsealed.md`.

R-029 CHECK 2, the equivalence run — pre-extraction verb from `git show HEAD:...` beside the new
one, program level plus six window shapes:

    cases: 7 | rows: 25 | fields unchanged: 300 | values moved: 0 | new fields: none

── THE DEBT THIS FILE PAYS ──────────────────────────────────────────────────────────────────
The sixth survivor — the skip rule's `and` turned to `or` — was an **equivalent mutant against
the reference seed**, which contains no period where exactly one of plan and spend is zero
(6 both-zero, 6 neither, **0 partly**). I recorded it rather than contriving a seed, and said
the extraction was what would make it testable.

**It is testable now, and `test_a_partly_zero_period_STILL_PRODUCES_A_ROW` is three lines**,
because this module takes quantities directly instead of reaching into state. That is the
argument for extraction beyond tidiness: **a rule becomes checkable by being lifted.**
"""
from __future__ import annotations

import pytest

from agent_fleet.finance_agent.measure_modules import burn_series as M

BAC = 1000.0


def _q(*rows):
    return [(f"P{i}", planned, burn) for i, (planned, burn) in enumerate(rows)]


def _build(*rows, bac=BAC):
    return M.build(_q(*rows), budget_at_completion=bac, scope_label="s", value_unit="USD")


def test_a_partly_zero_period_STILL_PRODUCES_A_ROW():
    """⚠ THE DEBT. `and`, never `or` — and the reference seed could not tell them apart.

    A period that PLANNED work and spent nothing is a stall, and it is the most interesting row
    on the chart. Dropping it would hide exactly what the series exists to show, and against
    the engine's seed that mistake was invisible: it has no partly-zero period at all.
    """
    rows = _build((100.0, 0.0), (0.0, 50.0), (0.0, 0.0), (100.0, 90.0))
    assert [r["period"] for r in rows] == ["P0", "P1", "P3"], (
        "a period with plan-and-no-spend, or spend-and-no-plan, was dropped"
    )


def test_a_period_with_NEITHER_produces_no_row():
    """The other half of the same rule. Nothing reported is not a period of zero activity."""
    assert _build((0.0, 0.0)) == []


def test_variance_to_plan_is_PLANNED_MINUS_BURN(  ):
    """Positive means spending BELOW plan. Flipped, over-plan reads as under-plan."""
    rows = _build((100.0, 60.0), (100.0, 140.0))
    assert rows[0]["variance_to_plan"] == 40.0     # under plan
    assert rows[1]["variance_to_plan"] == -40.0    # over plan


def test_budget_remaining_is_BAC_LESS_CUMULATIVE_BURN():
    """A remaining budget that ignores spend reports the full BAC forever, and the runway
    computed from it inherits the error."""
    rows = _build((100.0, 100.0), (100.0, 200.0), (100.0, 300.0))
    assert [r["budget_remaining"] for r in rows] == [900.0, 700.0, 400.0]


def test_the_trailing_rate_averages_the_LAST_THREE_burns_and_reports_its_window():
    """Three is declared, not tuned — and the window rides on the row so the figure can be
    argued with. A smoothed rate whose window is invisible cannot be checked."""
    rows = _build((0.0, 30.0), (0.0, 60.0), (0.0, 90.0), (0.0, 300.0))
    assert [r["trailing_periods"] for r in rows] == [1, 2, 3, 3]
    assert [r["trailing_rate"] for r in rows] == [30.0, 45.0, 60.0, 150.0]
    assert M.TRAILING_PERIODS == 3


def test_the_window_SLIDES_rather_than_growing():
    """The distinguishing case between 'last three' and 'all of them'.

    The fourth row's mean must drop the first burn. Averaging everything gives 120.0 here and
    the sliding window gives 150.0 — a fixture where the two agree cannot tell the mutations
    apart, which is why the numbers are chosen to diverge.
    """
    rows = _build((0.0, 30.0), (0.0, 60.0), (0.0, 90.0), (0.0, 300.0))
    assert rows[-1]["trailing_rate"] == 150.0        # (60+90+300)/3, the sliding window
    assert rows[-1]["trailing_rate"] != 120.0        # (30+60+90+300)/4, averaging everything


def test_the_runway_is_over_the_TRAILING_RATE_and_they_diverge_after_the_first_row():
    """A different denominator is a different forecast wearing the same name.

    ON THE FIRST ROW THEY ARE EQUAL BY ARITHMETIC — one period of history means the cumulative
    burn IS the trailing rate — so the property that makes the mutation detectable is that they
    diverge AT ALL, not that they differ everywhere. Requiring the latter is the
    over-constrained seal that fails against correct code.
    """
    rows = _build((0.0, 100.0), (0.0, 400.0))
    assert rows[0]["runway_periods"] == pytest.approx(900.0 / 100.0)
    assert rows[1]["runway_periods"] == pytest.approx(500.0 / 250.0)      # trailing mean
    assert rows[1]["runway_periods"] != pytest.approx(500.0 / 500.0)      # cumulative burn


def test_a_zero_rate_gives_NO_runway_rather_than_an_infinite_one():
    """Undefined, not unlimited. "Unlimited" is an assertion about solvency nobody made."""
    rows = _build((100.0, 0.0))
    assert rows[0]["trailing_rate"] == 0
    assert rows[0]["runway_periods"] is None


def test_the_accumulators_SEED_AT_INT_ZERO_so_a_Decimal_caller_works():
    """`0.0 + Decimal(...)` raises; `0 + Decimal(...)` does not.

    ONE CHARACTER, and it is the difference between a measure that lifts and one that does not
    — a float seed pins the module to float inputs while looking like a formatting choice.
    `index_series` shipped with that trap and its step-2 pass found it; this module was written
    with it fixed, so the seal is what keeps a later tidy-up from reintroducing it.
    """
    from decimal import Decimal

    rows = M.build([("P0", Decimal("100"), Decimal("60"))],
                   budget_at_completion=Decimal("1000"), scope_label="s")
    assert rows[0]["variance_to_plan"] == Decimal("40")
    assert isinstance(rows[0]["cum_burn"], Decimal)


def test_the_module_declares_a_version_and_imports_nothing_from_the_engine():
    """§1, checked structurally: a measure module importing engine state would still produce
    right figures, so the violation is invisible in a passing test."""
    import ast
    import pathlib

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
