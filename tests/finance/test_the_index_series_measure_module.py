"""The second measure module (ADR-0053 §1) — the index series, extracted from the indices verb.

EXTRACTION RECORD, the fields §7 requires, as COMMANDS rather than numbers:

    seal_path        tests/finance/test_engine_f_contracts.py
    seal_last_commit git log -1 --format=%h -- tests/finance/test_engine_f_contracts.py
    seal_age_days    git log -1 --format=%cd --date=short -- <that path>, against the run date

At this run (2026-09-14) that seal was `803071e`, dated 2026-09-02 — **twelve days old.**

── R-029 CHECK 1, RUN BEFORE THE MOVE, AND IT FOUND MORE THAN A TEST GAP ────────────────────
Mutating the unit in place first — *what does the standing seal actually assert about the thing
being moved* — found **two live wrong-answer paths**: a swapped CPI/SPI and a cumulative index
computed from the period figures, **both surviving the full suite**. Both change real values in
this seed, so neither is an equivalent mutant.

**Those were filed and sealed separately, in `501d6b0`, BEFORE this extraction.** A correctness
gap found during a refactor must not ride in the refactor's commit — it becomes invisible there.
`test_the_performance_indices_mean_what_they_say.py` is that work; this file is the module.

── R-029 CHECK 2: EQUIVALENCE, AND IT IS THE INSTRUMENT THAT DID NOT DECAY ──────────────────
The pre-extraction `fin_performance_indices` loaded from `git show HEAD:...` beside the new one,
both run over the same seed across the full matrix — program-level, every control account, and
four window shapes including a single period and a mid-series slice.

    cases: 10 | rows: 50 | DIFFS: 0
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agent_fleet.finance_agent.measure_modules import index_series as M


def _ratio(n, d):
    """The engine's rule: None where the denominator is zero, never 1.0 and never 0.0."""
    return (n / d) if d else None


def _q(*rows):
    return [(f"P{i}", *r) for i, r in enumerate(rows)]


def test_a_period_with_nothing_reported_produces_NO_ROW():
    """Deliberate-absent. A period with nothing reported is not a period of zero performance;
    a row there draws a point asserting the program stopped, which the data does not claim."""
    rows = M.build(_q((100.0, 90.0, 95.0), (0, 0, 0), (50.0, 50.0, 40.0)),
                   ratio=_ratio, scope_label="s")
    assert M.periods_present(rows) == ["P0", "P2"]


def test_a_period_that_is_only_PARTLY_zero_still_produces_a_row():
    """THE DISCRIMINATING CASE. The skip is for a period with NOTHING reported, not for one
    where a single quantity happens to be zero — a period that planned work and earned none is
    the most interesting row on the chart, and dropping it would hide exactly the failure the
    series exists to show."""
    rows = M.build(_q((100.0, 0.0, 0.0)), ratio=_ratio, scope_label="s")
    assert len(rows) == 1
    assert rows[0]["spi"] == 0.0        # earned nothing against a real plan
    assert rows[0]["cpi"] is None       # spent nothing: undefined, not perfect


def test_CPI_is_cost_and_SPI_is_schedule():
    """The mutation that survived the standing seal for twelve days. They say OPPOSITE things
    about what to do, and swapping them is undetectable by shape: both dimensionless, both
    near 1."""
    rows = M.build(_q((100.0, 90.0, 120.0)), ratio=_ratio, scope_label="s")
    assert rows[0]["cpi"] == pytest.approx(90.0 / 120.0)   # earned / actual COST
    assert rows[0]["spi"] == pytest.approx(90.0 / 100.0)   # earned / SCHEDULED
    assert rows[0]["cpi"] != rows[0]["spi"], "the fixture cannot tell a swap from a no-op"


def test_the_cumulative_indices_are_over_RUNNING_TOTALS_and_diverge_from_the_period_ones():
    """The other survivor. Undetectable while the two agree — which they do until the series
    has more than one row, which is why this fixture has three."""
    rows = M.build(_q((100.0, 100.0, 100.0), (100.0, 50.0, 100.0), (100.0, 50.0, 100.0)),
                   ratio=_ratio, scope_label="s")

    assert [r["cum_bcwp"] for r in rows] == [100.0, 150.0, 200.0]
    for r in rows:
        assert r["cum_cpi"] == pytest.approx(r["cum_bcwp"] / r["cum_acwp"])
    assert rows[1]["cpi"] != pytest.approx(rows[1]["cum_cpi"]), (
        "period and cumulative agree everywhere; computing one from the other would be "
        "undetectable and the assertion above cannot discriminate"
    )


def test_the_row_carries_the_quantities_its_ratios_were_TAKEN_OVER():
    """So a consumer can check the response against itself.

    This is what makes the swap detectable downstream without a second implementation of the
    verb: a response whose ratios disagree with the numbers printed beside them contradicts
    itself, and that is checkable by anyone holding the payload.
    """
    rows = M.build(_q((100.0, 90.0, 120.0)), ratio=_ratio, scope_label="s")
    row = rows[0]
    for key in ("bcws", "bcwp", "acwp", "cum_bcws", "cum_bcwp", "cum_acwp"):
        assert key in row
    assert row["cost_variance"] == pytest.approx(row["bcwp"] - row["acwp"])
    assert row["schedule_variance"] == pytest.approx(row["bcwp"] - row["bcws"])


def test_the_ratio_is_the_CALLERS_and_the_module_does_not_second_guess_it():
    """`ratio` is injected because `measures._ratio` has eleven call sites and is the engine's
    vocabulary. The module uses what it is handed — asserted by handing it something
    recognisable rather than by reading the source."""
    rows = M.build(_q((10.0, 10.0, 10.0)), ratio=lambda n, d: "MARKER", scope_label="s")
    assert rows[0]["cpi"] == "MARKER" and rows[0]["cum_spi"] == "MARKER"


def test_the_undefined_safe_precondition_can_be_CHECKED_before_building():
    """Injection buys one implementation and costs the guarantee it is the right one.

    A caller passing `truediv` gets a ZeroDivisionError; one passing a lambda returning 1.0
    gets a series quietly asserting perfect performance in periods where nothing was spent.
    """
    assert M.ratio_is_undefined_safe(_ratio) is True
    assert M.ratio_is_undefined_safe(lambda n, d: n / d) is False      # raises
    assert M.ratio_is_undefined_safe(lambda n, d: 1.0) is False        # the dangerous one


def test_the_engines_OWN_ratio_satisfies_the_precondition():
    """The check above proves the predicate works; this proves the real caller passes it.

    Without this pair the precondition is a function nobody's actual dependency is measured
    against — a guard tested only on fixtures of itself.
    """
    from agent_fleet.finance_agent import measures

    assert M.ratio_is_undefined_safe(measures._ratio) is True


def test_the_module_declares_a_version_and_performs_NO_IO():
    """§1's hard requirements, the second checked STRUCTURALLY from the module's own AST.

    A measure module that imports engine state would still produce right figures, so the
    violation is invisible in a passing test and has to be checked another way.
    """
    assert M.VERSION == "1.0.0"

    tree = ast.parse(pathlib.Path(M.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    forbidden = [n for n in imported if any(
        bad in n for bad in ("entities", "seed", "state", "agent_fleet", "requests",
                             "httpx", "neo4j", "urllib", "datetime", "time", "random", "os"))]
    assert not forbidden, f"a measure module may carry no engine dependency; imports {forbidden}"
