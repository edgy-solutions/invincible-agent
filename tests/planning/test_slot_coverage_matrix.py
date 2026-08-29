"""THE COVERAGE MATRIX — which declared slots are proven fillable, and which have never
been exercised at all.

WHAT THIS ANSWERS THAT 7-OF-7 DID NOT. The live acceptance battery ran seven hand-chosen
cases. Seven cases prove the mechanism EXISTS; they say nothing about the declared surface
they left untouched. This file walks that surface exhaustively and mechanically: every spoken
slot on every verb, every value of every enum, every route-supplied slot refused.

DERIVED FROM THE DECLARATIONS, NEVER HAND-LISTED. A hand-written case list drifts from the
declarations the moment a verb changes its signature, and drift is invisible — the list still
passes, over a smaller surface. Everything here is generated from `slots_for()` and from the
SEED, so adding a parameter to a measure adds a case automatically, and adding one nobody can
sample fails `test_every_declared_slot_is_covered` by name.

IT ASSERTS ARRIVAL AT THE VERB, not the filler's return value. That is row 4's lesson: a
value that is produced, accepted, and then dropped at any of the seven enumeration hops reads
as success and delivers nothing. Every case here goes through the real acceptance guard and
into the real measure over HTTP.

NO MODEL. This half is deterministic and exhaustive by construction; the model's ability to
PRODUCE these values from natural phrasings is the other half, measured live against a corpus
whose fairness is a human judgment.

READING A RED CELL? CHECK THIS HARNESS BEFORE THE ENGINE. The first run of this matrix
produced three failures and ALL THREE WERE THE INSTRUMENT: `period_caps` is a dict keyed BY
period and the sampler iterated its values (floats), reporting three `window` slots as
UNPROVEN; a verb with a spoken-MANDATORY slot cannot be exercised one slot at a time, so
every case measured its own omission; and `project_id` is OVERLOADED, carrying a phase id
when `kind="phase"`. A coverage report is unusually prone to this — it is an instrument whose
output is a list of accusations, and an accusation costs nothing to make. Confirm the case
against the engine by hand before believing the cell.

WHAT THIS MATRIX CANNOT SEE, stated so nobody assumes otherwise: a slot declared `str` over a
vocabulary that is CLOSED at runtime samples fine with one valid value and passes every
arrival case here. `direction` and `kind` were exactly that and were found by reading. The
seal at the bottom of this file closes that gap; the matrix does not.
"""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from agent_fleet.planning_agent import main as engine
from agent_fleet.planning_agent import measures
from agent_fleet.planning_agent.seed import build_seed
from agent_fleet.planning_agent.slots import slots_for
from agent_fleet.planning_agent.state import PlanStore
from iagent_pure.slot_acceptance import ROUTE_SUPPLIED, accept_slots

SEED = build_seed()


def _first_id(collection: str, attr: str):
    items = getattr(SEED, collection, None) or []
    items = list(items.values()) if isinstance(items, dict) else list(items)
    for it in items:
        v = getattr(it, attr, None)
        if v:
            return v
    return None


def _period():
    """A fiscal period the seed actually contains — not a plausible-looking literal. A period
    that does not exist raises NotInModel, and every `window` case would then fail for a
    reason unrelated to slot carriage.

    `period_caps` is a dict KEYED BY PERIOD; its values are cap amounts. The first version of
    this helper iterated the values looking for a `.period` attribute, found floats, and
    returned None — so all three `window` slots reported UNPROVEN. The matrix was accusing the
    system of a gap that belonged to the instrument, which is the failure mode a coverage
    report is most prone to."""
    caps = getattr(SEED, "period_caps", None) or {}
    keys = list(caps) if isinstance(caps, dict) else []
    return keys[0] if keys else None


