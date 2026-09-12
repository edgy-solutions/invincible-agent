"""The drafted review must be OPENABLE — its audience is granted and its kind is declared.

THE FAILURE THIS CATCHES IS THE ONE THE SUBSTRATE PUNISHES HARDEST. `register_task` raises
`NoEntitledRecipients` when an audience resolves to zero actors, and the gateway turns that into
a terminal 422 — because "a task no one can act on can never complete; it would suspend the
caller's workflow FOREVER, UNSEEN." For a risk acceptance the consequence is worse than a stuck
workflow: **the hazard is drafted, the review is opened, nothing appears in anyone's queue, and
the system looks like it is waiting for a human who was never asked.**

Two independent ways to produce it, and this file asserts against both:

  the AUDIENCE the matrix resolves is not granted in `policy/task_grants.yaml`
  the KIND the draft names is not declared in the composed task-kind set

Neither is hypothetical. The audience name is built from the risk level, which comes from a TTL
a programme edits; the kind is built from the same level. **Tailoring one matrix cell to a level
whose audience was never granted produces exactly this**, and it would be discovered by a safety
engineer waiting for a queue item that does not exist.

WHAT THIS DOES NOT DO: open a real task. That needs Postgres and Topaz and belongs to increment 5's
three-caller walk. This asserts the draft is CONSISTENT WITH the grants and declarations that exist
in git — which is the half that can be wrong while the substrate is perfectly healthy.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_fleet.safety_agent import entities, matrix, measures

_REPO = Path(__file__).resolve().parents[2]
_GRANTS = _REPO / "policy" / "task_grants.yaml"
_SEED = _REPO / "policy" / "task_kinds"
_OVERLAY = _REPO / "policy" / "overlays" / "sample" / "task_kinds"


@pytest.fixture(autouse=True)
def _clean_cache():
    matrix.reset_cache()
    yield
    matrix.reset_cache()


def _granted_audiences() -> dict:
    doc = yaml.safe_load(_GRANTS.read_text(encoding="utf-8"))
    return doc["audiences"]


def _drafts():
    """Every hazard that yields a draft with a review request."""
    for h in entities.HAZARDS:
        d = measures.draft_risk_assessment(hazard_id=h.hazard_id)
        if not d.get("refused") and "review_request" in d:
            yield h.hazard_id, d


def test_the_fixture_produces_at_least_one_openable_review():
    """Guard against a vacuous pass. Every assertion below is over drafts that exist, so a
    fixture producing none would make this file green and meaningless."""
    drafts = list(_drafts())
    assert drafts, "no hazard produced a review request — every assertion here would be vacuous"


def test_every_drafted_audience_is_actually_granted():
    """The audience the matrix resolves must have actors, or the review opens into silence."""
    granted = _granted_audiences()
    for hazard_id, draft in _drafts():
        audience = draft["review_request"]["audience"]
        assert audience in granted, (
            f"{hazard_id} drafts into audience {audience!r}, which is NOT in task_grants.yaml — "
            "register_task would raise NoEntitledRecipients and the acceptance would be opened "
            "into a queue nobody holds"
        )
        assert granted[audience].get("grant_to"), (
            f"{audience} is declared with an EMPTY grant_to — present in git and resolving to "
            "zero actors is the same outcome as absent, and harder to spot"
        )


def test_every_risk_level_in_the_matrix_has_a_granted_audience():
    """WIDER THAN THE FIXTURE, AND THAT IS THE POINT.

    The assertion above only covers levels the six fixture hazards happen to reach. A programme
    tailoring a cell to a level no fixture exercises would route into an ungranted audience and
    nothing here would have noticed. So this walks EVERY level the matrix can yield.
    """
    granted = _granted_audiences()
    levels = {audience for (_lvl, audience) in matrix.known_cells().values()}
    missing = sorted(a for a in levels if a not in granted)
    assert not missing, (
        f"the matrix can resolve to audience(s) with no grant: {missing} — a hazard reaching that "
        "cell drafts a review that opens into silence"
    )


def test_every_drafted_kind_is_a_declared_species():
    """The kind must exist in the COMPOSED set, not merely in the overlay file.

    An undeclared kind now accepts NOTHING (`verbs_for_kind`), so a draft naming one would open a
    task with no verbs — dead rather than wrongly actionable, which is the safer direction and
    still a broken acceptance.
    """
    compose = pytest.importorskip(
        "iagent_mesh.task_kinds",
        reason="iagent-mesh SDK not installed — this half is VOID, not green",
    ).compose
    declared = {str(getattr(k, "kind", "")) for k in compose(_SEED, [str(_OVERLAY)])}
    for hazard_id, draft in _drafts():
        kind = draft["review_request"]["kind"]
        assert kind in declared, (
            f"{hazard_id} drafts kind {kind!r}, which the composed set does not declare — the "
            f"task would open with no verbs. Declared: {sorted(declared)}"
        )


def test_the_kind_and_the_audience_agree():
    """`<task_kind>:<compartment>` is the audience convention, so the two cannot disagree.

    They are built from the same risk level, which is exactly why a seal is worth having: a future
    edit that derives one from the level and the other from something else would be invisible until
    a task landed in the wrong queue.
    """
    for hazard_id, draft in _drafts():
        rr = draft["review_request"]
        assert rr["audience"].split(":", 1)[0] == rr["kind"], (
            f"{hazard_id}: kind {rr['kind']!r} and audience {rr['audience']!r} disagree"
        )


def test_the_review_request_matches_register_tasks_signature():
    """The request is handed to `register_task` VERBATIM, so its keys are that function's
    parameters. A shape that needs translating can be translated wrongly."""
    import inspect

    from iagent import human_tasks

    params = set(inspect.signature(human_tasks.register_task).parameters)
    for hazard_id, draft in _drafts():
        stray = set(draft["review_request"]) - params
        assert not stray, (
            f"{hazard_id}: review_request has key(s) register_task does not accept: {sorted(stray)}"
        )


def test_the_payload_carries_the_evidence_but_not_the_narrative():
    """CLEARANCE-BOUNDED (§5). The queue must not become the leak.

    Citations travel, because an acceptance without its evidence is the signature this ADR exists
    to prevent. The hazard's full description does not: the summary is the clearance-safe form.
    """
    for hazard_id, draft in _drafts():
        payload = draft["review_request"]["payload"]
        assert payload["citations"], f"{hazard_id}: acceptance payload carries no evidence"
        assert "derived_from" in payload
        assert payload["reason_required"] == ["accepted", "rejected"], (
            f"{hazard_id}: the disposer must be told a reason is required BEFORE they act, not "
            "discover it from a refusal"
        )
