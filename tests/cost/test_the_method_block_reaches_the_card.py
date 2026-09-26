"""A FIGURE WITHOUT ITS METHOD IS UNACTIONABLE, AND THE METHOD HAS TWO HOPS TO SURVIVE.

The four cost CONTRIBUTION_RANKING producers now emit a `method` block — formula as text, inputs
by name with values, the bound and whether it was defaulted, and the producer sha. This file seals
BOTH HOPS, because each half is green on its own while the pair is broken:

  * the PRODUCER emits it, which the engine's own tests can see; and
  * the PROJECTOR carries it, which they cannot — `_PROJECTED_ARCHETYPES` is an explicit
    allowlist, so a new envelope-level field is dropped silently by a function that is working
    exactly as written. That has now happened four times to this one tuple (`reference`,
    `verdict`, `threshold`/`threshold_defaulted`, and this), each time found in a browser.

── THE SHAPE IS DECLARED OUTSIDE THIS FILE, AND OUTSIDE THIS ENGINE ──────────────────────────
`tests/_method_block_contract.py` holds it once, for every engine that emits a block, with each
decision's author recorded: inputs as an ordered list of `{name, value, unit?}`, `bound` as
float|None, values stringified, the unit key OMITTED rather than null where the quantity is
dimensionless. This file IMPORTS that rather than restating it — a mirror nobody checks is the
second-source-of-truth defect this repo keeps paying for, and the mirror this file used to hold
is what the reconciliation had to go and edit in two places.

The consumer's half of the contract is PARSED from `cortex-ui/src/lib/cardExport.ts` when the
sibling repo is checked out, never mirrored. `readMethod` drops a block WHOLE when `formula`
trims empty, `formatLeaf` JSON-stringifies an object, and `MethodInput` has NO unit field — so
`unit` is on the wire ahead of the card, which the parity seal records as a partition rather than
letting an equality check hide it.

── THE POPULATION IS DERIVED, NOT LISTED ─────────────────────────────────────────────────────
"The four cost producers" is a sentence I could have typed and been wrong about. The basis is
computed from `PRESENTATION_CAPABILITIES` (which subjects render as CONTRIBUTION_RANKING) joined
to `measures.OUTPUT_URI` (which verb produces each subject), and every member of that population
must be in the basis or in `_NOT_IN_SCOPE` with a reason. A fifth cost ranking added tomorrow
fails here rather than shipping a card with no method.

Run: uv run --frozen pytest tests/cost/test_the_method_block_reaches_the_card.py -v
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from agent_fleet.cost_agent import measures
from agent_fleet.cost_agent.seed import build_state
from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
from tests import _method_block_contract as contract

_CARD_EXPORT = (
    Path(__file__).resolve().parents[2].parent
    / "cortex-ui" / "src" / "lib" / "cardExport.ts"
)

#: IMPORTED, NOT MIRRORED. Two engines emit this block and the shape is one decision, so the
#: field sets live in `tests/_method_block_contract.py` with the reason each field exists.
_UI_METHOD_FIELDS = set(contract.BLOCK_FIELDS_IN_THE_UI)
_OURS_BEYOND_THE_UI = set(contract.BLOCK_FIELDS_BEYOND_THE_UI)

#: CONTRIBUTION_RANKING producers that are not cost measures. AN EXCLUSION IS A CLAIM, so each
#: carries its reason and the partition arm fails on any member that is in neither set.
_NOT_IN_SCOPE = {
    "fin:VarianceDriverRanking": (
        "engine-finance's producer. The order that asked for this block scoped it to the COST "
        "engine; finance's ranking needs the same treatment and it is a separate change in a "
        "separate file, not a silent omission here"
    ),
    "safety:OrphanedHazardSet": (
        "engine-safety's producer, same scope reason as the finance one. It also has no formula "
        "in the arithmetic sense — a count of orphans is not a computed contribution — so its "
        "method block is a design question rather than a transcription"
    ),
}

#: One representative call per verb in the basis. Arguments only; the payload is the engine's.
_CALLS = {
    "cost_lot_breakdown": dict(lot=3, rate_vintage="2021-02-01"),
    "cost_labor_composition": dict(lot=3),
    "cost_category_breakdown": dict(lot=3),
    "cost_supplier_concentration": dict(lot=3),
}

#: output class -> verb, derived from the engine's own table rather than restated.
_VERB_FOR = {uri.rsplit("#", 1)[-1]: fn for fn, uri in measures.OUTPUT_URI.items()}

_RANKING_SUBJECTS = [b["subject_uri"] for b in PRESENTATION_CAPABILITIES
                     if b["archetype"] == "CONTRIBUTION_RANKING"]

#: The basis: cost subjects rendered as a contribution ranking, as verbs.
BASIS = sorted(
    _VERB_FOR[s.split(":", 1)[1]]
    for s in _RANKING_SUBJECTS
    if s.startswith("cost:") and s.split(":", 1)[1] in _VERB_FOR
)


@pytest.fixture(scope="module")
def state():
    return build_state()


def _payload(state, verb: str) -> dict:
    return getattr(measures, verb)(state, **_CALLS[verb])


# ── the population ───────────────────────────────────────────────────────────────────────────


def test_the_population_is_DERIVED_and_every_member_is_decided():
    """Every CONTRIBUTION_RANKING producer is in the basis or excluded WITH A REASON.

    A member that is silently absent from a population is indistinguishable from one that was
    checked and passed. This arm is what makes the four parametrised arms below a census rather
    than a sample of whatever I happened to remember.
    """
    undecided = [s for s in _RANKING_SUBJECTS
                 if s not in _NOT_IN_SCOPE
                 and not (s.startswith("cost:") and s.split(":", 1)[1] in _VERB_FOR)]
    assert not undecided, (
        f"these CONTRIBUTION_RANKING producers are neither cost measures nor excluded with a "
        f"reason: {undecided}. Give the verb a method block, or add an entry to _NOT_IN_SCOPE "
        f"saying why it has none."
    )
    assert all(_NOT_IN_SCOPE.values()), "an exclusion with an empty reason is not a claim"
    # NON-VACUITY, both halves: an empty basis passes every arm below, and a _CALLS map that has
    # drifted from the basis silently shrinks it.
    assert len(BASIS) >= 4, f"the basis collapsed to {BASIS}"
    assert set(BASIS) == set(_CALLS), (
        f"the basis and the call map disagree: {sorted(set(BASIS) ^ set(_CALLS))}"
    )


def test_the_UIs_declared_METHOD_FIELDS_are_PARSED_not_remembered():
    """The declaration, checked against the consumer that gave it its field names.

    Skipped only when cortex-ui is not checked out beside this repo — and the arms that use the
    declared field sets still run in that case, so the declaration is exercised either way.
    """
    if not _CARD_EXPORT.is_file():
        pytest.skip(f"cortex-ui not checked out at {_CARD_EXPORT}; the declaration runs unchecked")
    src = _CARD_EXPORT.read_text(encoding="utf-8")
    parsed = set(contract.ui_block_fields(src))
    assert parsed == _UI_METHOD_FIELDS, (
        f"cortex declares {sorted(parsed)}; the contract declares {sorted(_UI_METHOD_FIELDS)}"
    )


# ── the producer half ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("verb", BASIS)
def test_every_cost_ranking_emits_a_method_block_the_UI_can_READ(verb, state):
    """The producer's side of the join, against the CONSUMER's gates rather than my own.

    `readMethod` returns null — and the card then says "method not supplied" — for a block that
    is not an object, or whose formula trims to empty. Those are the two ways to ship a block
    that exists and renders as nothing, so they are the two asserted here.
    """
    method = _payload(state, verb).get("method")
    assert isinstance(method, dict), f"{verb} emitted no method block"
    assert set(method) == _UI_METHOD_FIELDS | _OURS_BEYOND_THE_UI, sorted(method)

    # THE SHARED CHECKER, run against this engine's real payload. It reports every departure at
    # once rather than the first, and it is the same function engine-finance's seal will call —
    # which is the only reason "one shape" is a checkable claim rather than an agreement.
    assert contract.check_block(method) == [], contract.check_block(method)

    # And the two gates the CONSUMER applies, asserted here too rather than trusted to the
    # checker: a checker and the thing it checks sharing one author is one witness, not two.
    assert isinstance(method["formula"], str) and method["formula"].strip(), (
        "an empty formula is dropped WHOLE by readMethod — the card would say 'method not "
        "supplied' about a producer that supplied one"
    )
    assert isinstance(method["inputs"], list) and method["inputs"], f"{verb} stated no inputs"
    for entry in method["inputs"]:
        assert set(entry) <= set(contract.INPUT_FIELDS), entry
        assert set(contract.INPUT_REQUIRED) <= set(entry), entry
        # ONLY THE NAME GATES A ROW in readMethod, so a nameless input is dropped silently.
        assert isinstance(entry["name"], str) and entry["name"].strip(), entry
        assert entry["value"] is None or isinstance(entry["value"], str), entry
        # ABSENT, NEVER NULL. lane/ca's convention: absent means dimensionless by the contract,
        # so `"unit": None` would read as an unknown currency on a figure that is a count.
        assert "unit" not in entry or (entry["unit"] and isinstance(entry["unit"], str)), entry
    assert "producer_sha" in method, "the attestation must be present even when it is None"


@pytest.mark.parametrize("verb", BASIS)
def test_the_method_block_is_JSON_SAFE(verb, state):
    """A Decimal in the block is a 500 at the route, not a rendering problem. The whole payload is
    checked, not just the block, because the block is where Decimals were most likely to leak."""
    import json

    json.dumps(_payload(state, verb))


@pytest.mark.parametrize("verb", BASIS)
def test_the_bound_is_a_FLOAT_or_NULL_and_never_a_string_or_an_object(verb, state):
    """float|None, which is the RECONCILED shape and not the one this engine shipped first.

    Two other forms are wrong here and each was reasonable once. A nested
    `{name, value, defaulted}` is better JSON and appears in the card's bound cell as raw
    machine text, because `formatLeaf` JSON-stringifies an object. A SENTENCE is what 546e6be
    shipped and it renders best of the three — and it is one engine's private shape under a field
    name another engine also fills, which is the drift this reconciliation exists to end. So the
    string is asserted absent too, explicitly, rather than merely not-a-dict.

    A Decimal is the third: it is not JSON and would 500 the route, which the JSON arm catches
    from the other side.
    """
    bound = _payload(state, verb)["method"]["bound"]
    assert bound is None or isinstance(bound, float), bound
    assert not isinstance(bound, str), (
        f"bound={bound!r} is a string; that is the form this engine narrowed AWAY from"
    )


@pytest.mark.parametrize("verb", BASIS)
def test_bound_and_its_FLAG_agree_and_an_UNBOUNDED_measure_says_NOTHING(verb, state):
    """`bound_defaulted` is None, never False, when there is no bound.

    False means "there IS a bound and the caller chose it" — a claim about a caller who was never
    asked. Three of these four have no bound at all, and a plausible-looking `false` on those
    reads as considered rather than as absent, which is the failure mode this repo has a name for.
    """
    method = _payload(state, verb)["method"]
    if method["bound"] is None:
        assert method["bound_defaulted"] is None, (
            f"{verb} has no bound but reports bound_defaulted="
            f"{method['bound_defaulted']!r}"
        )
    else:
        assert isinstance(method["bound_defaulted"], bool)


def test_the_BOUNDED_measure_states_the_value_AND_WHO_CHOSE_IT(state):
    """Both directions, because the defaulted flag is only meaningful if it can read False.

    A block that always reported "defaulted" would satisfy the first half and be wrong about every
    caller-supplied threshold — and the supplied one is the case where the reader most needs to
    know the number was not ours.

    WHERE THE ATTRIBUTION LIVES CHANGED WITH THE SHAPE, and this arm changed with it rather than
    being deleted. Under the sentence form the origin was a phrase inside `bound`; under float|None
    the only carrier is `bound_defaulted`, so that flag now bears the whole claim — which is
    precisely why both of its values are driven here, and why the packet says plainly that nothing
    in the CARD shows it (`readMethod` drops the flag).
    """
    defaulted = measures.cost_supplier_concentration(state, lot=3)["method"]
    chosen_payload = measures.cost_supplier_concentration(state, lot=3, threshold=0.30)
    chosen = chosen_payload["method"]

    assert defaulted["bound_defaulted"] is True
    assert defaulted["bound"] == float(measures.DEFAULT_CONCENTRATION_THRESHOLD)

    assert chosen["bound_defaulted"] is False, "a chosen bound must not read as a defaulted one"
    # DERIVED FROM THE CALLER'S ARGUMENT, not typed. The claim is that the bound carries the
    # CALLER's number and NOT the engine's, so both halves are asserted — a value arm that only
    # said "equals 0.3" would pass against an engine that ignored the argument and happened to
    # default to it.
    assert chosen["bound"] == 0.30, chosen["bound"]
    assert chosen["bound"] != float(measures.DEFAULT_CONCENTRATION_THRESHOLD), chosen["bound"]
    assert defaulted["bound"] != chosen["bound"]

    # AND THE BOUND'S NAME SURVIVES, which is the half the narrowing could have lost silently.
    # A bare 0.3 in a cell is the EAC-without-method ambiguity again; the shared checker asserts
    # the three declarations of this one local — block bound, the input that names it, and the
    # envelope's labelled threshold — cannot disagree.
    assert contract.check_bound_agrees(
        chosen, envelope_threshold=chosen_payload["threshold"], bound_input_name="threshold"
    ) == [], contract.check_bound_agrees(
        chosen, envelope_threshold=chosen_payload["threshold"], bound_input_name="threshold"
    )


def test_the_TOP_LEVEL_threshold_pair_SURVIVES_the_addition(state):
    """The existing wire contract is not replaced by the block.

    `threshold` and `threshold_defaulted` are what the projector's allowlist names and what cortex
    reads today. A change that moved them inside `method` would be green in this file and blank on
    every card, so the old pair is sealed HERE, beside the new one, and both are asserted to agree
    — two statements of one fact are only safe while something checks they match.
    """
    payload = measures.cost_supplier_concentration(state, lot=3, threshold=0.30)
    # A string on the wire, and the caller's VALUE rather than the caller's spelling: the field
    # has always rendered 0.30 as "0.3", which is the producer's business and not this seal's.
    assert isinstance(payload["threshold"], str)
    assert Decimal(payload["threshold"]) == Decimal("0.30")
    assert payload["threshold_defaulted"] is False
    # THE SAME NUMBER IN TWO REPRESENTATIONS, compared as numbers. The envelope carries the string
    # (its existing contract) and the block carries the float (the reconciled one), so a textual
    # comparison would red on the representation instead of on the agreement — which is the arm
    # this line replaced.
    assert float(payload["threshold"]) == payload["method"]["bound"]
    assert payload["threshold_defaulted"] == payload["method"]["bound_defaulted"]


# ── the inputs are the ones the formula uses ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "verb,denominator,rowsum",
    [
        ("cost_lot_breakdown", "lot total", "contribution"),
        ("cost_labor_composition", "lot direct labor", "contribution"),
        ("cost_category_breakdown", "lot total", "contribution"),
        ("cost_supplier_concentration", "total purchased value", "contribution"),
    ],
)
def test_the_stated_DENOMINATOR_is_the_one_the_rows_add_up_to(verb, denominator, rowsum, state):
    """The block must be RECOMPUTABLE, which is the whole claim behind shipping it.

    Every one of these formulas divides by a total, and the total appears nowhere else in the
    payload for three of the four. A block naming a denominator that does not match the rows would
    be worse than no block: a reader who checked it would find a discrepancy in the figures and
    conclude the FIGURES were wrong.
    """
    payload = _payload(state, verb)
    stated = {i["name"]: i["value"] for i in payload["method"]["inputs"]}
    assert denominator in stated, f"{verb} does not state '{denominator}': {sorted(stated)}"
    total = Decimal(stated[denominator])
    summed = sum(Decimal(str(r[rowsum])) for r in payload["rows"])
    # The row figures are floats for the generic axis, so the comparison is to the cent rather
    # than exact -- an exact compare here would red on binary float noise and say nothing true.
    assert abs(total - summed) < Decimal("0.01"), f"{verb}: stated {total}, rows sum to {summed}"


@pytest.mark.parametrize(
    "verb,denominator,rowsum",
    [
        ("cost_lot_breakdown", "lot total", "contribution"),
        ("cost_labor_composition", "lot direct labor", "contribution"),
        ("cost_category_breakdown", "lot total", "contribution"),
        ("cost_supplier_concentration", "total purchased value", "contribution"),
    ],
)
def test_the_MONEY_input_carries_its_unit_and_the_COUNTS_carry_none(
    verb, denominator, rowsum, state
):
    """The unit is only worth having where it DISTINGUISHES, so both halves are asserted.

    THIS ARM EXISTS BECAUSE A MUTATION SURVIVED WITHOUT IT. Striking `VALUE_UNIT` off the "lot
    total" call site killed nothing: every other arm checked the unit's FORM when present and
    nothing checked its PRESENCE, so the one field the reconciliation added could be silently
    dropped from the one input that needs it. A shape sealed and a claim unsealed.

    The claim is that a card showing "31221216" beside "5" can tell dollars from a count. So the
    denominator — money in all four payloads — must state the unit, and every other input must
    OMIT the key: `"unit": None` on a count would read as an unknown currency, and a stated unit
    on a count would be a false dimension. Exactly one unit-bearing input per payload, and it is
    the one the formula divides by.
    """
    inputs = _payload(state, verb)["method"]["inputs"]
    by_name = {i["name"]: i for i in inputs}
    assert denominator in by_name, f"{verb} does not state {denominator!r} among its inputs"

    assert by_name[denominator].get("unit") == measures.VALUE_UNIT, (
        f"{verb}'s {denominator!r} is money and states unit="
        f"{by_name[denominator].get('unit')!r}"
    )
    united = sorted(n for n, i in by_name.items() if "unit" in i)
    assert united == [denominator], (
        f"{verb} states a unit on {united}; only the money denominator has a dimension here. "
        "Counts and identifiers are dimensionless BY OMISSION, which is the convention adopted "
        "unchanged from the other engine that emits this block"
    )


def test_the_formula_names_WHAT_THE_VERDICT_IS_ABOUT(state):
    """cost_category_breakdown's `favourable` is per-unit COST movement, not share movement.

    The obvious reading is the wrong one — a bucket's share can rise on a lot that got cheaper —
    and a card gives the reader no way to check which was meant. If the formula ever stops saying
    so, a red here is cheaper than a reader drawing the wrong conclusion in red.
    """
    formula = measures.cost_category_breakdown(state, lot=3)["method"]["formula"]
    assert "favourable = " in formula, formula
    # THE ASSERTION IS ON THE DEFINING CLAUSE, NOT ON THE WHOLE STRING. The first version of this
    # arm searched the whole formula for "per-unit" and SURVIVED the mutation that struck the word
    # out of the `favourable` definition — the formula's last sentence says "absent when the
    # per-unit figure did not move", so the search matched a neighbouring sentence and reported a
    # claim it had not checked. Narrow the subject to the clause that makes the claim.
    definition = formula.split("favourable = ", 1)[1].split(". ")[0]
    assert "PER-UNIT" in definition or "per-unit" in definition, definition
    assert "share" in definition, definition
    # The other half of the same sentence: where the verdict is ABSENT, which no card can show.
    assert "first lot" in formula and "did not move" in formula, formula


def test_the_helper_REFUSES_a_HALF_STATED_bound():
    """Both bad shapes, and the good one as the control.

    A bound with no word on where it came from, and a defaulted flag on a measure with no bound,
    are the two errors that read as deliberate. The control is here because a helper that refused
    everything would satisfy both raises and ship no method at all.
    """
    with pytest.raises(ValueError, match="disagree"):
        measures._method(formula="f", inputs=[], bound=0.25)
    with pytest.raises(ValueError, match="disagree"):
        measures._method(formula="f", inputs=[], bound_defaulted=True)
    with pytest.raises(ValueError, match="dropped"):
        measures._method(formula="   ", inputs=[measures._inp("a", 1)])
    # THE THIRD REFUSAL CAME WITH THE RECONCILIATION: a Decimal or a string bound means a call
    # site was left behind by the narrowing, which is a silent wrong shape rather than a crash.
    with pytest.raises(ValueError, match="float"):
        measures._method(formula="f", inputs=[], bound=Decimal("0.25"), bound_defaulted=True)
    with pytest.raises(ValueError, match="float"):
        measures._method(formula="f", inputs=[], bound="threshold = 0.25", bound_defaulted=True)

    ok = measures._method(formula="f", inputs=[measures._inp("a", Decimal("1.5"), "USD")],
                          bound=0.25, bound_defaulted=True)
    assert ok["inputs"] == [{"name": "a", "value": "1.5", "unit": "USD"}], (
        "Decimal must not reach the wire, and a stated unit must"
    )
    # AND THE OMISSION IS THE STATEMENT. `_inp` with no unit must produce no unit KEY — a helper
    # that wrote `"unit": None` would satisfy every other arm in this file and break the one
    # convention this reconciliation adopted from the other engine unchanged.
    assert measures._inp("a", 1) == {"name": "a", "value": "1"}
    assert "unit" not in measures._inp("a", 1)
    assert "unit" not in measures._inp("a", 1, None)
    assert "unit" not in measures._inp("a", 1, "")


def test_producer_sha_is_the_BAKED_one_and_None_when_UNATTESTED(monkeypatch, state):
    """None rather than a placeholder, in the two states that produce one.

    "unknown" is a sha-shaped string that matches no commit, and a reader must be able to tell
    "not attested" from "attested as this". Both the unset and the literal-"unknown" cases are
    driven because the engine has shipped both.
    """
    monkeypatch.setenv("IAGENT_GIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    assert (measures.cost_lot_breakdown(state, lot=3, rate_vintage="2021-02-01")
            ["method"]["producer_sha"]) == "0123456789abcdef0123456789abcdef01234567"

    monkeypatch.setenv("IAGENT_GIT_SHA", "unknown")
    assert (measures.cost_lot_breakdown(state, lot=3, rate_vintage="2021-02-01")
            ["method"]["producer_sha"]) is None

    monkeypatch.delenv("IAGENT_GIT_SHA", raising=False)
    assert (measures.cost_lot_breakdown(state, lot=3, rate_vintage="2021-02-01")
            ["method"]["producer_sha"]) is None


# ── the projector half ───────────────────────────────────────────────────────────────────────


def _projector():
    """The planning seal's loader, IMPORTED rather than copied.

    It execs only the projection helpers out of presentation_agent/main.py, which pulls fastapi
    and baml at import time. A second copy of that loader would be a second thing to fix the day
    the module's shape changes, and the copy that nobody fixed is the one that skips.
    """
    from tests.planning.test_planning_archetypes_are_projected import _envelope, _fns

    return _fns(), _envelope


_ROW = {"entity_id": "labor", "entity_name": "Labor", "contribution": 1.0, "rank": 1}
_METHOD = {"formula": "contribution = the recorded amount", "inputs": [{"name": "lot", "value": "3"}],
           "bound": None, "bound_defaulted": None, "producer_sha": "abc123"}


def test_the_projector_CARRIES_the_method_block():
    """The hop the producer's own tests cannot see.

    `_PROJECTED_ARCHETYPES` carries the payload key plus the fields declared in its tuple and
    NOTHING ELSE. This tuple has now dropped four separate envelope-level fields that producers
    emitted correctly the whole time, each found by looking at a card rather than at a test.
    """
    fns, envelope = _projector()
    got = fns["_project_planning_archetype"](
        "CONTRIBUTION_RANKING", envelope([_ROW], method=_METHOD), "X", None)
    assert got["method"] == _METHOD


def test_the_projector_INVENTS_no_method_when_the_producer_sent_none():
    """The other direction, and the half that makes the first one mean something.

    fin:VarianceDriverRanking and safety:OrphanedHazardSet render as this same archetype and emit
    no method block. A projection that always emitted the key would pass the arm above while
    fabricating a method for two producers that have none — and an invented method is worse than
    an absent one, because the absent one is visibly absent.
    """
    fns, envelope = _projector()
    got = fns["_project_planning_archetype"](
        "CONTRIBUTION_RANKING", envelope([_ROW]), "X", None)
    assert "method" not in got


def test_the_projected_component_is_what_the_UIs_export_reader_looks_AT():
    """cortex's `CardExportButton` reads `components[0].method` first, then the envelope's.

    So the field has to arrive on the COMPONENT, which is what the projector builds. Asserting the
    producer's block and the projector's tuple separately would leave exactly this step unstated —
    both sides correct, the relation asserted nowhere.
    """
    fns, envelope = _projector()
    state = build_state()
    payload = measures.cost_supplier_concentration(state, lot=3)
    got = fns["_project_planning_archetype"](
        "CONTRIBUTION_RANKING",
        envelope(payload["rows"], method=payload["method"],
                 threshold=payload["threshold"],
                 threshold_defaulted=payload["threshold_defaulted"]),
        "X", None)
    assert got["method"]["formula"] == payload["method"]["formula"]
    assert got["method"]["bound"] == payload["method"]["bound"]
    # The bound survives on BOTH wires, and they must still agree after the hop — as numbers,
    # because the two wires carry two representations of one local by design.
    assert float(got["threshold"]) == got["method"]["bound"]
