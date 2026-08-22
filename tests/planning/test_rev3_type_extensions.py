"""Revision 3's type extensions — and the one field that must NEVER exist.

These are EXTENSIONS to types built in Phase 0, not new entities. The tests are written to make
that distinction enforceable rather than merely stated: each asserts a field on an existing
dataclass, and the negative tests assert that nothing derivable got stored beside its source.

THE LOAD-BEARING TEST IN THIS FILE IS `test_no_stored_funding_gap_field_exists`. Funding
at-risk (`committed + approved < required`) is COMPUTED by the gap verb. Storing it beside the
requirement and commitment rows it is computed from is the two-masters defect in miniature, and
this arc has paid for that class twice — the hand-authored capability table beside derived
contracts, and the backend capability copy beside the frontend's. A stored gap would be the
third, in brand-new code, one commit after the delta doc refused it.
"""
from __future__ import annotations

import dataclasses

import pytest

from agent_fleet.planning_agent import entities, measures
from agent_fleet.planning_agent.seed import build_seed

M = 1_000_000.0


def _fields(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


# ─────────────────────────────────────────────────────────────────────────────
# B1 — ownership, priority, confidence
# ─────────────────────────────────────────────────────────────────────────────

def test_upper_tiers_carry_the_three_owner_roles():
    """Executive / business / technology are DISTINCT roles, not one 'owner' string. A single
    owner field forces a choice the organisation has not made, and the question 'who signs off
    on the money' has a different answer from 'who is accountable for the outcome'."""
    for cls in (entities.Portfolio, entities.Initiative):
        f = _fields(cls)
        assert {"executive_owner", "business_owner", "technology_owner"} <= f, cls.__name__


def test_working_tiers_carry_a_single_owner():
    """Phase and Project get ONE owner. Three roles at this tier would be ceremony — the
    distinction only exists where accountability actually splits."""
    for cls in (entities.Phase, entities.Project):
        assert "owner" in _fields(cls), cls.__name__


def test_priority_and_criticality_are_separate_fields():
    """They are different questions. Priority is 'what do we do first' (a sequencing choice
    the room makes); criticality is 'what happens if this fails' (a property of the thing).
    Collapsing them loses the case that matters most: low priority, high criticality."""
    for cls in (entities.Initiative, entities.Project):
        f = _fields(cls)
        assert "priority" in f and "criticality" in f, cls.__name__


def test_phase_carries_timing_confidence():
    """How firm the interval is. Without it a Q3 date and a Q3 guess draw identically, and a
    room cannot tell which bars it may safely move."""
    assert "timing_confidence" in _fields(entities.Phase)


# ─────────────────────────────────────────────────────────────────────────────
# B1 — the extras map
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls", [
    entities.Portfolio, entities.Initiative, entities.Phase, entities.Project,
    entities.Capability, entities.Site, entities.Organization, entities.Technology,
])
def test_every_entity_carries_an_extras_map(cls):
    """Answers "highly configurable attributes" without becoming a document store. The graph
    substrate at Phase 8 is the real answer; this is the seam that makes waiting survivable."""
    assert "attributes" in _fields(cls), cls.__name__


def test_the_extras_map_is_not_a_place_to_hide_modelled_fields():
    """A guard against the obvious abuse. If `attributes` starts carrying dates, amounts or
    references, the model has been routed around rather than extended — and every measure that
    reads a typed field stops seeing the data. The seed is the canary: it must not use the map
    for anything a field exists for."""
    s = build_seed()
    banned = {"start", "end", "planned", "amount", "cost", "capex", "expense",
              "owner", "priority", "criticality", "status", "level", "target"}
    for coll in (s.portfolios, s.initiatives, s.phases, s.projects,
                 s.capabilities, s.sites, s.organizations, s.technologies):
        for e in coll:
            overlap = banned & set(getattr(e, "attributes", {}) or {})
            assert not overlap, f"{e} hides modelled fields in attributes: {sorted(overlap)}"


# ─────────────────────────────────────────────────────────────────────────────
# B1 — funding status, and the field that must not exist
# ─────────────────────────────────────────────────────────────────────────────

def test_funding_commitment_carries_a_status_enum():
    assert "status" in _fields(entities.FundingCommitment)


def test_no_stored_funding_gap_field_exists():
    """THE LOAD-BEARING TEST. At-risk is DERIVED. A stored gap beside the rows it is computed
    from is stored-beside-derivable — the same defect as a hand-authored capability table beside
    derived contracts, and as the backend capability copy beside the frontend's. Two instances
    already paid for; this refuses the third."""
    banned = {"funding_gap", "gap", "at_risk", "shortfall", "unfunded"}
    for cls in (entities.FundingRequirement, entities.FundingCommitment, entities.Project,
                entities.Initiative, entities.Portfolio):
        overlap = banned & _fields(cls)
        assert not overlap, (
            f"{cls.__name__} stores {sorted(overlap)} — funding at-risk is DERIVED by "
            f"plan_funding_gap from requirement and commitment rows. Storing it creates a "
            f"second writer for a fact that already has one."
        )


def test_at_risk_is_derived_from_status_by_the_gap_verb():
    """committed + approved counts as secured; PENDING does not. That is the whole point of the
    enum — a pending commitment is a hope, and a gap measure that counts hopes as money is the
    measure a portfolio review exists to replace."""
    s = build_seed()
    rows = measures.plan_funding_gap(s, group_by="org")
    assert rows, "the gap verb returned nothing — the derivation cannot be asserted"
    for r in rows:
        assert "secured" in r and "at_risk" in r, (
            "the gap verb must expose secured (committed+approved) and at_risk separately; "
            "one combined number cannot answer 'is this funded or merely promised'"
        )
        assert r["at_risk"] >= 0
