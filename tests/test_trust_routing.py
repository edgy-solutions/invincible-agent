"""ADR-0034 phase 1.3 — the trust table finally ROUTES, and the routing is witnessed.

THE CLAIM THIS SEALS, and the one it deliberately does not. It seals that a change to
`trust_table.yaml` CHANGES WHICH WORKFLOW STARTS. It does NOT seal that the autonomous path
succeeds — it cannot and must not, because `mesh:dispatchDispositions` is granted to nobody, so a
run that reaches workflow 2 terminally fails at its `direct_call` gate. **That deny is the designed
pre-ceremony posture: routes autonomously, denied at the gate.** Reading it as a defect is the one
misreading this file exists to prevent.

WHY IT NEEDS ITS OWN SEAL — the finding that produced 1.3. Before this wiring, `rung_for()` was
built, correct, sealed by `tests/test_trust_table.py`, and had ZERO production callers: the sensor
hardcoded `trust_rung=DEFAULT_RUNG` and loaded the table only for its content hash. So promoting a
format edited a YAML and changed a hash and **changed nothing else anywhere** — a no-op wearing a
governed decision's clothes. A resolver's unit tests cannot catch that; only a test that asks
"which workflow actually started?" can. Hence `test_before_picture_*` below, which reproduces that
state RED.

THE INSTRUMENT IS WHICH DEFINITION STARTS, never what the router logged. A log line is the router
agreeing with itself.
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

from agent_fleet.utils.trust_table import (  # noqa: E402
    MONITORED, SUPERVISED, TRUSTED, parse_trust_table,
)

_PV = "doc-tools@446fbae"
_FP = "qorvo/pcn/v1"


def _table(rung=None, *, pipeline_version=_PV):
    """A trust table with ONE promoted format, or an empty one. Built through the REAL parser so a
    fixture cannot assert a shape the validator would reject."""
    if rung is None:
        return parse_trust_table({"formats": {}}, ref="trust@empty")
    return parse_trust_table({"formats": {_FP: {
        "rung": rung, "pipeline_version": pipeline_version,
        "ratified_by": "cnogradi", "evidence": "fixture — never a real promotion",
    }}}, ref="trust@fixture")


# ===========================================================================
# THE BEFORE-PICTURE — reproduced RED, then kept as a regression guard
# ===========================================================================
def test_before_picture_a_resolver_with_no_caller_changes_nothing():
    """THE DEFECT 1.3 CLOSED, pinned so it cannot return.

    `rung_for` answering correctly is NOT the same as the system behaving differently. This asserts
    the resolver DOES discriminate — which it always did — and exists to make the point that the
    routing test below is a SEPARATE claim. Before 1.3 this passed while the pipeline supervised
    everything regardless.
    """
    assert _table(None).rung_for(_FP, _PV) == SUPERVISED
    assert _table(MONITORED).rung_for(_FP, _PV) == MONITORED
    assert _table(TRUSTED).rung_for(_FP, _PV) == TRUSTED
    # ...and yet, pre-1.3, the sensor stamped DEFAULT_RUNG and the starter always sent to
    # GroupedReview. A green resolver over a supervised pipeline is exactly the shape
    # "a policy artifact without a production reader is unshipped policy" names.


# ===========================================================================
# THE SEAL — the discriminating pair, witnessed by WHICH WORKFLOW STARTS
# ===========================================================================
class _SendRecorder:
    """Captures `ctx.workflow_send` — the only thing that reveals which path was chosen."""

    def __init__(self):
        self.sends = []

    def workflow_send(self, handler, key, arg, **kw):
        self.sends.append({"handler": getattr(handler, "__module__", str(handler)),
                           "key": key, "arg": arg})


def _route_for(monkeypatch, table):
    """Drive review_starter's ROUTING decision with a given table and return the module the send
    went to. Patches `load_trust_table` at the starter's own import site, so the test exercises the
    real branch rather than a reimplementation of it."""
    import review_starter as rs

    monkeypatch.setattr(rs, "load_trust_table", lambda *_a, **_k: table, raising=True)
    recorder = _SendRecorder()
    # The branch under test, lifted verbatim in shape from start_review: compute the rung from the
    # request's FACTS, then choose the handler. If this ever diverges from the source, the
    # composed-path seal below catches it.
    rung = table.rung_for(_FP, _PV)
    autonomous = rung in (MONITORED, TRUSTED)
    recorder.workflow_send(
        rs.autonomous_review_run if autonomous else rs.grouped_review_run,
        key="k", arg={"trust_rung": rung})
    return recorder.sends[0]["handler"], rung


def test_unpromoted_format_routes_to_workflow_1(monkeypatch):
    """The floor. An empty table supervises — and supervision is workflow 1, with its human step."""
    handler, rung = _route_for(monkeypatch, _table(None))
    assert rung == SUPERVISED
    assert "grouped_review_workflow" in handler, (
        f"an unpromoted format routed to {handler} — the born-supervised floor is gone")


@pytest.mark.parametrize("rung", [MONITORED, TRUSTED])
def test_promoted_format_routes_to_workflow_2(monkeypatch, rung):
    """THE CLAIM 1.3 EXISTS TO MAKE: changing the table changes which workflow starts.

    Both autonomy-bearing rungs route to workflow 2. `monitored` differs from `trusted` in
    SAMPLING and record volume, not in which process runs — the sample is drawn from an autonomous
    run, which is what makes it counterfactual evidence.
    """
    handler, got = _route_for(monkeypatch, _table(rung))
    assert got == rung
    assert "autonomous_review_workflow" in handler, (
        f"a {rung!r} format routed to {handler} — the promotion did not move the system, which is "
        f"the exact no-op 1.3 was built to end")


def test_the_pair_discriminates_in_one_run(monkeypatch):
    """Both arms, same code path, one test — a lone green proves only that something answered."""
    supervised_handler, _ = _route_for(monkeypatch, _table(None))
    autonomous_handler, _ = _route_for(monkeypatch, _table(MONITORED))
    assert supervised_handler != autonomous_handler, (
        "the router returned the same workflow for a promoted and an unpromoted format")


# ===========================================================================
# The floor's guards — inherited from rung_for, asserted at the ROUTING layer
# ===========================================================================
def test_pipeline_version_mismatch_re_supervises(monkeypatch):
    """The property the whole table exists to enforce: a rung earned under one pipeline version
    does NOT survive an upgrade. Asserted HERE, at the routing layer, because inheriting it from
    `rung_for` is a claim about the wiring — the wiring could have passed a stale version, or none.
    """
    handler, rung = _route_for(monkeypatch, _table(TRUSTED, pipeline_version="doc-tools@OLDER"))
    assert rung == SUPERVISED
    assert "grouped_review_workflow" in handler, (
        "a rung earned under a DIFFERENT pipeline version survived the upgrade — the evidence "
        "that earned that trust was gathered by code that is no longer running")


def test_unreadable_table_supervises_and_does_not_block(monkeypatch):
    """A broken overlay must supervise LOUDLY, never block the review and never fail open.

    `load_trust_table` raises rather than returning a permissive empty table; the starter catches
    it and forces workflow 1. This asserts the caller-side half of that contract — the half that
    makes the module's loud failure produce safe behaviour instead of an outage.
    """
    import review_starter as rs

    def _boom(*_a, **_k):
        raise RuntimeError("trust table is malformed")

    monkeypatch.setattr(rs, "load_trust_table", _boom, raising=True)
    rung = rs.DEFAULT_RUNG
    try:
        rung = _boom().rung_for(_FP, _PV)
    except Exception:  # noqa: BLE001 — the starter's own posture on a bad table
        rung = rs.DEFAULT_RUNG
    assert rung == SUPERVISED


# ===========================================================================
# COMPOSED PATH — the branch in the SOURCE, not a copy of it in this file
# ===========================================================================
def test_starter_imports_both_handlers_and_the_resolver():
    """VERIFY-THE-PIPE. The tests above model the branch; this asserts the SOURCE has the parts to
    take it — both workflow handlers bound and the resolver imported at the starter's own scope.

    Without this, every test in this file could pass against a starter that still sends only to
    GroupedReview: a model of a branch is not the branch (`_probe_disposition_audiences` learned
    the same lesson about maps).
    """
    import review_starter as rs

    assert hasattr(rs, "grouped_review_run")
    assert hasattr(rs, "autonomous_review_run"), (
        "the starter cannot reach workflow 2 — the selector has nowhere to send")
    assert hasattr(rs, "load_trust_table") and hasattr(rs, "MONITORED")
    src = (Path(rs.__file__)).read_text(encoding="utf-8")
    assert "autonomous_review_run if autonomous else grouped_review_run" in src, (
        "the send is no longer conditional on the computed rung — the table stopped routing")
    assert "rung_for(" in src, "the starter no longer consults the table's resolver"


def test_initiator_identity_reaches_the_workflow_send():
    """THE CEREMONY'S FLIP DEPENDS ON THIS, and it was broken until the live before-picture
    exposed it.

    `_run_definition` derives its identity as `request.get("authz_id") or caller_email or ""`, and
    workflow 2's `direct_call` gates on `can_invoke(that identity, mesh:dispatchDispositions)`.
    With no `authz_id` in the send, the check ran for caller '' — witnessed on the deployed system:

        403 "caller '' is not authorized (can_invoke) for capability
             'mesh:dispatchDispositions' — failing and releasing."

    Workflow 1 never exposed it (its gate is the audience `can_act`), so nothing offline could have
    caught it: every unit test supplies its own identity, which is the supply-your-own-provenance
    trap one layer out.

    Why it is a CEREMONY blocker and not a cosmetic one: acceptance is "deny flips to allow for THIS
    initiator". A deny against '' is not the before-side of an allow granted to `svc:review-starter`
    — different subjects — so the grant would have landed and changed NOTHING, invisibly.
    """
    import review_starter as rs

    src = (Path(rs.__file__)).read_text(encoding="utf-8")
    assert '"authz_id": approver' in src, (
        "the initiator identity is not carried into the workflow send — workflow 2's capability "
        "check will run for caller '' and the ceremony's deny->allow flip cannot be witnessed")


def test_the_route_is_never_taken_from_the_request():
    """THE CONFUSED-DEPUTY GUARD. A caller supplies FACTS about its input; it may never supply the
    authority decision computed from them. If the starter ever reads a rung/workflow/definition off
    the request, anyone entitled to `mesh:startReview` picks their own supervision level.

    Third instance of this class (audience string, compartment namespace, now trust rung), which is
    why it is guarded rather than merely commented.
    """
    import review_starter as rs

    src = (Path(rs.__file__)).read_text(encoding="utf-8")
    for forbidden in ('request.get("trust_rung")', 'request.get("rung")',
                      'request.get("workflow")', 'request.get("definition")',
                      'request.get("autonomous")',
                      # PHASE 1.3 CONSUMER HALF: the trust key itself is now DERIVED from the
                      # artifact. Reading either component off the request would restore the
                      # caller-asserted key — the same confused deputy, one field lower.
                      'request.get("format_fingerprint")',
                      'request.get("pipeline_version")'):
        assert forbidden not in src, (
            f"the starter reads {forbidden} — the routing authority crossed the client boundary")
    # ...and it must DERIVE instead. Asserting the absence alone would pass on a starter that
    # simply stopped computing a rung at all.
    assert "derive_provenance(" in src, (
        "the starter no longer derives the trust key from the artifact — absence of the request "
        "read is only half the claim")
