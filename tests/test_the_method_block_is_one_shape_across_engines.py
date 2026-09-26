"""THE PARITY SEAL: every engine that emits a `method` block emits the SAME block.

WHAT THIS EXISTS TO CATCH. Two engines produce CONTRIBUTION_RANKING payloads, and a card draws
whichever one answered. A shape agreed in a packet drifts silently, because each engine's own seal
is complete on its own side while the two disagree — the class of defect where two mirrors of one
declaration are each internally consistent and a row present in one and absent from the other is
invisible to every per-side check. So the shape is declared once in
`tests/_method_block_contract.py` and asserted HERE against every producer in the population, not
against each engine's restatement of it.

── WHAT IS TRUE TODAY, MEASURED AND NOT ASSUMED ──────────────────────────────────────────────
Only the COST engine emits a method block. That was established by running every producer in the
population, not by reading for one: `fin_variance_drivers` returns a bare LIST with no envelope at
all and no row carrying `method`, and `find_orphaned_hazards` returns an envelope with no `method`
in it. So the honest form of "parity" today is a PARTITION, not a comparison:

  * a producer that emits a block has it checked against the shared declaration; and
  * a producer that does not is named in `NO_BLOCK_YET` with its reason,

and BOTH DIRECTIONS FAIL. A producer in `NO_BLOCK_YET` that has started emitting a block reds
here, which is what makes this file non-vacuous the day lane/ca builds theirs: their block cannot
land in a wrong shape and pass, and it cannot land in the right shape and leave a stale "not yet"
behind. A comparison written against an implementation that does not exist would have been a seal
that cannot fail — the shape this repo has a name for.

── AND THE HAZARD THE RECONCILIATION EXPOSED ─────────────────────────────────────────────────
`_PROJECTED_ARCHETYPES` LIFTS A MISSING ENVELOPE FIELD OFF `rows[0]`. Adding `method` to the
CONTRIBUTION_RANKING allowlist therefore made every ROW-LEVEL `method` a candidate to be
presented as the envelope's method block. That is not hypothetical in this codebase: engine
finance already uses `method` as a row field on its EAC producers, where it holds the NAME of a
formula as a bare string. Those producers render as other archetypes today, so nothing is broken —
which is exactly why this arm is here rather than in a bug report. `readMethod` would return null
for a string and the card would read "method not supplied" about a producer that supplied a
formula name, with nothing anywhere going red.

Run: uv run --frozen pytest tests/test_the_method_block_is_one_shape_across_engines.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
from tests import _method_block_contract as contract

_CARD_EXPORT = (
    Path(__file__).resolve().parents[1].parent / "cortex-ui" / "src" / "lib" / "cardExport.ts"
)

#: Every subject the presentation agent renders as a contribution ranking. DERIVED: the
#: population is read from the registry that decides it, because "the six rankings" is a sentence
#: that goes stale the first time somebody adds a seventh.
RANKING_SUBJECTS = sorted(
    b["subject_uri"] for b in PRESENTATION_CAPABILITIES
    if b["archetype"] == "CONTRIBUTION_RANKING"
)

#: Producers that do NOT emit a block yet, each with its reason. An entry here is a claim, and the
#: arm below fails in BOTH directions — a producer that starts emitting one must come off this
#: list, and one that stops emitting one must go on it.
NO_BLOCK_YET = {
    "fin:VarianceDriverRanking": (
        "engine-finance. The order that reconciled this shape says lane/ca fixes their side, and "
        "they have not yet: measured, `fin_variance_drivers` returns a bare LIST with no envelope, "
        "so there is no sibling slot for a block to occupy — attaching one means the verb starts "
        "returning an envelope, which is a change to its return type and not a field addition"
    ),
    "safety:OrphanedHazardSet": (
        "engine-safety. It HAS an envelope, so the slot exists — but a count of orphaned hazards "
        "has no formula in the arithmetic sense, and the ranking's own legend says order and "
        "magnitude are different quantities here. Whether this producer should carry a block is a "
        "design question nobody has ruled on, which is a different state from not-done-yet"
    ),
}


def _cost_producers() -> dict[str, tuple]:
    from agent_fleet.cost_agent import measures as cost
    from agent_fleet.cost_agent.seed import build_state

    state = build_state()
    calls = {
        "cost_lot_breakdown": dict(lot=3, rate_vintage="2021-02-01"),
        "cost_labor_composition": dict(lot=3),
        "cost_category_breakdown": dict(lot=3),
        "cost_supplier_concentration": dict(lot=3),
    }
    verb_for = {uri.rsplit("#", 1)[-1]: fn for fn, uri in cost.OUTPUT_URI.items()}
    return {
        f"cost:{cls}": (getattr(cost, verb), state, calls[verb])
        for cls, verb in verb_for.items()
        if verb in calls
    }


def _finance_producers() -> dict[str, tuple]:
    from agent_fleet.finance_agent import measures as fin
    from agent_fleet.finance_agent.seed import build_seed

    state = build_seed()
    verb_for = {uri.rsplit("#", 1)[-1]: fn for fn, uri in fin.OUTPUT_URI.items()}
    verb = verb_for.get("VarianceDriverRanking")
    if verb is None:  # pragma: no cover - the engine's own table would have to have moved
        return {}
    return {
        "fin:VarianceDriverRanking": (
            getattr(fin, verb), state, dict(program_id=state.programs[0].program_id)
        )
    }


def _safety_producers() -> dict[str, tuple]:
    # NAMED, NOT DERIVED, and this is the one place in this file where that is true: engine-safety
    # has no OUTPUT_URI table to join a subject to a verb through. Said out loud because a hand
    # link is a sample of a population, and the partition arm below is what keeps this one honest.
    from agent_fleet.safety_agent import measures as safety

    return {"safety:OrphanedHazardSet": (safety.find_orphaned_hazards, None, {})}


def _producers() -> dict[str, tuple]:
    found: dict[str, tuple] = {}
    for build in (_cost_producers, _finance_producers, _safety_producers):
        found.update(build())
    return found


@pytest.fixture(scope="module")
def producers():
    return _producers()


def _run(spec) -> object:
    fn, state, kwargs = spec
    return fn(**kwargs) if state is None else fn(state, **kwargs)


def _envelope_of(out) -> dict:
    """The envelope, or `{}` for a producer that returns a bare list.

    A LIST IS NOT AN EMPTY ENVELOPE and conflating them is how this arm could have read
    "no method block" about a producer that has no place to put one. The distinction is reported
    by `test_a_producer_with_no_envelope_has_nowhere_to_put_a_block`, so this helper can be blunt.
    """
    return out if isinstance(out, dict) else {}


def _rows_of(out) -> list:
    if isinstance(out, dict):
        rows = out.get("rows") or []
    else:
        rows = out or []
    return [r for r in rows if isinstance(r, dict)]


# ── the population ───────────────────────────────────────────────────────────────────────────


def test_every_ranking_producer_is_REACHED_or_decided(producers):
    """Every derived subject has a producer this file actually CALLS, or the partition fails.

    A subject in the population that no arm reaches is a gap that reads as coverage: the file is
    green, the count looks right, and the one producer nobody ran is the one that drifted.
    """
    reached = set(producers)
    undecided = [s for s in RANKING_SUBJECTS if s not in reached]
    assert undecided == [], (
        f"{undecided} render as CONTRIBUTION_RANKING and no producer in this file calls them. "
        "Add the call, or the shape is unchecked for them"
    )
    stale = sorted(reached - set(RANKING_SUBJECTS))
    assert stale == [], (
        f"{stale} are called here and no longer render as CONTRIBUTION_RANKING; a producer whose "
        "archetype moved needs its block rechecked against the new archetype's allowlist"
    )
    assert len(RANKING_SUBJECTS) >= 6, (
        f"only {len(RANKING_SUBJECTS)} ranking subjects were derived; the registry that decides "
        "this population has shrunk or the join broke, and either way the arms below are weaker "
        "than they read"
    )


# ── the shape, per producer, both directions ─────────────────────────────────────────────────


def test_a_producer_that_emits_a_block_emits_THE_declared_one(producers):
    """One shape, checked by the shared checker against every block in the fleet.

    The reasons come back as sentences so a wrong-shaped block reports ALL of its departures at
    once. A producer reporting one departure per run is a producer somebody fixes one field at a
    time, which is how a reconciliation takes four passes.
    """
    emitted = {}
    for subject, spec in sorted(producers.items()):
        block = _envelope_of(_run(spec)).get("method")
        if block is not None:
            emitted[subject] = contract.check_block(block)

    assert emitted, (
        "no producer in the population emits a method block at all. This file would then be "
        "asserting nothing, which is the state it exists to make visible"
    )
    wrong = {s: r for s, r in emitted.items() if r}
    assert wrong == {}, wrong


def test_the_NOT_YET_list_fails_in_BOTH_directions(producers):
    """A producer that starts emitting a block comes off the list; one that stops goes on it.

    THIS IS THE ARM THAT MAKES THIS FILE NON-VACUOUS THE DAY lane/ca BUILDS THEIRS. Without it,
    a finance block in a wrong shape would simply not be looked at, and the file would stay green
    while the two engines disagreed — a seal whose register is accurate is blind, and this list is
    the register.
    """
    for subject, spec in sorted(producers.items()):
        has_block = _envelope_of(_run(spec)).get("method") is not None
        reason = NO_BLOCK_YET.get(subject)
        if has_block:
            assert reason is None, (
                f"{subject} NOW EMITS a method block and is still listed as not-yet, with the "
                f"reason: {reason!r}. Remove the entry — the block is checked by the arm above "
                "only for producers this list does not excuse"
            )
        else:
            assert reason, (
                f"{subject} emits NO method block and nothing says why. A ranking whose figures "
                "carry no account of themselves is either a gap or a decision, and a reader "
                "cannot tell which from silence"
            )


def test_a_producer_with_no_envelope_has_nowhere_to_put_a_block(producers):
    """A bare list is not an empty envelope, and the difference is what lane/ca has to build.

    Recorded as an assertion rather than a comment because it is the substantive part of the
    hand-off: attaching a block to `fin_variance_drivers` is a change to its RETURN TYPE, not a
    field addition, and a packet saying "add a method block" would understate it. If finance later
    grows an envelope this reds, which is the notification that the hand-off item is done.
    """
    shapes = {s: type(_run(spec)).__name__ for s, spec in sorted(producers.items())}
    listy = sorted(s for s, t in shapes.items() if t == "list")
    assert listy == ["fin:VarianceDriverRanking"], (
        f"the producers returning a bare list are {listy}; this arm records which rankings have "
        f"no envelope slot for a block. Full shapes: {shapes}"
    )


# ── the hazard the allowlist addition created ────────────────────────────────────────────────


def test_no_ranking_puts_METHOD_on_a_ROW(producers):
    """The projector LIFTS an absent envelope field off `rows[0]`, so a row-level `method` wins.

    `_PROJECTED_ARCHETYPES`'s loop reads the envelope, and where the field is absent it takes
    `rows[0].get(field)` instead. Adding `method` to the CONTRIBUTION_RANKING allowlist therefore
    made any row-level `method` a candidate for the block's slot — and engine-finance already uses
    `method` as a row field on its EAC producers, holding a formula's NAME as a bare string.

    Those producers render as other archetypes, so this reds on nothing today. That is the point:
    a hazard found while it is still latent costs an assertion, and the same hazard found later
    costs a card that says "method not supplied" with nothing going red anywhere.
    """
    offenders = {
        subject: [r["method"] for r in _rows_of(_run(spec))[:1]]
        for subject, spec in sorted(producers.items())
        if any("method" in r for r in _rows_of(_run(spec)))
    }
    assert offenders == {}, (
        f"{sorted(offenders)} carry `method` on a ROW. The projector lifts an absent envelope "
        f"field off rows[0], so this value would be presented as the method BLOCK: {offenders}. "
        "Rename the row field, or state the block on the envelope where the allowlist reads it"
    )


# ── the consumer's half, parsed, and PARTITIONED rather than compared ────────────────────────


def test_the_declared_fields_PARTITION_against_the_consumers_interfaces():
    """Every declared field is in the consumer's interface, or beyond it WITH A REASON.

    NOT AN EQUALITY CHECK, and the difference matters. `unit` is on the wire and cortex's
    `MethodInput` has no such field — `readMethod` builds `{name, value}` and drops it. An equality
    arm would have to either fail on a field the order asked for or quietly exclude it; a partition
    reports the third bucket, UNDECIDED, and fails on it.
    """
    if not _CARD_EXPORT.is_file():
        pytest.skip(f"cortex-ui not checked out at {_CARD_EXPORT}; the consumer's half is unread")
    src = _CARD_EXPORT.read_text(encoding="utf-8")

    in_ui, with_reason, undecided = contract.partition_against_the_ui(
        contract.BLOCK_FIELDS, contract.ui_block_fields(src), contract.BLOCK_FIELDS_BEYOND_THE_UI
    )
    assert undecided == [], (
        f"block fields {undecided} are in neither the consumer's interface nor "
        "BLOCK_FIELDS_BEYOND_THE_UI with a reason"
    )
    assert sorted(in_ui) == sorted(contract.BLOCK_FIELDS_IN_THE_UI)
    assert sorted(with_reason) == sorted(contract.BLOCK_FIELDS_BEYOND_THE_UI)

    in_ui, with_reason, undecided = contract.partition_against_the_ui(
        contract.INPUT_FIELDS, contract.ui_input_fields(src), contract.INPUT_OPTIONAL
    )
    assert undecided == [], f"input fields {undecided} are undecided against MethodInput"
    assert sorted(in_ui) == sorted(contract.INPUT_REQUIRED)
    # THE ONE ON THE WIRE AHEAD OF THE CARD. When cortex gains `unit`, this arm reds — which is
    # the good news it should report rather than pass over in silence.
    assert with_reason == ["unit"], (
        f"the fields beyond MethodInput are {with_reason}; if `unit` is no longer among them, "
        "cortex has gained it and the reason in INPUT_OPTIONAL is now stale"
    )


# ── the checker itself ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "what,block,because",
    [
        ("not a mapping", ["formula"], "must be a mapping"),
        ("no formula", {"inputs": [], "bound": None}, "missing 'formula'"),
        ("blank formula", {"formula": "   ", "inputs": [], "bound": None}, "trims empty"),
        ("no inputs key", {"formula": "f", "bound": None}, "must be a LIST"),
        ("inputs as a mapping", {"formula": "f", "inputs": {"a": "1"}, "bound": None},
         "must be a LIST"),
        ("an input that is not a mapping", {"formula": "f", "inputs": ["a"], "bound": None},
         "not a mapping"),
        ("an input with no name", {"formula": "f", "inputs": [{"value": "1"}], "bound": None},
         "name=None"),
        ("a numeric input value",
         {"formula": "f", "inputs": [{"name": "a", "value": 1.5}], "bound": None},
         "drops the cents"),
        ('"unit": None',
         {"formula": "f", "inputs": [{"name": "a", "value": "1", "unit": None}], "bound": None},
         "NO UNIT KEY AT ALL"),
        ("a blank unit",
         {"formula": "f", "inputs": [{"name": "a", "value": "1", "unit": " "}], "bound": None},
         "omit the key instead"),
        ("an undeclared input field",
         {"formula": "f", "inputs": [{"name": "a", "value": "1", "units": "USD"}], "bound": None},
         "undeclared field 'units'"),
        ("a string bound", {"formula": "f", "inputs": [], "bound": "0.25",
                            "bound_defaulted": True}, "the shape is float|None"),
        ("a boolean bound", {"formula": "f", "inputs": [], "bound": True,
                             "bound_defaulted": True}, "not a numeric bound"),
        ("a bound with no flag", {"formula": "f", "inputs": [], "bound": 0.25}, "disagree"),
        ("a flag with no bound", {"formula": "f", "inputs": [], "bound": None,
                                  "bound_defaulted": False}, "disagree"),
        ("an undeclared block field", {"formula": "f", "inputs": [], "bound": None,
                                       "bound_defaulted": None, "producer_sha": None,
                                       "algorithm": "x"}, "undeclared field 'algorithm'"),
    ],
)
def test_the_CHECKER_refuses_each_wrong_shape_FOR_THE_RIGHT_REASON(what, block, because):
    """A POSITIVE CONTROL ON THE MATCHER, one case per rule, and it is not optional.

    Every arm above is worth exactly what `check_block` is worth. A checker that returned `[]` for
    everything would make this whole file green against any shape at all — a broken matcher returns
    nothing and nothing reads as conformance.

    AND THE REASON IS ASSERTED, NOT JUST THE REFUSAL, because a refusal for the wrong reason is a
    neighbour of the claim rather than the claim. Measured: disabling the `"unit": None` rule
    SURVIVED a run where this arm only asked "was it refused" — the next rule down catches a null
    as a malformed string and refuses it anyway, with a reason that tells a producer to fix their
    string instead of to omit the key. The refusal was intact and the CONVENTION was not.
    """
    reasons = contract.check_block(block)
    assert reasons != [], f"the checker accepted {what}: {block}"
    assert any(because in r for r in reasons), (
        f"the checker refused {what} but not for the stated reason ({because!r}); it said "
        f"{reasons}. A refusal that lands on a neighbouring rule leaves the rule under test dead"
    )


def test_the_CHECKER_accepts_the_conforming_control():
    """The other half: a checker that refused everything would satisfy every arm above."""
    ok = {
        "formula": "contribution = the recorded amount; share = contribution / total",
        "inputs": [
            {"name": "lot", "value": "3"},
            {"name": "lot total", "value": "31221216.00", "unit": "USD"},
            {"name": "compared_to_lot", "value": None},
        ],
        "bound": 0.25,
        "bound_defaulted": True,
        "producer_sha": None,
    }
    assert contract.check_block(ok) == [], contract.check_block(ok)

    # AND THE UNBOUNDED FORM, which is three of the four cost rankings: bound and flag both None.
    unbounded = dict(ok, bound=None, bound_defaulted=None)
    assert contract.check_block(unbounded) == [], contract.check_block(unbounded)


def test_the_BOUND_AGREEMENT_checker_refuses_each_disagreement():
    """`check_bound_agrees` is the only thing asserting an invariant BETWEEN three declarations,
    so it gets the same positive control as the block checker."""
    good = {
        "formula": "above = share > threshold",
        "inputs": [{"name": "threshold", "value": "0.25"}],
        "bound": 0.25,
        "bound_defaulted": True,
        "producer_sha": None,
    }
    assert contract.check_bound_agrees(
        good, envelope_threshold="0.25", bound_input_name="threshold"
    ) == []

    # the envelope disagrees
    assert contract.check_bound_agrees(
        good, envelope_threshold="0.30", bound_input_name="threshold"
    ) != []
    # the named input disagrees
    off = dict(good, inputs=[{"name": "threshold", "value": "0.30"}])
    assert contract.check_bound_agrees(
        off, envelope_threshold="0.25", bound_input_name="threshold"
    ) != []
    # the bound is named by NO input, which is how its name would vanish from the card
    nameless = dict(good, inputs=[{"name": "lot", "value": "3"}])
    assert contract.check_bound_agrees(
        nameless, envelope_threshold="0.25", bound_input_name="threshold"
    ) != []
    # and named TWICE, which is two statements of one bound with nothing choosing between them
    twice = dict(good, inputs=[{"name": "threshold", "value": "0.25"},
                               {"name": "threshold", "value": "0.25"}])
    assert contract.check_bound_agrees(
        twice, envelope_threshold="0.25", bound_input_name="threshold"
    ) != []