#: How to SAMPLE a value for a slot that is not an enum. Keyed by slot name because the name
#: is what carries the referent — `site_id` and `capability_id` are both `str` and neither is
#: satisfiable by an arbitrary string. Enum slots need no entry: their values are declared.
#:
#: A slot with no entry here and no declared values is UNSAMPLEABLE and is reported as such
#: rather than silently skipped — that report is the point of the matrix.
_SAMPLERS = {
    # `project_id` is OVERLOADED by design: with `kind="phase"` it carries a PHASE id, and
    # a project id there raises NotInModel. Sampling is therefore kind-aware — see
    # `_required_params`. The verb's docstring calls this "the item"; the parameter name
    # does not, which is why the coupling has to be encoded here rather than assumed.
    "project_id":          lambda: _first_id("projects", "project_id"),
    "project_id@phase":    lambda: _first_id("phases", "phase_id"),
    "site_id":             lambda: _first_id("sites", "site_id"),
    "capability_id":       lambda: _first_id("capabilities", "capability_id"),
    "scope_initiative_id": lambda: _first_id("initiatives", "initiative_id"),
    "process_id":          lambda: _first_id("processes", "process_id"),
    "tech_id":             lambda: _first_id("technologies", "tech_id"),
    "window":              lambda: [_period()] if _period() else None,
    "as_of":               lambda: "2026-06-30",
}

_VERBS = sorted(n for n in dir(measures) if n.startswith("plan_") and slots_for(n))


def _required_params(verb: str, exclude: str = "", variant: str = "") -> dict:
    """The verb's spoken-MANDATORY slots, sampled.

    Without this, every case for a verb with a required parameter fails on the missing
    parameter rather than on the slot under test — the instrument would be measuring its own
    omission. `plan_dependency_neighborhood` requires `project_id`, so its four enum cases
    all failed with NotInModel until this existed."""
    out = {}
    for d in slots_for(verb):
        if d["kind"] != "spoken-mandatory" or d["name"] == exclude:
            continue
        key = d["name"]
        if key == "project_id" and variant == "phase":
            key = "project_id@phase"
        sampler = _SAMPLERS.get(key)
        if sampler:
            out[d["name"]] = sampler()
    return out


def _cases():
    """(verb, slot, value) for every SPOKEN slot — one case per enum value, one per
    sampleable free slot. Generated, so the surface cannot silently shrink."""
    out = []
    for verb in _VERBS:
        for d in slots_for(verb):
            if not d["kind"].startswith("spoken"):
                continue
            if d.get("values"):
                # A slot can be BOTH enum-valued and container-typed: `window` declares the
                # fiscal calendar as its vocabulary and takes `list[str]`. Generating the bare
                # value there produces `window="FY27-Q3"`, which the guard correctly refuses as
                # a wrong shape — so the matrix would report the engine broken for obeying its
                # own declaration. The container comes from the declared TYPE, not from a guess
                # about the slot.
                container = str(d.get("type") or "").startswith(("list[", "set[", "tuple["))
                for v in d["values"]:
                    out.append((verb, d["name"], [v] if container else v))
            else:
                sampler = _SAMPLERS.get(d["name"])
                out.append((verb, d["name"], sampler() if sampler else None))
    return out


CASES = _cases()
COVERABLE = [(v, s, val) for v, s, val in CASES if val is not None]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(engine, "STORE", PlanStore(build_seed()))
    with TestClient(engine.app) as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# The matrix itself
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("verb,slot,value", COVERABLE,
                         ids=[f"{v}.{s}={val if not isinstance(val, list) else '+'.join(map(str, val))}"
                              for v, s, val in COVERABLE])
def test_a_declared_slot_value_ARRIVES_at_the_verb(client, verb, slot, value):
    """Accepted by the guard AND honoured by the measure.

    The 200 is the weaker half of the claim and is asserted first so a 4xx names itself; the
    stronger half is that the guard did not quietly drop the slot on the way, which is what
    `accepted.params` proves."""
    # `variant` carries the value under test into the sampler, because a mandatory slot can
    # be COUPLED to it — `plan_dependency_neighborhood(kind="phase")` needs a phase id in
    # `project_id`. Without this the four enum cases failed on the coupling, not the carriage.
    spoken = {**_required_params(verb, exclude=slot, variant=str(value)), slot: value}
    accepted = accept_slots(spoken, slots_for(verb))
    assert accepted.params == spoken, (
        f"the guard refused a value the verb itself declares: {accepted.refusals}"
    )
    r = client.post(f"/measure/{verb}", json={"params": accepted.params})
    assert r.status_code == 200, (
        f"{verb}({slot}={value!r}, required={_required_params(verb, slot, str(value))}) -> "
        f"{r.status_code} {r.text[:180]}"
    )


