"""ADR-0053 §2 registry rows, and §2a's ABSOLUTE TRANSCRIPTION SEAL on each.

── WHY THIS SEAL PARSES A STRING INSTEAD OF COMPARING TWO ───────────────────────────────────
The obvious seal is `row.transcription == eac_formulas.FORMULA[method_id]`. It would pass on
the day the whole engine was wrong, because **two copies of one wrong formula agree perfectly**
— and that is not a hypothesis here. Five of six mutations against these three methods survived
a 151-test green suite, and the worst of them, `EAC = BAC * CPI` in place of `BAC / CPI`,
**reverses the sign of the forecast**: *"we will overrun by 2.15M"* becomes *"we will land 1.8M
under"*.

So the row's `derived_from.transcription` is **PARSED AND EVALUATED** and its result compared
against what the module computes. The transcription is written the way the standard states the
formula; the module is written the way Python spells it; and the seal is the only place the two
meet. That is what makes it absolute rather than relative.

**AND THE COMPARISON SEAL DOES NOT SUBSTITUTE.** `fin_eac_comparison` checks the spread between
the three methods and did NOT catch the inversion — `BAC * CPI` keeps CPI below CPI_SPI, so the
ordering held. *A relative check is blind to what its subjects share.*

── THE CHECKER IS ITSELF CHECKED ────────────────────────────────────────────────────────────
`test_the_transcription_seal_CATCHES_the_inversion_it_was_written_for` feeds the seal the exact
mutation and asserts it FAILS. A transcription check that cannot be made to fail is a green
light wired to nothing, and this file's whole claim rests on that one test.

── WHERE THE VALUE SET COMES FROM ───────────────────────────────────────────────────────────
**From OUTSIDE the rows.** `EACMethod` in `entities.py` is a `Literal` this directory does not
write, and the seal asserts the two agree. A vocabulary enumerated FROM the rows it checks is
complete by construction: a row added with no type value, and a type value with no row, would
both pass. Two independent declarations that must match is the only arrangement in which either
one can be wrong.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Any, get_args

import pytest

from agent_fleet.finance_agent import measures
from agent_fleet.finance_agent.entities import EACMethod
from agent_fleet.finance_agent.measure_modules import eac_formulas
from agent_fleet.finance_agent.method_registry import (
    MethodRowError,
    load_method_rows,
)

ROWS = load_method_rows()
BY_ID = {r.method_id: r for r in ROWS}

#: THE VALUE SET, DECLARED OUTSIDE `policy/measures/`. Read from the type, never from the rows.
DECLARED_METHODS = frozenset(get_args(EACMethod))

#: A program over cost and behind schedule — **CPI BELOW ONE**, which is the only region where
#: dividing and multiplying by it point in opposite directions. Round figures, notional.
_EVM: dict[str, float] = {
    "BAC": 10_000_000.0,
    "BCWP": 4_000_000.0,
    "ACWP": 5_000_000.0,
    "BCWS": 4_500_000.0,
}
_EVM["CPI"] = _EVM["BCWP"] / _EVM["ACWP"]          # 0.80
_EVM["SPI"] = _EVM["BCWP"] / _EVM["BCWS"]          # 0.888...

_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


def _evaluate(transcription: str, quantities: dict[str, float]) -> float:
    """Run a transcribed formula. `EAC = <expr>` over the named EVM quantities.

    A WHITELISTED AST WALK, not `eval`. Not for safety theatre — these strings are ratified
    rows, not input — but because a walk that meets an unexpected node RAISES, while `eval`
    would quietly evaluate whatever else a row happened to contain and call it a formula.
    """
    lhs, _, rhs = transcription.partition("=")
    assert lhs.strip() == "EAC", f"a transcription states EAC; this one states {lhs.strip()!r}"
    assert rhs.strip(), "a transcription with no right-hand side is not a formula"

    def walk(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in quantities:
                raise AssertionError(
                    f"transcription names {node.id!r}, which is not an EVM quantity this seal "
                    f"supplies ({sorted(quantities)}). A formula over a quantity nobody defined "
                    f"cannot be checked, and silently treating it as zero would pass."
                )
            return quantities[node.id]
        raise AssertionError(f"transcription contains an unsupported construct: {ast.dump(node)}")

    return walk(ast.parse(rhs.strip(), mode="eval"))


# ── §2a: THE TRANSCRIPTION, RUN ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("row", ROWS, ids=lambda r: r.method_id)
def test_the_module_COMPUTES_what_its_row_TRANSCRIBES(row):
    """EVERY ROW CARRIES AN ABSOLUTE TRANSCRIPTION SEAL (§2a), and this is it.

    Not a string against another string. The row's formula is evaluated as arithmetic and the
    module is called, and the two numbers are compared.
    """
    expected = _evaluate(row.transcription, _EVM)
    actual = eac_formulas.estimate_at_completion(
        row.method_id,
        bac=_EVM["BAC"], bcwp=_EVM["BCWP"], acwp=_EVM["ACWP"],
        cpi=_EVM["CPI"], spi=_EVM["SPI"],
    )
    assert actual == pytest.approx(expected), (
        f"{row.method_id}: the row transcribes {row.transcription!r} from "
        f"{row.clause!r}, which evaluates to {expected:,.2f}, and the module computes "
        f"{actual:,.2f}. The row's citation is what travels on the artifact under §5."
    )


def test_the_transcription_seal_CATCHES_the_inversion_it_was_written_for():
    """THE CHECKER, CHECKED. Everything above rests on this seal being able to fail.

    The mutation is the real one: `BAC * CPI` for `BAC / CPI`. It survived a 151-test green
    suite, it preserves the ordering that `fin_eac_comparison` checks, and with CPI at 0.8 it
    turns a 12.5M forecast into an 8M one — **an overrun reading as an underrun**.
    """
    honest = _evaluate("EAC = BAC / CPI", _EVM)
    inverted = _evaluate("EAC = BAC * CPI", _EVM)

    assert honest == pytest.approx(12_500_000.0)
    assert inverted == pytest.approx(8_000_000.0)
    assert honest != pytest.approx(inverted), (
        "the two point in opposite directions; a seal that cannot tell them apart is a green "
        "light wired to nothing"
    )
    # And the module sits on the honest side of that difference.
    assert eac_formulas.estimate_at_completion(
        "CPI", bac=_EVM["BAC"], bcwp=_EVM["BCWP"], acwp=_EVM["ACWP"],
        cpi=_EVM["CPI"], spi=_EVM["SPI"],
    ) == pytest.approx(honest)


def test_the_evaluator_REFUSES_a_quantity_nobody_declared():
    """A formula over an undefined symbol must raise rather than read as zero — otherwise a row
    citing `EAC = BAC / CPI_ADJUSTED` would seal green against a module ignoring it."""
    with pytest.raises(AssertionError, match="not an EVM quantity"):
        _evaluate("EAC = BAC / MADE_UP_INDEX", _EVM)


def test_the_evaluator_REFUSES_anything_that_is_not_arithmetic():
    with pytest.raises(AssertionError, match="unsupported construct"):
        _evaluate("EAC = max(BAC, ACWP)", _EVM)


# ── THE VALUE SET, DECLARED FROM OUTSIDE THE ROWS ────────────────────────────────────────────

def test_the_ROWS_and_the_TYPE_declare_the_same_methods():
    """⚠ THE ONE ASSERTION THAT MUST NOT BE DERIVED FROM THE ROWS.

    `EACMethod` is a `Literal` in `entities.py`. Enumerating the vocabulary from
    `policy/measures/` and then checking `policy/measures/` against it would be complete by
    construction, and BOTH halves of the real failure — a row with no type value, a type value
    with no row — would pass.
    """
    assert {r.method_id for r in ROWS} == set(DECLARED_METHODS), (
        "a method row with no `EACMethod` value is unreachable through the slot, and an "
        "`EACMethod` value with no row is a method the registry does not govern"
    )


def test_the_three_TABLES_the_engine_already_carried_agree_with_the_rows():
    """`measures.EAC_METHODS`, `measures.EAC_FORMULA` and `eac_formulas.FORMULA` were three
    copies of one fact before these rows existed. Each is checked against the registry."""
    assert set(measures.EAC_METHODS) == {r.method_id for r in ROWS}
    assert set(measures.EAC_FORMULA) == {r.method_id for r in ROWS}
    assert set(eac_formulas.FORMULA) == {r.method_id for r in ROWS}
    assert set(eac_formulas.REQUIRES_INDEX) == {r.method_id for r in ROWS}


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r.method_id)
def test_the_wire_spelling_is_the_TRANSCRIPTION_with_one_declared_rendering(row):
    """`measures.EAC_FORMULA` is what the response carries, and it spells multiplication `x`
    where the transcription spells it `*`.

    ⚠ THE WIRE IS NOT CHANGED TO MATCH. A consumer has already seen the `x` spelling —
    `CompetingMeasures.test.tsx` carries it in a fixture — so the rendering is declared here and
    pinned, rather than the string being quietly converted and a card's expectation broken. One
    transcription, one stated rendering, and no third spelling.
    """
    assert measures.EAC_FORMULA[row.method_id] == row.transcription.replace("*", "x")


# ── `requires_index` IS DATA, AND IT IS TRUE OF THE CODE ─────────────────────────────────────

@pytest.mark.parametrize("row", ROWS, ids=lambda r: r.method_id)
def test_requires_index_on_the_row_is_TRUE_OF_THE_MODULE_and_not_merely_beside_it(row):
    """The row says whether a method needs an index; the module is asked with none.

    A field that only has to match another field can drift with it. This one is checked against
    BEHAVIOUR — which is also the check that would have caught the unreachable "every method
    undefined" refusal, because `REMAINING_AT_BUDGET` answering here is the fact that made it
    unreachable.
    """
    assert row.requires_index == eac_formulas.REQUIRES_INDEX[row.method_id]

    answered = eac_formulas.estimate_at_completion(
        row.method_id, bac=_EVM["BAC"], bcwp=_EVM["BCWP"], acwp=_EVM["ACWP"], cpi=None, spi=None,
    )
    if row.requires_index:
        assert answered is None, (
            f"{row.method_id} declares requires_index but produced {answered} with no index; "
            f"None is not zero, and every substitute figure is an invention"
        )
    else:
        assert answered is not None, (
            f"{row.method_id} declares it needs no index and then refused without one — the "
            f"property that makes an 'every method undefined' refusal unreachable"
        )


# ── §3's REFUSALS, EACH WITH A POSITIVE CONTROL ──────────────────────────────────────────────

def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


_GOOD = """
method_id: GOOD
name: A row that loads
module: agent_fleet.finance_agent.measure_modules.eac_formulas
function: estimate_at_completion
version: "1.0.0"
requires_index: false
derived_from:
  authority: test
  clause: test
  transcription: EAC = BAC
