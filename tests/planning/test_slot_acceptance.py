"""The acceptance schema: what a verb will and will not be told.

THE CLAIM UNDER TEST is not "the filter filters". It is that a spoken value can never reach
an argument the ROUTE supplies. `agent_fleet/planning_agent/main.py` computes
`baseline_state`, `touched_project_ids`, `ops` and `scenario_name` from the store and puts
them in the same `params` dict a caller's values land in. Those two populations sharing a
dict is why the boundary needs enforcing rather than documenting: `baseline_state: str` and
`site_id: str` are the same type with opposite provenance, and no type system carries the
difference.

WHY IT IS TESTED WITHOUT A MODEL. Every join in the slot pipeline except the last is
deterministic. Testing them against fixtures rather than a live extraction is not a
convenience — it means a red test names the join that broke instead of naming the weather.
"""
from __future__ import annotations

import pytest

from iagent_pure.slot_acceptance import (
    NOT_A_PERMITTED_VALUE,
    NO_DECLARATIONS,
    ROUTE_SUPPLIED,
    ROUTE_SUPPLIED_KINDS,
    SLOT_KINDS,
    UNDECLARED,
    accept_slots,
)

#: A verb's declarations, in the shape `slots_for()` derives and `mesh_slots` carries.
DECL = [
    {"name": "group_by", "kind": "spoken-optional", "type": "enum",
     "required": False, "values": ["org", "initiative"], "default": "org"},
    {"name": "window", "kind": "spoken-optional", "type": "str", "required": False},
    {"name": "baseline_state", "kind": "handle", "type": "PlanState", "required": True},
]


# ── what the carry is FOR ────────────────────────────────────────────────────

def test_a_spoken_value_reaches_the_verb():
    """The whole point. Without this the other tests describe a very safe way of doing
    nothing, which is what the system does today."""
    a = accept_slots({"group_by": "initiative"}, DECL)
    assert a.params == {"group_by": "initiative"}
    assert a.clean


# ── the boundary ─────────────────────────────────────────────────────────────

def test_a_spoken_value_for_a_HANDLE_slot_is_refused():
    """`baseline_state` is resolved by the route from the store. A caller naming it chooses
    what their own answer is computed against."""
    a = accept_slots({"baseline_state": "some-other-plan"}, DECL)
    assert a.params == {}, "a route-supplied argument was accepted from a speaker"
    assert [r.reason for r in a.refusals] == [ROUTE_SUPPLIED]


def test_the_boundary_holds_when_a_legitimate_slot_rides_along():
    """The realistic shape of the attack, and the one a naive 'reject the whole payload'
    guard gets wrong in the other direction: the good slot must still land."""
    a = accept_slots({"group_by": "initiative", "baseline_state": "x"}, DECL)
    assert a.params == {"group_by": "initiative"}
    assert [r.name for r in a.refusals] == ["baseline_state"]


def test_ceremony_kind_is_route_supplied_too():
    a = accept_slots({"actor": "someone-else"},
                     [{"name": "actor", "kind": "ceremony", "type": "str", "required": True}])
    assert a.params == {}
    assert a.refusals[0].reason == ROUTE_SUPPLIED


# ── the other refusals ───────────────────────────────────────────────────────

def test_an_undeclared_slot_is_dropped_rather_than_forwarded():
    """Forwarding reaches `func(state, **params)` and returns a 400 naming the ENGINE, which
    blames the wrong layer for the router's invention."""
    a = accept_slots({"group_by": "org", "sort_order": "desc"}, DECL)
    assert a.params == {"group_by": "org"}
    assert [(r.name, r.reason) for r in a.refusals] == [("sort_order", UNDECLARED)]


def test_a_value_outside_the_declared_enum_is_refused():
    """The values come out of the signature's `Literal`, so this is the verb's own
    vocabulary — not a guess about what it might accept."""
    a = accept_slots({"group_by": "by_vibes"}, DECL)
    assert a.params == {}
    assert a.refusals[0].reason == NOT_A_PERMITTED_VALUE


def test_a_free_text_slot_with_no_declared_values_takes_any_value():
    """Non-vacuity control for the test above: the enum check must not be a blanket refusal."""
    a = accept_slots({"window": "FY26-Q4"}, DECL)
    assert a.params == {"window": "FY26-Q4"} and a.clean


# ── fail closed ──────────────────────────────────────────────────────────────

def test_no_declarations_refuses_EVERYTHING():
    """The branch that keeps the carry dark until `mesh_slots` is projected. Absence of a
    declaration is not permission — treating it as such would make an unprojected verb more
    permissive than a declared one."""
    a = accept_slots({"group_by": "initiative"}, [])
    assert a.params == {}
    assert a.refusals[0].reason == NO_DECLARATIONS


def test_nothing_spoken_is_not_a_refusal():
    """Distinguishes 'asked for nothing' from 'asked and was refused' — today's every-call
    case, and it must not fill the log with noise."""
    assert accept_slots({}, []) == ({}, [])
    assert accept_slots(None, None).clean


# ── the seals: this module mirrors two things it must not drift from ─────────

def test_the_kind_vocabulary_MATCHES_the_producer():
    """Mirrored, not imported, so the BFF and the supervisor need not depend on an engine's
    package. A test is what makes a mirror safe."""
    from agent_fleet.planning_agent.slots import SLOT_KINDS as PRODUCER_KINDS
    assert tuple(SLOT_KINDS) == tuple(PRODUCER_KINDS)


def test_every_argument_the_ROUTE_INJECTS_is_declared_route_supplied():
    """THE DRIFT SEAL, and the one that actually protects the boundary.

    `run_measure` injects store-derived values into `params`. If a new injection site is
    added and its argument is declared `spoken-*`, the guard would wave it through — the
    exact defect this module exists to prevent, re-entering through the producer.

    Read out of the producer's own constant rather than re-listed here, so the two cannot
    disagree silently."""
    from agent_fleet.planning_agent.slots import HANDLE_SLOTS, slots_for
    from agent_fleet.planning_agent import measures

    injected = {name for names in HANDLE_SLOTS.values() for name in names}
    assert injected, "HANDLE_SLOTS is empty — this seal would pass over nothing"

    seen = set()
    for verb, names in HANDLE_SLOTS.items():
        assert getattr(measures, verb, None) is not None, (
            f"HANDLE_SLOTS names {verb!r}, which measures.py does not define")
        by_name = {d["name"]: d for d in slots_for(verb)}
        for name in names:
            assert name in by_name, f"{verb}: {name} declared a handle but absent from the signature"
            kind = by_name[name]["kind"]
            assert kind in ROUTE_SUPPLIED_KINDS, (
                f"{verb}.{name} is injected by the route but declared {kind!r} — "
                f"a spoken value would be accepted for it"
            )
            seen.add(name)
    assert seen == injected