@pytest.mark.parametrize("verb", _VERBS)
def test_every_route_supplied_slot_is_refused_from_a_speaker(verb):
    """The boundary, walked across the WHOLE surface rather than the two verbs that happened
    to be interesting. Fourteen handle/ceremony slots exist; every one of them must be
    unspeakable."""
    declared = slots_for(verb)
    handles = [d for d in declared if d["kind"] in ("handle", "ceremony")]
    if not handles:
        pytest.skip(f"{verb} declares no route-supplied slots")
    spoken = {d["name"]: "forged-by-a-speaker" for d in handles}
    accepted = accept_slots(spoken, declared)
    assert accepted.params == {}, f"{verb} accepted a spoken value for {list(accepted.params)}"
    assert {r.reason for r in accepted.refusals} == {ROUTE_SUPPLIED}


# ─────────────────────────────────────────────────────────────────────────────
# The report — what is NOT covered, said out loud
# ─────────────────────────────────────────────────────────────────────────────

def test_every_declared_slot_is_covered(capsys):
    """THE MATRIX, and the test that makes it a guard rather than a report.

    A slot with no declared values and no sampler cannot be exercised, so it is UNPROVEN —
    nothing in this suite shows a value for it reaching the verb. That is exactly where the
    next declaration defect hides: `window` was declared `str` for days while nothing
    exercised it, and `direction` was declared open `str` over a closed vocabulary until this
    matrix was built.

    Adding a parameter to a measure fails this test BY NAME until it is either sampleable or
    consciously excused."""
    uncovered = [(v, s) for v, s, val in CASES if val is None]

    by_verb: dict[str, list[str]] = {}
    for v, s, val in CASES:
        by_verb.setdefault(v, []).append(f"{s}={'ok' if val is not None else 'UNPROVEN'}")
    report = ["", "SLOT COVERAGE MATRIX", "=" * 62]
    for v in _VERBS:
        report.append(f"  {v:30s} {', '.join(by_verb.get(v, [])) or '(no spoken slots)'}")
    report.append("-" * 62)
    report.append(f"  spoken slot-values exercised : {len(COVERABLE)}")
    report.append(f"  unproven                     : {len(uncovered)}")
    with capsys.disabled():
        print("\n".join(report))

    assert not uncovered, (
        "declared but never exercised — add a sampler in _SAMPLERS or excuse it "
        f"explicitly: {uncovered}"
    )


def test_the_matrix_is_not_vacuous():
    """A generated suite that generates nothing passes loudly and proves nothing. Pinned
    against the surface as counted on 2026-08-29: 11 verbs with declarations, 17 spoken
    slots, 12 enum values across 4 enum slots. These are LOWER bounds — the surface may
    grow, and growth should not be a failure."""
    enum_slots = [(v, d) for v in _VERBS for d in slots_for(v) if d.get("values")]
    enum_values = sum(len(d["values"]) for _, d in enum_slots)
    spoken = [(v, d) for v in _VERBS for d in slots_for(v) if d["kind"].startswith("spoken")]

    assert len(_VERBS) >= 11, f"verbs with declarations dropped to {len(_VERBS)}"
    assert len(spoken) >= 17, f"spoken slots dropped to {len(spoken)}"
    assert enum_values >= 12, (
        f"enum VALUES dropped to {enum_values} — a Literal became a bare `str` and the "
        f"router is now advertising free text over a closed vocabulary"
    )
    assert len(COVERABLE) >= enum_values, "enum values are not all being exercised"


# ─────────────────────────────────────────────────────────────────────────────
# The seal the matrix itself CANNOT provide
# ─────────────────────────────────────────────────────────────────────────────

def _closed_vocabulary_violations():
    """Spoken slots declared OPEN (`str`) whose body validates them against a CLOSED,
    literal vocabulary.

    Returns (verb, slot, rhs_source) triples. Separated from the test so the positive
    control can drive the same logic over deliberately-broken source."""
    import ast

    src = pathlib.Path(measures.__file__).read_text(encoding="utf-8")
    return _violations_in(src, ast.parse(src))


