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
"""
from __future__ import annotations

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
                for v in d["values"]:
                    out.append((verb, d["name"], v))
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
                         ids=[f"{v}.{s}={val}" for v, s, val in COVERABLE])
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
