"""ADR-0051 seals 8 and 12, plus the three-state control that makes seal 8 a measurement.

SEAL 8 IS CARDINALITY, IN BOTH DIRECTIONS. "The orphans are in the result" cannot see an extra
one, and "the result has three rows" cannot see the wrong three. Containment and count are
different assertions and both are here, plus the two mutations: drop one and add one.

The number comes from the FIXTURE, which chose it (`EXPECTED_ORPHAN_COUNT`), not from the
verb. A seal that asks the verb how many it found and then checks that it found that many is
the shape that passes on every implementation including an empty one.
"""
from __future__ import annotations

import dataclasses

import pytest

from agent_fleet.safety_agent import measures
from agent_fleet.safety_agent.entities import (
    EXPECTED_ORPHAN_COUNT,
    HAZARDS,
    WRITE_UPS,
    WORK_ORDERS,
    CRITICAL_ITEMS,
    Hazard,
    Mitigation,
)

#: The three the fixture built, by id and by MECHANISM. Named here so a failure says which
#: mechanism stopped being detected rather than "expected 3, got 2".
EXPECTED_ORPHANS = {
    "HAZ-1001": "no mitigation recorded",
    "HAZ-1002": "mitigation recorded but no owner",
    "HAZ-1003": "mitigation owned but never verified in the field",
}


def test_orphan_count_is_exactly_what_the_fixture_built():
    """SEAL 8, forward: the count is N, and N is the fixture's number."""
    result = measures.find_orphaned_hazards()
    assert result["refused"] is False
    assert result["orphan_count"] == EXPECTED_ORPHAN_COUNT == 3
    assert {o["hazard_id"] for o in result["orphans"]} == set(EXPECTED_ORPHANS)


def test_each_orphan_reports_the_mechanism_that_orphaned_it():
    """A boolean would pass this suite and be useless in the queue.

    "Unowned" and "never verified" need different people to do different things, so the reason
    is asserted per hazard rather than merely being present.
    """
    result = measures.find_orphaned_hazards()
    got = {o["hazard_id"]: o["orphan_reason"] for o in result["orphans"]}
    assert got == EXPECTED_ORPHANS


def test_the_verified_and_closed_hazards_are_not_returned():
    """The controls. Without these the verb could return every hazard and pass on count alone
    only by coincidence of the fixture's size — so they are asserted by id."""
    result = measures.find_orphaned_hazards()
    ids = {o["hazard_id"] for o in result["orphans"]}
    assert "HAZ-1004" not in ids, "an owned, field-verified mitigation is not an orphan"
    assert "HAZ-1005" not in ids, "a closed hazard is not an orphan"


def test_not_assessed_is_reported_separately_and_never_counted_as_an_orphan():
    """THE THREE-STATE CONTROL, and the one that decides whether seal 8 measures anything.

    A verb that sorts `not_assessed` into "open" returns FOUR. A hazard nobody has
    characterised has a missing ASSESSMENT, not a missing mitigation, and a different person
    fixes it — merging them inflates the orphan count and buries the assessment gap.
    """
    result = measures.find_orphaned_hazards()
    assert "HAZ-1006" not in {o["hazard_id"] for o in result["orphans"]}
    assert [n["hazard_id"] for n in result["not_assessed"]] == ["HAZ-1006"]
    assert result["not_assessed_count"] == 1


# ---------------------------------------------------------------------------
# THE MUTATIONS. Seal 8 is not done until both have been RUN and gone red, and
# they are run here rather than by hand so they cannot rot.
# ---------------------------------------------------------------------------

def test_mutation_dropping_an_orphan_is_caught(monkeypatch):
    """DROP ONE -> the count must fall. Catches a verb that stops detecting a mechanism."""
    without_1002 = tuple(h for h in HAZARDS if h.hazard_id != "HAZ-1002")
    monkeypatch.setattr(measures, "HAZARDS", without_1002)
    result = measures.find_orphaned_hazards()
    assert result["orphan_count"] == 2, (
        "removing an orphan from the fixture must change the count — if this is still 3 the "
        "verb is not reading the fixture it is handed"
    )