def _violations_in(src, tree):
    import ast

    # Module-level names bound to a literal tuple/list/set of constants, or to get_args(...)
    # of a Literal — both are closed vocabularies written down somewhere other than the
    # annotation.
    const_names = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        val = node.value
        literal_seq = (isinstance(val, (ast.Tuple, ast.List, ast.Set))
                       and val.elts and all(isinstance(e, ast.Constant) for e in val.elts))
        for t in node.targets:
            if isinstance(t, ast.Name) and literal_seq:
                const_names.add(t.id)

    out = []
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for verb, fn in fns.items():
        if not verb.startswith("plan_"):
            continue
        # Annotations read from THIS source, not from the live module. The first version
        # called `slots_for(verb)` — so the positive control, which supplies synthetic
        # source, was scored against the REAL module's annotations and reported the defect
        # as absent. The harness was grading the wrong system, which is this file's own
        # recurring failure mode and is why the control exists at all.
        declared_open = set()
        for a in list(fn.args.args) + list(fn.args.kwonlyargs):
            ann = ast.get_source_segment(src, a.annotation) if a.annotation else ""
            if ann and "Literal" not in ann:
                declared_open.add(a.arg)
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)):
                continue
            if not any(isinstance(o, (ast.In, ast.NotIn)) for o in node.ops):
                continue
            if node.left.id not in declared_open:
                continue  # annotated with a Literal — declared honestly
            rhs = node.comparators[0]
            closed = (
                (isinstance(rhs, (ast.Tuple, ast.List, ast.Set)) and rhs.elts
                 and all(isinstance(e, ast.Constant) for e in rhs.elts))
                or (isinstance(rhs, ast.Name) and rhs.id in const_names)
            )
            # An ATTRIBUTE or CALL on the right is a data lookup, not a vocabulary:
            # `process_id in c.enables_process_ids` asks whether a capability enables a
            # process. Flagging it would be the instrument manufacturing work.
            if closed:
                out.append((verb, node.left.id, ast.get_source_segment(src, rhs)))
    return out


def test_no_runtime_closed_vocabulary_is_declared_as_open_text():
    """A DECLARATION DERIVED FROM AN IMPRECISE ANNOTATION IS IMPRECISE IN THE DIRECTION OF
    PERMISSIVENESS — and permissive declarations do not fail closed, they INVITE.

    `slots_for` derives `values` from a `Literal` and nothing from a bare `str`. So a
    parameter whose body validates it against a closed set, but whose annotation is `str`,
    is advertised to the router as free text: the model may invent `"forwards"`, and the
    engine answers 422 to a question the system told it it could ask.

    THE COVERAGE MATRIX CANNOT SEE THIS. A closed-vocabulary `str` samples fine with one
    valid value and passes every arrival case. `direction` and `kind` were exactly that, and
    they were found by reading, not by the matrix. This is the seal that closes the gap the
    matrix leaves.

    The rule distinguishes a VOCABULARY from a LOOKUP: a literal sequence (or a module
    constant bound to one) is a vocabulary and must be a `Literal`; an attribute or call on
    the right — `process_id in c.enables_process_ids` — is a data lookup and is left alone."""
    violations = _closed_vocabulary_violations()
    assert not violations, (
        "declared as open text but validated against a closed set — make the annotation a "
        f"Literal so the router can advertise the vocabulary: {violations}"
    )


def test_that_seal_has_teeth():
    """Shown RED before being trusted, on source that reintroduces the exact defect.

    Also pins the LOOKUP exclusion: the same source contains a data-lookup membership test,
    and a seal that flagged it would manufacture work by pointing at the wrong system —
    which is the failure mode this file's own harness bugs already demonstrated once."""
    import ast

    broken = '''
_DIRECTIONS = ("upstream", "downstream")

def plan_dependency_neighborhood(state, *, project_id: str, direction: str = "upstream"):
    if direction not in _DIRECTIONS:
        raise NotInModel("nope")
    if project_id in state.enables_process_ids:
        pass
'''
    found = _violations_in(broken, ast.parse(broken))
    names = {(v, s) for v, s, _ in found}
    assert ("plan_dependency_neighborhood", "direction") in names, (
        "the seal did not flag a closed vocabulary declared as `str` — it is vacuous"
    )
    assert ("plan_dependency_neighborhood", "project_id") not in names, (
        "the seal flagged a DATA LOOKUP as a vocabulary; it would manufacture work"
    )


