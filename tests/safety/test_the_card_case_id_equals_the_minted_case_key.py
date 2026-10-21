"""The draft card's `review_request.case_id` equals the case key the gateway mints, for every level.

Engine S mirrors `iagent_pure.acceptance_request.acceptance_workflow_id` (its image does not ship
`iagent_pure`). The mirror is only safe while this seal holds: this test imports the real function;
the engine never does. The level set is derived from the ratified matrix, not typed here.

THE MISMATCH ARM is the positive control: with the mirror patched to today's short form (no level
suffix) the equality assertion goes RED by assertion, not by crash.
"""
from __future__ import annotations

import pytest

from ._engine_extra import requires_rdflib
from iagent_pure import acceptance_request as ar


def _one_hazard_per_level():
    """level label -> a fixture hazard id that resolves to it (derived by drafting every hazard)."""
    from agent_fleet.safety_agent import measures
    from agent_fleet.safety_agent import matrix
    labels = {lbl for lbl, _aud in matrix.known_cells().values()}
    seen = {}
    for hid in _hazard_ids():
        d = measures.draft_risk_assessment(hazard_id=hid)
        if d.get("risk_level") in labels and "review_request" in d:
            seen.setdefault(d["risk_level"], hid)
    return labels, seen


def _hazard_ids():
    from agent_fleet.safety_agent import measures
    return [f"HAZ-{n}" for n in range(1000, 1100)
            if "review_request" in _try(measures, f"HAZ-{n}")]


def _try(measures, hid):
    try:
        return measures.draft_risk_assessment(hazard_id=hid)
    except Exception:
        return {}


def _check_equal():
    from agent_fleet.safety_agent import measures
    labels, seen = _one_hazard_per_level()
    assert seen, "no fixture hazard reached any matrix level -- instrument failure"
    for level, hid in sorted(seen.items()):
        card = measures.draft_risk_assessment(hazard_id=hid)["review_request"]
        slug = card["payload"]["risk_level_slug"]
        assert card["case_id"] == ar.acceptance_workflow_id(hid, slug), (level, hid, card["case_id"])
        # and the slug is the one the minter's caller derives from the same request
        trig = ar.acceptance_trigger(card, authz_id="requester@example.org")
        assert trig["level_slug"] == slug
    return labels, seen


@requires_rdflib
def test_the_card_case_id_equals_the_minted_case_key_for_every_reachable_level():
    labels, seen = _check_equal()
    assert set(seen) <= labels


@requires_rdflib
def test_every_matrix_level_is_reached_by_the_seal_or_named_unreached():
    """A level no fixture hazard reaches is not silently skipped: the format is level-independent
    (slug is a string), so assert the mirror against the real function on EVERY matrix label."""
    from agent_fleet.safety_agent import measures, matrix
    for level in sorted({lbl for lbl, _ in matrix.known_cells().values()}):
        assert measures._case_id("HAZ-X", level.lower()) == ar.acceptance_workflow_id("HAZ-X", level.lower())


@requires_rdflib
def test_mismatch_arm_a_mirror_that_drops_the_level_suffix_turns_the_seal_red(monkeypatch):
    from agent_fleet.safety_agent import measures
    monkeypatch.setattr(measures, "_case_id", lambda hazard_id, level_slug: f"risk-acceptance-{hazard_id}")
    with pytest.raises(AssertionError) as ei:
        _check_equal()
    assert "risk-acceptance-HAZ-" in str(ei.value)
    print("MISMATCH-RED:", str(ei.value)[:200])
