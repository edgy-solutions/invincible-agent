"""Prove-the-negative on the capability-grant sync's PURE core (no network).

The grant path CREATES an EFFECT capability (an invoker grant → can_invoke → a
direct_call may fire the action), so it must REFUSE bad grants, not just process
good ones — the grant-side of [[broken-closed-hides-brokenness]]. An INVOKE is a
mutation, so an unaudited grant is exactly what "an unauditable grant shouldn't
exist" forbids; missing granted_by/reason/grant_to is REFUSED. Same discipline as
the task-grant, ontology-compartment, and asset-grant syncs (ADR-0029 Slice 1,
sixth namespace).

Run:  PYTHONPATH=policy/sync pytest tests/test_capability_grant_sync.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from capability_grant_sync import load_capabilities, derive_desired  # noqa: E402


def test_wellformed_capability_loads():
    raw = {"capabilities": {"mesh:publishArtifact": {
        "granted_by": "cnogradi", "reason": "demo", "grant_to": ["alice@example.com"]}}}
    caps, errors = load_capabilities(raw)
    assert errors == []
    assert len(caps) == 1
    c = caps[0]
    assert c.key == "mesh:publishArtifact"
    assert c.grant_to == ("alice@example.com",)


# ── prove-the-negative: malformed capabilities are REFUSED, not dropped ───────
def test_missing_granted_by_is_refused():
    raw = {"capabilities": {"mesh:x": {"reason": "r", "grant_to": ["a@b.com"]}}}
    caps, errors = load_capabilities(raw)
    assert caps == []
    assert any("granted_by" in e for e in errors)


def test_missing_reason_is_refused():
    raw = {"capabilities": {"mesh:x": {"granted_by": "g", "grant_to": ["a@b.com"]}}}
    _, errors = load_capabilities(raw)
    assert any("reason" in e for e in errors)


def test_targetless_capability_is_refused():
    raw = {"capabilities": {"mesh:x": {"granted_by": "g", "reason": "r", "grant_to": []}}}
    caps, errors = load_capabilities(raw)
    assert caps == []
    assert any("grant_to" in e for e in errors)


# ── derive: one invoker relation per grantee, ensure objects present ──────────
def test_derive_desired_invoker_relations():
    raw = {"capabilities": {"mesh:publishArtifact": {
        "granted_by": "c", "reason": "r",
        "grant_to": ["alice@example.com", "dave@example.com"]}}}
    caps, _ = load_capabilities(raw)
    state = derive_desired(caps)
    invoker_rels = {(r.object_id, r.subject_id) for r in state.relations
                    if r.object_type == "capability" and r.relation == "invoker"}
    assert invoker_rels == {
        ("mesh:publishArtifact", "alice@example.com"),
        ("mesh:publishArtifact", "dave@example.com"),
    }
    # objects ensured: the capability + each user
    obj = {(o.type, o.id) for o in state.objects}
    assert ("capability", "mesh:publishArtifact") in obj
    assert ("user", "alice@example.com") in obj
    assert ("user", "dave@example.com") in obj


def test_empty_input_safe():
    caps, errors = load_capabilities({})
    assert caps == [] and errors == []
    assert derive_desired([]).relations == set()
