"""RULED 2026-10-25 (a4): no single-approver deletes. Deleting a row for a SAFETY-CRITICAL part
needs a second approver with a DIFFERENT authz_id, reusing 202's 409 `same_actor` rule.

WHAT "SAFETY-CRITICAL" MEANS HERE is what the code decides on: Engine S's critical-item list.
`entities.CRITICAL_ITEMS` (agent_fleet/safety_agent/entities.py:320) and its derived
`CRITICAL_PART_NUMBERS` (entities.py:433), matched by exact `part_number` (the same test
`measures.py:239` applies to a deferred work order). The arms import the set, never restate it.
Whether the live critical list is that same source is Q2 in the packet.

THE SEAM is Lane 1's. The arms drive the real act route and assert the OBSERVABLE: after the FIRST
approval of a critical-part delete nothing is written (no ledger record, no task resolved); the
SAME approver again is 409 `same_actor` and still nothing is written; a DIFFERENT approver
completes it, once. Strict xfail, red by assertion under `--runxfail` (today the first approval
writes and resolves).

CONTROLS share the gate and the population and differ in one thing each:
  * the same single-approver delete on a NON-critical part's row is unchanged (the op is the same,
    the part is not critical);
  * a single-approver CORRECTION on the SAME critical part is unchanged (the part is the same, the
    op is not a delete).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_fleet.safety_agent.entities import CRITICAL_PART_NUMBERS
from src.iagent import gateway

from tests.test_a_promotion_takes_row_edits_behind_its_flag import FLAG, _promote, world  # noqa: F401

CRITICAL = sorted(CRITICAL_PART_NUMBERS)[0]
PLAIN = "B-2"
assert PLAIN not in CRITICAL_PART_NUMBERS


def _delete(mpn):
    return {"deleted": [{"mpn": mpn, "reason": "not a part of this notice"}]}


def _as(authz_id):
    user = SimpleNamespace(authz_id=authz_id, sub=authz_id, email=f"{authz_id}@x", persona=None,
                           entitled_domains=["SUSTAINMENT"], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


def _written(w):
    return bool(w.ledger.records) or bool(w.resolved)


@pytest.fixture
def on(world, monkeypatch):  # noqa: F811
    monkeypatch.setenv(FLAG, "true")
    world.mpns = [CRITICAL, PLAIN]
    return world


def test_CONTROL_a_single_approver_delete_of_a_non_critical_part_is_unchanged(on):
    _as("alice")
    r = _promote(on, _delete(PLAIN))
    assert r.status_code == 200, r.text
    assert len(on.ledger.records) == 1 and len(on.resolved) == 1


def test_CONTROL_a_single_approver_correction_of_the_critical_part_is_unchanged(on):
    _as("alice")
    r = _promote(on, {"corrected": [{"mpn": CRITICAL, "corrected_mpn": "NEW-1", "evidence": "p2"}]})
    assert r.status_code == 200, r.text
    assert len(on.ledger.records) == 1 and len(on.resolved) == 1


@pytest.mark.xfail(strict=True, reason="a4: the first approval of a critical-part delete writes and "
                   "resolves the task today")
def test_the_first_approval_of_a_critical_part_delete_writes_nothing(on):
    _as("alice")
    _promote(on, _delete(CRITICAL))
    assert not _written(on), f"ledger={len(on.ledger.records)} resolved={len(on.resolved)}"


@pytest.mark.xfail(strict=True, reason="a4: the same approver can approve a critical-part delete "
                   "twice (no 409 same_actor)")
def test_the_same_approver_twice_is_409_same_actor_and_nothing_is_written(on):
    _as("alice")
    _promote(on, _delete(CRITICAL))
    r = _promote(on, _delete(CRITICAL))
    assert r.status_code == 409, r.status_code
    assert (r.json().get("detail") or {}).get("error") == "same_actor"
    assert not _written(on)


@pytest.mark.xfail(strict=True, reason="a4: nothing is held for a second approver today, so the "
                   "write has already happened before the different approver acts")
def test_a_different_second_approver_completes_it_once(on):
    _as("alice")
    _promote(on, _delete(CRITICAL))
    assert not _written(on), "written before the second approver acted"
    _as("bob")
    r = _promote(on, _delete(CRITICAL))
    assert r.status_code == 200, r.text
    assert len(on.ledger.records) == 1 and len(on.resolved) == 1