def test_mutation_adding_an_orphan_is_caught(monkeypatch):
    """ADD ONE -> the count must rise. THE DIRECTION CONTAINMENT CANNOT SEE.

    A containment assertion ("the three expected ids are present") passes with a fourth orphan
    silently in the result. This is the half that catches an over-broad predicate.
    """
    extra = Hazard(
        hazard_id="HAZ-1099",
        description="Synthetic fourth orphan, added by the mutation.",
        status="open",
        severity="III",
        probability="C",
        tail="TN-7799",
        platform="PLT-DELTA",
        opened_on="2026-09-01",
        mitigations=(),
    )
    monkeypatch.setattr(measures, "HAZARDS", HAZARDS + (extra,))
    result = measures.find_orphaned_hazards()
    assert result["orphan_count"] == 4
    assert "HAZ-1099" in {o["hazard_id"] for o in result["orphans"]}


def test_mutation_verifying_the_paper_closed_mitigation_removes_exactly_one(monkeypatch):
    """THE PAPER-CLOSED CASE, proven to be what HAZ-1003 is detected BY.

    Flip only `verified_in_field` on MIT-2103 and the orphan count must fall to two. If it
    stays at three, the verb is finding HAZ-1003 for some other reason and the fixture's
    hardest case is being detected by accident.
    """
    patched = []
    for h in HAZARDS:
        if h.hazard_id == "HAZ-1003":
            mits = tuple(
                dataclasses.replace(m, verified_in_field="true") for m in h.mitigations
            )
            patched.append(dataclasses.replace(h, mitigations=mits))
        else:
            patched.append(h)
    monkeypatch.setattr(measures, "HAZARDS", tuple(patched))
    result = measures.find_orphaned_hazards()
    assert result["orphan_count"] == 2
    assert "HAZ-1003" not in {o["hazard_id"] for o in result["orphans"]}


# ---------------------------------------------------------------------------
# SEAL 12 — every identity-shaped field holds a different value.
# ---------------------------------------------------------------------------

def test_no_identity_value_is_shared_across_fixture_field_kinds():
    """SEAL 12. A read keyed on the WRONG field must fail rather than coincidentally pass.

    The law from `c849b1e`: a fixture that used one identity for two fields let nine tests pass
    over a defect that returned `404 "no artifact for you"` for 285 of 286 artifacts. Distinct
    values per field kind are what make a mis-keyed read visible.
    """
    buckets = {
        "hazard_id": {h.hazard_id for h in HAZARDS},
        "mitigation_id": {m.mitigation_id for h in HAZARDS for m in h.mitigations},
        "csi_id": {c.csi_id for c in CRITICAL_ITEMS},
        "part_number": {c.part_number for c in CRITICAL_ITEMS}
        | {w.part_number for w in WORK_ORDERS},
        "work_order_id": {w.work_order_id for w in WORK_ORDERS},
        "write_up_id": {w.write_up_id for w in WRITE_UPS},
        "tail": {h.tail for h in HAZARDS} | {w.tail for w in WRITE_UPS},
        "owner": {m.owner for h in HAZARDS for m in h.mitigations if m.owner},
    }
    names = list(buckets)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            overlap = buckets[a] & buckets[b]
            assert not overlap, f"{a} and {b} share identity value(s): {overlap}"


def test_no_identity_value_is_a_prefix_of_another():
    """Distinctness is not enough when a consumer does a prefix or substring match —
    `startswith` on an id is a real pattern, and two ids where one prefixes the other let it
    pass while matching the wrong row."""
    every = [
        v
        for bucket in (
            {h.hazard_id for h in HAZARDS},
            {m.mitigation_id for h in HAZARDS for m in h.mitigations},
            {c.csi_id for c in CRITICAL_ITEMS},
            {w.work_order_id for w in WORK_ORDERS},
            {w.write_up_id for w in WRITE_UPS},
        )
        for v in bucket
    ]
    for a in every:
        for b in every:
            if a != b:
                assert not a.startswith(b), f"{a!r} has {b!r} as a prefix"