"""


def test_a_VALID_row_loads_which_is_the_control_for_every_refusal_below(tmp_path):
    """Without this, a refusal test passes because the loader refuses EVERYTHING."""
    rows = load_method_rows(_write(tmp_path, "good.yaml", _GOOD), overlay_dirs=[])
    assert [r.method_id for r in rows] == ["GOOD"]


def test_a_row_with_NO_TRANSCRIPTION_is_refused(tmp_path):
    """§2a is structural. A row whose formula cannot be checked against a stated standard is a
    row that ships a sign flip with a name on it."""
    text = _GOOD.replace("  transcription: EAC = BAC\n", "")
    with pytest.raises(MethodRowError, match="transcription is required"):
        load_method_rows(_write(tmp_path, "no_clause.yaml", text), overlay_dirs=[])


def test_a_row_pointing_at_an_UNMANIFESTED_module_is_refused(tmp_path):
    """§3 by name: *a row that resolves to an unmanifested target is worse than an absent row,
    because it reads as governed.*"""
    text = _GOOD.replace(
        "module: agent_fleet.finance_agent.measure_modules.eac_formulas",
        "module: agent_fleet.finance_agent.entities",     # real module, no VERSION
    )
    rows = load_method_rows(_write(tmp_path, "unmanifested.yaml", text), overlay_dirs=[])
    with pytest.raises(MethodRowError, match="declares no VERSION"):
        rows[0].resolve()


def test_a_row_whose_VERSION_disagrees_with_its_module_is_refused(tmp_path):
    """§5 puts this string on every artifact beside the figure. A row and a module disagreeing
    means a recipient cannot reproduce the number from what the artifact says."""
    text = _GOOD.replace('version: "1.0.0"', 'version: "9.9.9"')
    rows = load_method_rows(_write(tmp_path, "badver.yaml", text), overlay_dirs=[])
    with pytest.raises(MethodRowError, match="module declares"):
        rows[0].resolve()


def test_an_EMPTY_policy_directory_is_a_missing_COPY_and_not_an_empty_registry(tmp_path):
    """FAIL LOUD ON NONE, for the reason `load_graphs` states: zero rows and a green light is
    the failure mode with no symptom."""
    with pytest.raises(MethodRowError, match="no ratified method rows"):
        load_method_rows(tmp_path, overlay_dirs=[])


# ── THE DIRECTORY SHIPS ──────────────────────────────────────────────────────────────────────

def test_the_policy_directory_is_COPIED_into_the_agent_image():
    """⚠ THE DEPLOYMENT-ONLY FAILURE, sealed at CI time.

    `policy/measures/` reaches a container through a per-file COPY in `.github/docker/Dockerfile.agent`
    heredoc inside `.github/workflows/build-containers.yml`. That file's own comment says the
    per-file COPY *"is itself the fragile part: the next shared-policy file will need"* it —
    written when `policy/graphs/` was that next file. This directory is the one after.

    Nothing imports the registry at runtime YET, so today this seal is early rather than
    load-bearing. It is written now because the edit that makes it load-bearing is one line in
    `measures.py`, and by then the missing COPY is an unstartable pod rather than a red test.
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    wf = (root / ".github/docker/Dockerfile.agent").read_text(encoding="utf-8")
    assert "COPY policy/measures/ /app/policy/measures/" in wf, (
        "policy/measures/ is not COPYed into the agent image. A finance engine that imports "
        "the method registry would pass every test here and fail only in the deployment."
    )
