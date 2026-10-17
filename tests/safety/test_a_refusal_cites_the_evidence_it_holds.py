"""hazard_closed and not_assessed refusals cite what the engine HOLDS (ruled 2026-10-17):
ids and held values only; a closed hazard says plainly that no closure record is held.
Each CONTROL differs from its subject in exactly one thing."""
from __future__ import annotations

import dataclasses

from agent_fleet.safety_agent import entities, measures


def _with(monkeypatch, hid, **kw):
    monkeypatch.setitem(measures.BY_HAZARD_ID, hid, dataclasses.replace(entities.BY_HAZARD_ID[hid], **kw))


def test_closed_cites_status_levels_mitigation_and_the_absent_closure_record():
    b = measures.draft_risk_assessment(hazard_id="HAZ-1005")
    assert b["outcome"] == "hazard_closed"
    assert b["reason"] == (
        "hazard 'HAZ-1005' is closed; there is no open risk to accept. Held: status closed; "
        "severity IV, probability E; mitigations MIT-2105 (owner tech.pubs@example.invalid, "
        "verified_in_field true). No closure record (date, closer) is held.")
    assert b["evidence"]["mitigations"] == [{"mitigation_id": "MIT-2105",
        "owner": "tech.pubs@example.invalid", "verified_in_field": "true"}]
    assert b["evidence"]["closure_record"] == "not held"
    assert "closed_on" not in b["evidence"] and "closed_by" not in b["evidence"]


def test_closed_with_no_mitigations_says_so(monkeypatch):
    _with(monkeypatch, "HAZ-1005", mitigations=())
    b = measures.draft_risk_assessment(hazard_id="HAZ-1005")
    assert b["reason"] == (
        "hazard 'HAZ-1005' is closed; there is no open risk to accept. Held: status closed; "
        "severity IV, probability E; no mitigations recorded. No closure record (date, closer) is held.")
    assert b["evidence"]["mitigations"] == []


def test_closed_holds_an_unowned_unverified_mitigation_as_held_not_as_defaulted(monkeypatch):
    m = dataclasses.replace(entities.BY_HAZARD_ID["HAZ-1005"].mitigations[0], owner=None,
                            verified_in_field="not_verified")
    _with(monkeypatch, "HAZ-1005", mitigations=(m,))
    b = measures.draft_risk_assessment(hazard_id="HAZ-1005")
    assert "MIT-2105 (owner none recorded, verified_in_field not_verified)" in b["reason"]


def test_not_assessed_cites_gap_other_half_opened_on_and_what_to_obtain():
    b = measures.draft_risk_assessment(hazard_id="HAZ-1006")
    assert b["outcome"] == "not_assessed"
    assert b["reason"] == (
        "hazard 'HAZ-1006' has not been assessed: severity is not assessed on this hazard; no risk "
        "level is resolved and no authority is implied. Held: status not_assessed; neither severity "
        "nor probability held; opened 2026-08-30. To proceed, obtain a severity and probability "
        "assessment for HAZ-1006.")
    assert b["evidence"]["opened_on"] == "2026-08-30" and b["evidence"]["hazard_id"] == "HAZ-1006"


def test_not_assessed_with_severity_held_names_the_missing_probability_and_the_held_severity(monkeypatch):
    _with(monkeypatch, "HAZ-1006", severity="IV")
    b = measures.draft_risk_assessment(hazard_id="HAZ-1006")
    assert b["reason"].endswith("Held: status not_assessed; severity IV held; opened 2026-08-30. "
                                "To proceed, obtain a probability assessment for HAZ-1006.")


def test_not_assessed_with_probability_held_names_the_missing_severity(monkeypatch):
    _with(monkeypatch, "HAZ-1006", probability="E")
    b = measures.draft_risk_assessment(hazard_id="HAZ-1006")
    assert "probability E held" in b["reason"] and "obtain a severity assessment" in b["reason"]


def test_CONTROL_an_open_hazard_is_not_refused_and_carries_no_evidence_block(monkeypatch):
    _with(monkeypatch, "HAZ-1005", status="open")
    b = measures.draft_risk_assessment(hazard_id="HAZ-1005")
    assert b["refused"] is False and "evidence" not in b
