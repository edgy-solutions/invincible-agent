"""Answer -> workflow-step seeding sealed deterministically (ADR-0029 Slice 4 / ADR-0028 Use-3).

Proves the two guarantees the design promises:
  * a grounded answer seeds a valid spo_operation step (native SPO extraction);
  * a fallback / ungrounded answer is NOT seedable (returns a reason, never a fabricated step);
  * seeding INHERITS ENFORCEMENT — the seeded (subject, verb) must be eligible for the SEEDER
    (PickRefused otherwise), so an answer is provenance, not authority.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest pytest ../../tests/test_answer_step_seeding.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst import answer_step_seeding as seed  # noqa: E402
from agent_fleet.restate_analyst import spo_interview as si  # noqa: E402
from agent_fleet.restate_analyst.workflow_definition import WorkflowDefinition  # noqa: E402

# A grounded, non-fallback, STRONG-provenance answer's routing (gateway shape).
GROUNDED = {
    "about": {"uri": "http://invincible-agent/idp#Dataset", "label": "Dataset", "confidence": 0.91},
    "action": {"iri": "mesh:lookupOwnership", "label": "Lookup Ownership"},
    "handled_by": {"engine_name": "Engine A"},
    "fallback": False,
}
FALLBACK = {
    "about": {"uri": "UNKNOWN", "label": "Not grounded"},
    "action": {"iri": "UNKNOWN", "label": "General search"},
    "fallback": True,
}

# The seeder's CURRENT authorized sets (Slice-2 shapes).
SEEDER_SUBJECTS = [{"uri": "http://invincible-agent/idp#Dataset", "label": "Dataset"}]
SEEDER_VERBS = [{"verb_iri": "mesh:lookupOwnership", "output_uri": "http://invincible-agent/mesh#OwnershipFact"}]


# ---------------------------------------------------------------------------
# Native extraction
# ---------------------------------------------------------------------------

def test_grounded_answer_seeds_spo_step():
    step, reason = seed.seed_step_from_answer(
        GROUNDED, verb_output_uri="http://invincible-agent/mesh#OwnershipFact")
    assert reason is None
    assert step["kind"] == "spo_operation"
    assert step["subject"] == "http://invincible-agent/idp#Dataset"
    assert step["verb"] == "mesh:lookupOwnership"
    assert step["expected_output"] == "http://invincible-agent/mesh#OwnershipFact"
    assert step["id"] == "lookupOwnership_Dataset"


def test_seeded_step_is_a_valid_workflow_step():
    """The seeded step round-trips as a real SpoOperationStep in a WorkflowDefinition."""
    step, _ = seed.seed_step_from_answer(GROUNDED)
    wf = WorkflowDefinition.model_validate({"id": "from_answer", "name": "From an answer", "steps": [step]})
    assert wf.steps[0].kind == "spo_operation"
    assert wf.steps[0].verb == "mesh:lookupOwnership"


# ---------------------------------------------------------------------------
# Not seedable — refuse honestly, never fabricate
# ---------------------------------------------------------------------------

def test_fallback_answer_not_seedable():
    step, reason = seed.seed_step_from_answer(FALLBACK)
    assert step is None and "fallback" in reason


def test_ungrounded_subject_not_seedable():
    r = {"about": {"uri": "UNKNOWN"}, "action": {"iri": "mesh:lookupOwnership"}, "fallback": False}
    step, reason = seed.seed_step_from_answer(r)
    assert step is None and "subject" in reason


def test_ungrounded_verb_not_seedable():
    r = {"about": {"uri": "http://invincible-agent/idp#Dataset"}, "action": {"iri": "UNKNOWN"}, "fallback": False}
    step, reason = seed.seed_step_from_answer(r)
    assert step is None and "verb" in reason


# ---------------------------------------------------------------------------
# WEAK PROVENANCE does not seed — provenance includes HOW the answer resolved.
# A plausible-but-weak answer wrong-seeded into a repeatable workflow is the
# error made durable and re-executable. (Cross-seam with the recall-override guard.)
# ---------------------------------------------------------------------------

# The explicit honest-degradation flag (engine-o recall_override) — PRECISE but currently
# DORMANT-UNTIL-WIRED (the supervisor's _resolve_subject discards provenance.recall_override,
# so it does not yet reach routing.about). This test pins the branch so threading it lights it up.
RECALL_OVERRIDE = {
    "about": {"uri": "http://invincible-agent/idp#Table", "label": "Table",
              "confidence": 0.50, "recall_override": True},
    "action": {"iri": "mesh:lookupOwnership", "label": "Lookup Ownership"},
    "fallback": False,
}
# The LIVE proxy today: the guard caps the weak path at 0.50 and that cap propagates to
# routing.about.confidence even though the flag itself is dropped upstream.
CAPPED_CONF = {
    "about": {"uri": "http://invincible-agent/idp#Table", "label": "Table", "confidence": 0.50},
    "action": {"iri": "mesh:lookupOwnership", "label": "Lookup Ownership"},
    "fallback": False,
}


def test_recall_override_answer_not_seedable():
    """The explicit weak-path flag refuses seeding (lights up once threaded into routing.about)."""
    step, reason = seed.seed_step_from_answer(RECALL_OVERRIDE)
    assert step is None and "recall_override" in reason


def test_capped_confidence_answer_not_seedable():
    """LIVE today: a subject confidence at/below the recall-override ceiling (0.50) refuses to seed,
    even without the explicit flag — the cap propagates through the supervisor while the flag does not."""
    step, reason = seed.seed_step_from_answer(CAPPED_CONF)
    assert step is None and "does not seed" in reason


def test_strong_confidence_still_seeds():
    """A strong-provenance answer (0.91) is unaffected — the gate is specific to the weak path."""
    step, reason = seed.seed_step_from_answer(GROUNDED)
    assert reason is None and step["subject"] == "http://invincible-agent/idp#Dataset"


def test_seed_and_validate_rejects_weak_provenance_before_authz():
    """Weak provenance is refused at the seam, BEFORE the eligibility check — a weak answer does
    not seed even for a fully-entitled seeder (it never reaches validate_pick)."""
    with pytest.raises(ValueError):
        seed.seed_and_validate_step(
            RECALL_OVERRIDE, authorized_subjects=[{"uri": "http://invincible-agent/idp#Table"}],
            authorized_verbs=SEEDER_VERBS)


def test_confidence_floor_is_tunable():
    """A caller can demand stronger provenance (raise the floor); a 0.70 answer then refuses too."""
    mid = {"about": {"uri": "http://invincible-agent/idp#Dataset", "confidence": 0.70},
           "action": {"iri": "mesh:lookupOwnership"}, "fallback": False}
    assert seed.seed_step_from_answer(mid)[0] is not None  # default floor 0.50: seeds
    assert seed.seed_step_from_answer(mid, confidence_floor=0.80)[0] is None  # stricter: refuses


# ---------------------------------------------------------------------------
# Seeding INHERITS enforcement — an answer is provenance, not authority
# ---------------------------------------------------------------------------

def test_seed_and_validate_passes_for_entitled_seeder():
    step = seed.seed_and_validate_step(
        GROUNDED, authorized_subjects=SEEDER_SUBJECTS, authorized_verbs=SEEDER_VERBS,
        verb_output_uri="http://invincible-agent/mesh#OwnershipFact")
    assert step["subject"] == "http://invincible-agent/idp#Dataset"


def test_seed_refused_when_seeder_cannot_see_subject():
    """The answer ran once, but the seeder is no longer entitled to the subject -> PickRefused
    (not a bypass): an answer whose subject you can't see does not seed."""
    with pytest.raises(seed.PickRefused):
        seed.seed_and_validate_step(
            GROUNDED, authorized_subjects=[], authorized_verbs=SEEDER_VERBS)


def test_seed_refused_when_seeder_not_eligible_for_verb():
    with pytest.raises(seed.PickRefused):
        seed.seed_and_validate_step(
            GROUNDED, authorized_subjects=SEEDER_SUBJECTS, authorized_verbs=[])


def test_seed_and_validate_rejects_fallback_answer():
    with pytest.raises(ValueError):
        seed.seed_and_validate_step(
            FALLBACK, authorized_subjects=SEEDER_SUBJECTS, authorized_verbs=SEEDER_VERBS)
