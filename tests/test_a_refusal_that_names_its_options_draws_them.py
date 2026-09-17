"""A refusal carrying a slot and a menu renders as an ask — and an ABSENT menu never renders empty.

THE DEFECT, and it is not the one anybody expected. `cost_agent` has emitted

    {"refused": true, "outcome": "not_in_model", "reason": "...", "available": [...]}

since the vintage refusal was written, with its own comment saying *"same key as VintageRequired
above, so a consumer reads one field for what may I say instead."*

**Measured 2026-09-17 by `cortex-ui-60`, who traced it rather than building on a claim that it was
renderable:**

    src/iagent            grep '"available"'  ->  ZERO hits
    presentation_agent    grep '"available"'  ->  no match
    cortex-ui             nothing to read, because nothing sends it

> **It was never flattened into prose downstream. THE CONSUMER WAS NEVER WRITTEN.** A producer did
> the right thing, documented who would read it, and no one ever did — both ends correct and the
> wire between them empty, with nothing failing for as long as it lasted.

That is R-075's corollary rather than R-075 itself. The rule catches a producer that writes a list
into a sentence; **this is a producer that got it right and a reader that does not exist.**

── THE ARM THAT MATTERS IS ABSENT-VERSUS-EMPTY ──────────────────────────────────────────────────

`not_in_model` arrives BOTH WITH and WITHOUT `available` — the `NotInModel` branch could not
always compute one, the `CompositionError` branch recomputes it. `cortex-ui-60` caught that by
reading BOTH branches rather than the one the dispatch named, and was right that **absent must not
render as an empty menu**: `[]` means *this lot accepts nothing*, omitted means *not computable
from what you supplied*, and rendering the second as the first is a different and false answer.

`options_for` already keeps them apart — it returns `None` for "not computable" and `[]` for
"genuinely none" — and its docstring says so. Both branches now honour that.

Run: uv run --frozen pytest tests/test_a_refusal_that_names_its_options_draws_them.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_PRES = _REPO / "agent_fleet" / "presentation_agent" / "main.py"
_COST = _REPO / "agent_fleet" / "cost_agent" / "main.py"


def _pres() -> str:
    return _PRES.read_text(encoding="utf-8")


def _cost() -> str:
    return _COST.read_text(encoding="utf-8")


def _helper() -> str:
    """`_render_refusal_menu`, which builds the component.

    THE SHAPE AND THE GUARD LIVE IN DIFFERENT PLACES, and the arms follow them rather than the
    other way round. The call site decides WHETHER to project (absent-versus-empty); the helper
    decides WHAT the component is. A single slice over both would pass an assertion about the
    shape by finding it in the guard, or vice versa.
    """
    s = _pres()
    i = s.index("def _render_refusal_menu(")
    return s[i:s.index("def _render_abstain_menu(", i)]


def _block() -> str:
    """The refusal projection alone, bounded by the branch that follows it."""
    s = _pres()
    i = s.index("# ── A REFUSAL THAT NAMES WHAT YOU MAY SAY INSTEAD IS AN ASK")
    j = s.index("_declared = _extract_agent_response(request.raw_data)", i)
    return s[i:j]


def test_THE_CONSUMER_EXISTS_AT_ALL():
    """THE WHOLE POINT. `available` was a correct field with no reader for weeks; the property
    this file protects is that a reader exists, not that it is clever."""
    assert '_ref.get("available")' in _block(), (
        "nothing reads `available`, so a refusal that names what you may say instead still "
        "arrives as prose — the producer emits a field into a wire with no consumer"
    )


def test_IT_PROJECTS_AS_AN_ELICITATION_WITH_OPTIONS():
    """Ruled: an ask whose options are values. cortex's AskCard renders `options` when the list
    is non-empty and falls back to free text when it is not, so `options` is the whole contract."""
    b = _helper()
    assert '"archetype": "ELICITATION"' in b
    assert '"options": _as_options(opts)' in b
    assert '"slot": slot' in b, (
        "the ask does not carry which slot it is asking about; ELICITATION requires it and a "
        "card that cannot say what it is asking for is not an ask"
    )


def test_AN_ABSENT_MENU_DOES_NOT_RENDER_AS_AN_EMPTY_ONE():
    """THE ARM WITH TEETH, and the one a 'does it draw a menu' check cannot make.

    `[]` means the lot accepts nothing; omitted means not computable. Rendering the second as
    the first asserts something false with a card's confidence.
    """
    b = _block()
    assert re.search(r"isinstance\(_opts,\s*list\)\s*and\s*_opts", b), (
        "the projection does not require a NON-EMPTY list, so an absent or empty `available` "
        "renders as a menu of nothing — which says this lot accepts nothing"
    )
    assert "_opts == []" in b, (
        "the genuinely-empty case is not distinguished from the absent one; both are silent "
        "and a reader cannot tell which happened"
    )


def test_THE_ENGINE_KEEPS_ABSENT_AND_EMPTY_APART():
    """The producer half of the same rule. `options_for` returns None for 'not computable' and
    [] for 'genuinely none', and the refusal must not collapse them by defaulting."""
    c = _cost()
    assert re.search(r'\{"available": _avail\} if _avail is not None else \{\}', c), (
        "the NotInModel branch defaults the option list instead of omitting it, so "
        "'not computable from what you supplied' is reported as 'this lot accepts nothing'"
    )


def test_ONE_REFUSAL_KIND_DOES_NOT_ARRIVE_TWO_SHAPES():
    """`not_in_model` reached consumers both with and without `available`. A consumer written
    against either was wrong about the other, which is why cortex-60 could not have built this
    from the dispatch alone — it named only the carrying branch."""
    c = _cost()
    # A WINDOW, NOT A BALANCED-PAREN MATCH. The first draft stopped at the close paren inside
    # `options_for(...)`, read a TRUNCATED branch, and reported correct code as broken. A regex
    # that cannot see the whole construct answers about the part it saw.
    branches = [c[m.start():m.start() + 240]
                for m in re.finditer(r'"not_in_model"', c)]
    assert len(branches) >= 2, f"expected both not_in_model branches, found {len(branches)}"
    assert all("available" in b for b in branches), (
        "a not_in_model branch still refuses without ever offering the field, so the shape a "
        "consumer sees depends on which exception fired"
    )


def test_THE_SLOT_TRAVELS_WITH_THE_MENU():
    """A list of values for SOMETHING. A consumer inferring the slot from the verb name is
    re-deriving a fact the producer holds."""
    c = _cost()
    assert c.count('slot="rate_vintage"') >= 3, (
        "not every refusal that can carry a menu names the slot it is a menu for"
    )


def test_THE_OPTION_SOURCE_NAMES_THE_MECHANISM_not_a_borrowed_one():
    """`enumeration` would claim an enumerate provider was asked. None was — the engine
    recomputed the legal values while refusing, which is a different provenance and a consumer
    may care which."""
    b = _helper()
    assert '"option_source": "refusal"' in b
    assert '"option_source": "enumeration"' not in b


@pytest.mark.parametrize("marker", ["THE CONSUMER WAS NEVER WRITTEN", "ABSENT IS NOT EMPTY"])
def test_THE_REASONING_TRAVELS(marker: str):
    """A later reader seeing a branch that looks like defensive plumbing needs the measurement:
    a correct field can sit unread indefinitely with nothing failing."""
    assert marker in _pres()
