"""The first measure module (ADR-0053 §1), and the contract that makes it one.

EXTRACTION RECORD — the fields ADR-0053 §7 requires, as COMMANDS rather than as numbers,
because a typed age is stale the day after it is typed:

    seal_path        tests/finance/test_engine_f_contracts.py
    seal_last_commit git log -1 --format=%h -- tests/finance/test_engine_f_contracts.py
    seal_age_days    git log -1 --format=%cd --date=short -- <that path>, against the run date

**AT THE RUN (2026-09-12) THAT SEAL WAS `803071e`, DATED 2026-09-02 — TEN DAYS OLD, in a tree
81 commits had landed in since this lane last merged.** Recorded plainly because it weakens
the claim: ADR-0053 §7 says the untouched-assertion argument decays with time, and *"written
before either change" stops implying "unchanged"*. It does not flip the order — a drifted seal
is still a better baseline than one rewritten for the occasion — but a reader cannot tell a
ten-day-old instrument from a fresh one unless the number is there.

**SO THE EXTRACTION WAS CHECKED TWICE, and the second check is the stronger one.** The old
`fin_variance_drivers` was loaded from `git show HEAD:...` alongside the new one and both were
run over the same seed across the full parameter matrix — 2 variance kinds × 2 levels × 5
`top_n` values. **20 cases, 42 rows, byte-identical JSON, 0 diffs.** That is equivalence
against the code itself rather than against an assertion about it, and it does not decay.

── A CORRECTION TO ADR-0053 §7, FOUND BY MUTATING THE EXTRACTED MODULE ──────────────────────
§7's argument for extraction-first is that *"the existing seal — written before either change,
already battle-tested — is the check."* **For this verb it was not a check of the extracted
behaviour at all.** Five mutations were run against the module — sort by raw value instead of
absolute, keep zero contributors, annotate only the last row with the withheld tail, return 0
instead of None for an undefined share, rank from 0 — and **every one of them reddened exactly
one test, always a test in THIS file.** The standing seal stayed green through all five.

It exercises `fin_variance_drivers` (two call sites) and asserts its contract shape; it never
asserted the ordering, the zero-drop, the rank numbering, or the withheld tail. **So the green
before and after was real and weak**: it proved the verb still runs and still answers in the
declared shape, not that the ranking survived.

**This does not flip the order — extraction-first is still right.** It corrects the stated
REASON: the instrument that established behaviour-preservation here was the purpose-built
equivalence run, and the standing seal was a smoke test. The next extraction should check what
its seal actually asserts about the unit being moved, rather than inheriting §7's claim that
it is covered. **A seal that exercises a function is not a seal that pins its algorithm.**
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agent_fleet.finance_agent.measure_modules import variance_driver_ranking as M


def _rows(*contributions):
    return [{"entity_id": f"e{i}", "contribution": c} for i, c in enumerate(contributions)]


def test_a_contributor_of_nothing_is_dropped_not_ranked_last():
    """Zero is not a small driver. It is not one."""
    out = M.rank_drivers(_rows(5.0, 0.0, -3.0), top_n=10)
    assert [r["entity_id"] for r in out] == ["e0", "e2"]


def test_ordering_is_by_ABSOLUTE_contribution_with_the_sign_left_on_the_row():
    """Favourable contributors rank too, and that is not a completeness gesture.

    Ranking only the unfavourable rows produces a list whose magnitudes sum to MORE than the
    variance they claim to explain, and a reader doing the obvious arithmetic finds the
    numbers do not add up.
    """
    out = M.rank_drivers(_rows(-10.0, 40.0, -25.0), top_n=10)
    assert [r["contribution"] for r in out] == [40.0, -25.0, -10.0]
    assert [r["rank"] for r in out] == [1, 2, 3]


def test_the_withheld_tail_is_declared_on_EVERY_returned_row():
    """`top_n` hiding contributors without saying so is a partial list that looks complete.

    ON EVERY ROW, not just the last: a consumer reading one row must be able to tell the
    ranking is a window. The sum is of the withheld CONTRIBUTIONS, signed — not their
    magnitudes — so it reconciles against the total the way the ranked rows do.
    """
    out = M.rank_drivers(_rows(10.0, 8.0, -5.0, 2.0), top_n=2)
    assert [r["contribution"] for r in out] == [10.0, 8.0]
    for row in out:
        assert row["withheld_contributors"] == 2
        assert row["withheld_contribution"] == pytest.approx(-3.0)


def test_no_withheld_fields_when_nothing_was_withheld():
    """Absence means nothing was hidden. A zero would be a third state a reader must decode,
    and one consumer checking presence and another checking truthiness would disagree."""
    out = M.rank_drivers(_rows(10.0, 8.0), top_n=5)
    assert all("withheld_contributors" not in r for r in out)


def test_share_of_total_is_NONE_on_a_zero_total_rather_than_zero():
    """A variance of zero has no contributors-as-a-proportion. The ratio is undefined, not
    "nobody contributed" — and a card would draw either substitute as a real share."""
    assert M.share_of_total(5.0, 0) is None
    assert M.share_of_total(5.0, 0.0) is None
    assert M.share_of_total(5.0, 20.0) == pytest.approx(0.25)


def test_top_n_below_one_is_refused_by_the_module_in_ITS_OWN_exception_type():
    """A measure module may not depend on engine exception types (§1).

    The VERB keeps its own `NotInModel` guard with its own message, so the caller-facing
    refusal is unchanged by the extraction — this is the module defending its own contract
    against a direct caller, which is a different audience.
    """
    with pytest.raises(ValueError):
        M.rank_drivers(_rows(1.0), top_n=0)


def test_the_module_declares_a_version_that_is_its_OWN():
    """§1: the version is the module's, not the engine's. Bumping it is a claim that the
    figures may change — which is why 1.0.0 is correct for an extracted-unchanged unit."""
    assert M.VERSION == "1.0.0"


def test_the_module_performs_NO_IO_AND_IMPORTS_NOTHING_FROM_THE_ENGINE():
    """§1's hard requirement, checked STRUCTURALLY rather than trusted to review.

    A measure module that imports engine state, the seed, or the entity types has a
    dependency the contract forbids, and the violation is invisible in a passing test — the
    figures would still be right. So this reads the module's own AST.

    DERIVED FROM THE SOURCE, not from a list of banned names I remembered: any import naming
    the engine package or its known-stateful siblings fails, so a module that starts reading
    the graph tomorrow fails on the import rather than at a review nobody schedules.
    """
    src = pathlib.Path(M.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    forbidden = [
        name for name in imported
        if any(bad in name for bad in
               ("entities", "seed", "state", "agent_fleet", "requests", "httpx",
                "neo4j", "urllib", "datetime", "time", "random", "os"))
    ]
    assert not forbidden, (
        f"a measure module must perform no I/O and carry no engine dependency; this one "
        f"imports {forbidden}"
    )
