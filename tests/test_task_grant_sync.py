"""Prove-the-negative on the HITL task-grant sync's PURE core (no network).

The grant path CREATES access (an actor grant → can_act → the task becomes
visible+actable), so it must REFUSE bad grants, not just process good ones — the
grant-side of [[broken-closed-hides-brokenness]]. Same discipline as the
ontology-compartment and asset-grant syncs.

Run:  PYTHONPATH=policy/sync pytest tests/test_task_grant_sync.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from task_grant_sync import load_audiences, derive_desired  # noqa: E402


def test_wellformed_audience_loads():
    raw = {"audiences": {"promotion:DATA_ENGINEERING": {
        "granted_by": "cnogradi", "reason": "demo", "grant_to": ["alice@example.com"]}}}
    audiences, errors = load_audiences(raw)
    assert errors == []
    assert len(audiences) == 1
    a = audiences[0]
    assert a.key == "promotion:DATA_ENGINEERING"
    assert a.grant_to == ("alice@example.com",)


# ── prove-the-negative: malformed audiences are REFUSED, not dropped ──────────
def test_missing_granted_by_is_refused():
    raw = {"audiences": {"x:Y": {"reason": "r", "grant_to": ["a@b.com"]}}}
    audiences, errors = load_audiences(raw)
    assert audiences == []
    assert any("granted_by" in e for e in errors)


def test_missing_reason_is_refused():
    raw = {"audiences": {"x:Y": {"granted_by": "g", "grant_to": ["a@b.com"]}}}
    _, errors = load_audiences(raw)
    assert any("reason" in e for e in errors)


def test_targetless_audience_is_refused():
    raw = {"audiences": {"x:Y": {"granted_by": "g", "reason": "r", "grant_to": []}}}
    audiences, errors = load_audiences(raw)
    assert audiences == []
    assert any("grant_to" in e for e in errors)


# ── derive: one actor relation per grantee, ensure objects present ────────────
def test_derive_desired_actor_relations():
    raw = {"audiences": {"promotion:DATA_ENGINEERING": {
        "granted_by": "c", "reason": "r",
        "grant_to": ["alice@example.com", "dave@example.com"]}}}
    audiences, _ = load_audiences(raw)
    state = derive_desired(audiences)
    actor_rels = {(r.object_id, r.subject_id) for r in state.relations
                  if r.object_type == "task_audience" and r.relation == "actor"}
    assert actor_rels == {
        ("promotion:DATA_ENGINEERING", "alice@example.com"),
        ("promotion:DATA_ENGINEERING", "dave@example.com"),
    }
    # objects ensured: the audience + each user
    obj = {(o.type, o.id) for o in state.objects}
    assert ("task_audience", "promotion:DATA_ENGINEERING") in obj
    assert ("user", "alice@example.com") in obj
    assert ("user", "dave@example.com") in obj


def test_empty_input_safe():
    audiences, errors = load_audiences({})
    assert audiences == [] and errors == []
    assert derive_desired([]).relations == set()
