"""The fourth measure module — and the first to carry §2a's ABSOLUTE TRANSCRIPTION SEAL.

EXTRACTION RECORD (ADR-0053 §7), as commands:

    seal_path        tests/finance/test_engine_f_contracts.py
    seal_last_commit git log -1 --format=%h -- tests/finance/test_engine_f_contracts.py
    seal_age_days    git log -1 --format=%cd --date=short -- <that path>, against the run date

R-029 CHECK 1 found **five of six mutations surviving** — the worst rate of the five verbs, with
`BAC * CPI` reversing the sign of the forecast. Filed and sealed separately in `9f2d4bb`.

R-029 CHECK 2, via `scripts/extraction_equivalence.py`: **54 shared-key values unchanged, 0
moved, no field added or removed**, over all three methods.

── WHAT THIS FILE ADDS THAT THE VERB-LEVEL SEALS COULD NOT ──────────────────────────────────
ADR-0053 §2a requires each method row to carry an **absolute transcription seal** against the
clause it cites. **`test_each_FORMULA_string_computes_what_the_module_computes` is that seal**:
it takes the published formula text, substitutes the quantities, evaluates it, and compares
against the function.

**The formula string stops being documentation and becomes the check.** A row naming a method
and a version then names something a reader can verify against a standard, rather than a label
— and §5 makes that string travel with every figure, so the label is what gets trusted.

This could only be written after the lift: at verb level the formula and the arithmetic were
in one function with state access around them, and nothing could hand the pair a controlled set
of quantities. **A rule becomes checkable by being lifted** — fourth instance.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agent_fleet.finance_agent.measure_modules import eac_formulas as M

QUANTITIES = dict(bac=12_000_000.0, bcwp=6_300_000.0, acwp=7_430_000.0)


def _ratio(n, d):
    return (n / d) if d else None


CPI = _ratio(QUANTITIES["bcwp"], QUANTITIES["acwp"])
SPI = 0.913


@pytest.mark.parametrize("method", sorted(M.FORMULA))
def test_each_FORMULA_string_computes_what_the_module_computes(method):
    """§2a's ABSOLUTE TRANSCRIPTION SEAL — the published formula IS the check.

    The formula text is parsed and evaluated against the same quantities the module is given,
    and the two must agree. A relative check across methods cannot do this: `fin_eac_comparison`
    compares the three methods' spread and **did not catch `BAC * CPI`**, because multiplying
    preserved the ordering.

    THE SUBSTITUTION IS DELIBERATELY DUMB — uppercase names to values, then `eval`. Anything
    cleverer would start re-implementing the formula, and a transcription seal that re-derives
    its subject is the two-copies-of-one-instrument shape.
    """
    expression = M.FORMULA[method].split("=", 1)[1].strip()
    env = {"BAC": QUANTITIES["bac"], "BCWP": QUANTITIES["bcwp"],
           "ACWP": QUANTITIES["acwp"], "CPI": CPI, "SPI": SPI}

    # PARSED BEFORE EVALUATION so a formula containing anything but arithmetic over the five
    # declared names fails loudly rather than executing.
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id in env, f"{method}: formula names {node.id!r}, which is not a quantity"
        else:
            assert isinstance(node, (ast.Expression, ast.BinOp, ast.Load, ast.Add, ast.Sub,
                                     ast.Mult, ast.Div, ast.Constant)), (
                f"{method}: formula contains {type(node).__name__}, which is not arithmetic"
            )

    transcribed = eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, env)
    computed = M.estimate_at_completion(method, cpi=CPI, spi=SPI, **QUANTITIES)
    assert computed == pytest.approx(transcribed), (
        f"{method}: the module computes {computed}, its published formula "
        f"{M.FORMULA[method]!r} gives {transcribed}"
    )


def test_the_CPI_formula_DIVIDES_and_the_fixture_can_tell(  ):
    """The inversion, pinned directly as well as through the transcription.

    Two seals for one property because the transcription would also pass if BOTH the formula
    string and the code were changed together — a consistent lie. This one asserts the
    DIRECTION against the standard as a human states it.
    """
    assert CPI < 1.0, "the fixture no longer shows an overrun; the direction is untested"
    computed = M.estimate_at_completion("CPI", cpi=CPI, spi=SPI, **QUANTITIES)
    assert computed > QUANTITIES["bac"], (
        "with CPI below one the forecast must EXCEED the budget; multiplying would lower it "
        "and reverse the finding"
    )


def test_REQUIRES_INDEX_agrees_with_what_each_method_actually_does():
    """THE JOIN between the registry datum and the behaviour it describes.

    §2 wants `requires_index` as DATA so a refusal's reachability is a property of the rows
    rather than something found by reading code — which is how an unreachable "every method
    undefined" refusal came to be written here. A datum that can disagree with the code is
    worse than none: it is a false claim with a registry behind it.
    """
    for method, requires in M.REQUIRES_INDEX.items():
        answered = M.estimate_at_completion(
            method, cpi=None, spi=None, **QUANTITIES
        )
        if requires:
            assert answered is None, f"{method} claims to need an index but answered without one"
        else:
            assert answered is not None, f"{method} claims to need no index but refused"


def test_an_undefined_index_gives_NONE_and_never_a_number():
    """With no performance reported there is no index to project forward, and every substitute
    figure would be an invention."""
    for bad in (None, 0, 0.0):
        assert M.estimate_at_completion("CPI", cpi=bad, spi=SPI, **QUANTITIES) is None


def test_an_unknown_method_is_REFUSED_rather_than_falling_through_to_one_of_them():
    """The original had `else: # CPI_SPI` — an unknown method would have been silently
    computed as CPI_SPI. Registry rows make unknown method names reachable input, so the
    fall-through becomes a wrong answer with a name on it."""
    with pytest.raises(ValueError):
        M.estimate_at_completion("NOT_A_METHOD", cpi=CPI, spi=SPI, **QUANTITIES)


def test_the_derived_figures_answer_their_own_questions():
    """`vac` NEGATIVE means overrun; `etc` is measured from what has been SPENT; and
    `percent_complete` is earned over BUDGET, not over spend."""
    eac = M.estimate_at_completion("CPI", cpi=CPI, spi=SPI, **QUANTITIES)
    out = M.derived(eac, ratio=_ratio, **QUANTITIES)

    assert out["vac"] == pytest.approx(QUANTITIES["bac"] - eac)
    assert out["vac"] < 0, "the fixture no longer overruns, so a flipped sign is undetectable"
    assert out["etc"] == pytest.approx(eac - QUANTITIES["acwp"])
    assert out["percent_complete"] == pytest.approx(
        QUANTITIES["bcwp"] / QUANTITIES["bac"]
    )
    assert QUANTITIES["acwp"] != QUANTITIES["bcwp"], "ETC's origin would be undetectable"


def test_every_declared_method_has_a_formula_and_an_index_flag():
    """DERIVED FROM ONE SET OF KEYS, so a sixth method cannot be added to one table and
    forgotten in the other — the drift a registry replaces a Literal to prevent."""
    assert set(M.FORMULA) == set(M.REQUIRES_INDEX)


def test_the_module_declares_a_version_and_imports_nothing_from_the_engine():
    assert M.VERSION == "1.0.0"
    tree = ast.parse(pathlib.Path(M.__file__).read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    bad = [n for n in imported if any(x in n for x in
           ("entities", "seed", "state", "agent_fleet", "requests", "httpx", "neo4j",
            "urllib", "datetime", "time", "random", "os"))]
    assert not bad, f"a measure module may carry no engine dependency; imports {bad}"


def test_the_COMPARISON_verb_agrees_with_this_module_on_every_method():
    """⚠ THE FORMULAS LIVE IN TWO PLACES, AND NOTHING ASSERTED THEY AGREE.

    `fin_eac_comparison` carries its own `compute(method)` reimplementing all three formulas in
    Decimal, independent of the module `fin_eac_calculation` now uses. They agree today —
    checked before this was written, so this seal is pinning a true state rather than reporting
    a defect.

    **THE DUPLICATION MATTERS BECAUSE OF §2a.** The transcription seal above makes the
    PUBLISHED FORMULA the check for `eac_formulas`. The comparison verb does not use that
    module, so its figures — the three a customer sees side by side — are not covered by it. A
    registry row would make `eac_formulas` authoritative while the comparison verb went on
    computing from a copy nobody transcribed.

    **This is the join, and it is the cheap half.** The durable fix is for the comparison verb
    to CALL the module, which §2 requires anyway ("runs every registered method and no
    unregistered one") and which is recorded as its own item rather than done inside an
    extraction.
    """
    from decimal import Decimal

    from agent_fleet.finance_agent import measures as engine
    from agent_fleet.finance_agent.seed import build_seed

    state = build_seed()
    compared = {r["method"]: r for r in engine.fin_eac_comparison(state,
                                                                  program_id="NP-MERIDIAN")}
    assert set(compared) == set(M.FORMULA), (
        f"the comparison verb reports {sorted(compared)}, the module declares "
        f"{sorted(M.FORMULA)} — a method in one and not the other is invisible to both"
    )

    for method, row in compared.items():
        if row.get("eac") is None:
            continue
        direct = engine.fin_eac_calculation(state, program_id="NP-MERIDIAN", method=method)
        assert abs(Decimal(str(row["eac"])) - Decimal(str(direct[0]["eac"]))) < Decimal("0.01"), (
            f"{method}: the comparison verb says {row['eac']} and the calculation verb says "
            f"{direct[0]['eac']} — two implementations of one formula have drifted"
        )


@pytest.mark.parametrize("method,cpi,spi,expected", [
    ("REMAINING_AT_BUDGET", None, None, None),   # projects no index, so it always answers
    ("REMAINING_AT_BUDGET", 0.8, 0.9, None),
    ("CPI", None, 0.9, "CPI"),
    ("CPI", 0, 0.9, "CPI"),
    ("CPI", 0.8, None, None),                    # SPI is not its business
    ("CPI_SPI", None, 0.9, "CPI"),
    ("CPI_SPI", 0.8, None, "SPI"),
    ("CPI_SPI", None, None, "CPI"),              # both absent: the COST index is reported
    ("CPI_SPI", 0.8, 0.9, None),
])
def test_missing_index_names_WHICH_index_a_method_needed_and_did_not_get(
        method, cpi, spi, expected):
    """A FACT ABOUT THE COMPUTATION, NOT A SENTENCE — the caller phrases the refusal.

    `CPI` IS NAMED FIRST WHEN BOTH ARE ABSENT, matching the behaviour this replaced: a program
    with no cost performance has a larger problem than a missing schedule index, and that is
    the one to report.

    **None of this was reachable in the reference seed**, where all three methods answer. It
    became one parametrize once the decision moved into a module that takes the indices as
    arguments — seventh instance of a rule becoming checkable by being lifted.
    """
    assert M.missing_index(method, cpi=cpi, spi=spi) == expected


def test_missing_index_is_NONE_exactly_when_the_method_ANSWERS():
    """THE JOIN between the explanation and the outcome. A method that answers must not also
    report a missing index, and one that refuses must name one — otherwise a row could carry a
    forecast AND a reason it could not be computed, which is two answers to one question."""
    for method in M.FORMULA:
        for cpi in (None, 0, 0.8):
            for spi in (None, 0, 0.9):
                answered = M.estimate_at_completion(
                    method, cpi=cpi, spi=spi, **QUANTITIES) is not None
                named = M.missing_index(method, cpi=cpi, spi=spi) is not None
                assert answered != named, (
                    f"{method} cpi={cpi} spi={spi}: answered={answered} but "
                    f"missing_index reported {named}"
                )


def test_the_COMPARISON_verb_keeps_an_undefined_methods_ROW_with_its_reason():
    """The deliberate difference between the two verbs, sealed now that one module serves both.

    `fin_eac_comparison` KEEPS the row and explains; `fin_eac_calculation` RAISES. **A
    comparison that dropped a method would show two forecasts where three were asked for.**

    REACHED VIA A WINDOW WITH NO REPORTED FACTS — the seed's own periods, six of which carry
    nothing. Without that window every method answers and this entire path is unexercised,
    which is how it stood until this commit.
    """
    from agent_fleet.finance_agent import measures as engine
    from agent_fleet.finance_agent.entities import periods_in
    from agent_fleet.finance_agent.seed import build_seed

    state = build_seed()
    wps = {w.wp_id for w in state.work_packages
           if w.ca_id in {c.ca_id for c in state.accounts_of("NP-MERIDIAN")}}
    empty = [p for p in periods_in(None) if engine._totals(state, wps, [p]) == (0, 0, 0)]
    assert len(empty) >= 2, "the seed no longer has unreported periods; this path is unreachable"

    rows = engine.fin_eac_comparison(state, program_id="NP-MERIDIAN", window=empty[:2])
    assert len(rows) == len(M.FORMULA), "a method was DROPPED rather than explained"

    by_method = {r["method"]: r for r in rows}
    assert by_method["CPI"]["eac"] is None
    assert "CPI" in by_method["CPI"]["unavailable_reason"]
    assert by_method["CPI_SPI"]["eac"] is None
    assert by_method["CPI_SPI"]["unavailable_reason"]

    # REMAINING_AT_BUDGET PROJECTS NO INDEX, so it answers where the other two cannot — the
    # property that made the "every method undefined" refusal unreachable.
    assert by_method["REMAINING_AT_BUDGET"]["eac"] is not None
    assert by_method["REMAINING_AT_BUDGET"].get("unavailable_reason") is None, (
        "a method that answered also carried a reason it could not be computed"
    )