def test_the_period_vocabulary_IS_the_one_the_measure_validates_against():
    """A DECLARATION THAT DISAGREES WITH THE CODE, IN THE RESTRICTIVE DIRECTION.

    `_periods()` in measures.py rejects anything not in `FISCAL_PERIODS`, so that table is the
    authority on what a period slot accepts. The first version of this vocabulary was sourced
    from a loaded plan's `period_caps` instead — the seed funds five periods while the calendar
    declares eight — so the router refused `FY27-Q2` as not-a-permitted-value while the measure
    accepted it and returned a row. A legitimate question, refused before it reached the thing
    that could answer it.

    Every earlier instance of this species was too PERMISSIVE and invited a wrong answer
    (`direction: str` over a closed set, `Optional[list[str]]` reported as `str`). This one was
    too RESTRICTIVE and refused a right one. Both come from deriving a contract from something
    that was never the contract.

    Asserted as SET EQUALITY, not containment: a superset would accept values the measure
    rejects, and a subset is the defect above."""
    from agent_fleet.planning_agent.entities import FISCAL_PERIODS

    declared = {d["name"]: d for d in slots_for("plan_site_load")}["window"].get("values")
    assert declared, "the window slot declares no vocabulary — 'this quarter' reaches the engine"
    assert set(declared) == set(FISCAL_PERIODS), (
        "the declared period vocabulary and the one the measure validates against disagree; "
        f"declared-only={sorted(set(declared) - set(FISCAL_PERIODS))} "
        f"measure-only={sorted(set(FISCAL_PERIODS) - set(declared))}"
    )


def test_every_period_slot_carries_the_vocabulary():
    """Keyed by parameter name, so a second period slot added without an entry silently goes
    back to accepting free text and reaching the engine as `unknown fiscal period(s)`."""
    from agent_fleet.planning_agent.slots import _PERIOD_SLOTS

    assert _PERIOD_SLOTS, "no period slots declared — this seal would pass over nothing"
    for verb in _VERBS:
        for d in slots_for(verb):
            if d["name"] in _PERIOD_SLOTS and d["kind"].startswith("spoken"):
                assert d.get("values"), f"{verb}.{d['name']} is a period slot with no vocabulary"


def test_a_period_slot_declares_WHICH_period_vocabulary_it_takes():
    """`window` and `as_of` are both `str` in the signature and are NOT the same vocabulary.
    One takes a fiscal label; the other takes an ISO date and compares it LEXICALLY, so a
    fiscal label there is a complete no-op rather than a weak filter."""
    from agent_fleet.planning_agent.slots import _PERIOD_KIND

    assert _PERIOD_KIND, "no period kinds declared — this seal would pass over nothing"
    window = {d["name"]: d for d in slots_for("plan_site_load")}["window"]
    as_of = {d["name"]: d for d in slots_for("plan_maturity_grid")}["as_of"]
    assert window.get("period") == "fiscal-period"
    assert as_of.get("period") == "date"


def test_as_of_carries_NO_vocabulary_until_it_can_actually_RESOLVE_one():
    """THE TRIPWIRE, and it fails in BOTH directions on purpose.

    Giving `as_of` the fiscal vocabulary today would make the router accept exactly the values
    the measure silently ignores — a guard certifying a no-op, which is worse than no guard
    because it reads as coverage. Measured: `as_of="FY26-Q4"` returns 8 rows, byte-identical
    to passing nothing, while `as_of="2025-01-01"` returns 0.

    So the vocabulary and the resolution must arrive TOGETHER:

      * vocabulary present, resolution absent -> the router certifies a no-op;
      * resolution present, vocabulary absent -> the router forwards a fiscal label the
        resolver could have handled, and the silent path stays open.

    `_resolve_period_to_date` is the marker for "resolution exists". When fiscal->date
    resolution lands, this test tells whoever built it to attach the vocabulary in the same
    change — which is the point of a tripwire over a comment."""
    from agent_fleet.planning_agent import slots as slots_mod

    as_of = {d["name"]: d for d in slots_for("plan_maturity_grid")}["as_of"]
    resolution_exists = hasattr(slots_mod, "_resolve_period_to_date")
    # The "vocabulary" for a date-taking period slot is `period_end` — the label->date
    # boundaries the router resolves through — not `values`. `values` would be an acceptance
    # SET, and an acceptance set is wrong here: the slot also legitimately takes a bare ISO
    # date, which no fiscal vocabulary contains.
    has_vocabulary = bool(as_of.get("period_end"))

    assert has_vocabulary == resolution_exists, (
        "as_of's vocabulary and its fiscal->date resolution must land together. "
        f"vocabulary={'present' if has_vocabulary else 'absent'}, "
        f"resolution={'present' if resolution_exists else 'absent'}. "
        "A vocabulary without resolution certifies a no-op; resolution without a vocabulary "
        "leaves the silent path open."
    )
