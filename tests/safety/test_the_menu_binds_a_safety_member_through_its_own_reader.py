"""Engine S's enumerated members must survive the menu's own reader.

The reader is `iagent_pure.slot_disposition.decide_disposition` (builds each Option from
`m.get("instance_id")` and drops a member without one; slot_disposition.py ~478-482), and
`ontology_service.main._bind_from_scope` (~3181) filters the same key. Engine S used to publish
`identifier` only, so the menu for `hazard_id` was empty. The seal drives the REAL route into the
REAL reader; no key is restated here beyond the control's deliberate shape.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_fleet.safety_agent import entities, slots
from agent_fleet.safety_agent.main import app
from iagent_pure.slot_disposition import decide_disposition

HAZARD = "http://internal/sustainment/safety#Hazard"


def _route(class_uri, *, bound_slots=None):
    r = TestClient(app).post("/enumerate_instances", json={"class_uri": class_uri})
    assert r.status_code == 200
    return r.json()


def _identifier_only(class_uri, *, bound_slots=None):
    """THE CONTROL: today's shape before the fix -- the same members under `identifier` only."""
    body = _route(class_uri)
    body["members"] = [{"identifier": m["identifier"], "label": m["label"]} for m in body["members"]]
    return body


def _offered(provider):
    disp = decide_disposition(
        accepted={}, declared=slots.slots_for("draft_risk_assessment"), enumerate_class=provider
    )
    return disp, [o.value for o in disp.options]


def test_every_held_hazard_binds_through_the_menus_own_code():
    disp, ids = _offered(_route)
    assert disp.slot == "hazard_id"
    assert set(ids) == {h.hazard_id for h in entities.HAZARDS}
    assert "HAZ-1004" in ids


def test_control_an_identifier_only_provider_offers_no_option():
    disp, ids = _offered(_identifier_only)
    assert ids == [], "the reader must drop identifier-only members, or this control proves nothing"


def test_both_keys_carry_the_same_value():
    for m in _route(HAZARD)["members"]:
        assert m["instance_id"] == m["identifier"]


import pytest  # noqa: E402


def test_my_side_claims_haz_1004_exactly_once():
    """Engine S's half of the double claim: one candidate, one class, for the exact id."""
    r = TestClient(app).post("/resolve_instance", json={"identifier": "HAZ-1004", "query": "HAZ-1004"})
    cands = r.json()["candidates"]
    assert [(c["instance_id"], c["class_uri"]) for c in cands] == [("HAZ-1004", HAZARD)]


@pytest.mark.skip(reason=(
    "BLOCKED on lane/74 (owns engine_o_sustainment): it also claims HAZ-1004 as a "
    "pcn#Component, so fill_slots refuses the bind as ambiguous_in_domain. RULED (architect, "
    "Q3): HAZ-* belongs to the safety engine, an identifier namespace is claimed by exactly one "
    "engine, and engine-o stops matching HAZ-. Packet: 2026-10-12-packet-to-74-engine-o-"
    "sustainment-resolver-stops-matching-haz-ruled-and-a-namespace-field-ask.md. Unskip when "
    "engine-o lands it: fan out _call_resolver over every mesh:resolveInstance provider and "
    "assert exactly one candidate overall."
))
def test_haz_1004_resolves_to_exactly_one_candidate_across_the_fan_out():
    raise AssertionError("unreachable until the other claimant is named and fixed")
