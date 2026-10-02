"""Prove-the-negative on the program-member sync's PURE core (no network).

The origin-entitlement ruling (architect, 2026-10-02: "ORIGIN, not audience") gates a
READ (program membership is disclosure, ADR-0047 §5.1) through this SEVENTH namespace
— same discipline as the other six git-asserted syncs: a program grant missing
granted_by/reason/grant_to is REFUSED, not silently dropped, same as
capability_grant_sync.py's `load_capabilities`.

Run:  PYTHONPATH=policy/sync pytest tests/test_program_member_sync.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from program_member_sync import load_programs, derive_desired  # noqa: E402


def test_wellformed_program_loads():
    raw = {"programs": {"SANDBOX_PROGRAM_ALPHA": {
        "granted_by": "cnogradi", "reason": "demo", "grant_to": ["alice@example.com"]}}}
    programs, errors = load_programs(raw)
    assert errors == []
    assert len(programs) == 1
    p = programs[0]
    assert p.key == "SANDBOX_PROGRAM_ALPHA"
    assert p.grant_to == ("alice@example.com",)


# ── prove-the-negative: malformed programs are REFUSED, not dropped ───────────
def test_missing_granted_by_is_refused():
    raw = {"programs": {"P": {"reason": "r", "grant_to": ["a@b.com"]}}}
    programs, errors = load_programs(raw)
    assert programs == []
    assert any("granted_by" in e for e in errors)


def test_missing_reason_is_refused():
    raw = {"programs": {"P": {"granted_by": "g", "grant_to": ["a@b.com"]}}}
    _, errors = load_programs(raw)
    assert any("reason" in e for e in errors)


def test_targetless_program_is_refused():
    raw = {"programs": {"P": {"granted_by": "g", "reason": "r", "grant_to": []}}}
    programs, errors = load_programs(raw)
    assert programs == []
    assert any("grant_to" in e for e in errors)


# ── derive: one member relation per grantee, ensure objects present ───────────
def test_derive_desired_member_relations():
    raw = {"programs": {"SANDBOX_PROGRAM_ALPHA": {
        "granted_by": "c", "reason": "r",
        "grant_to": ["alice@example.com", "bob@example.com"]}}}
    programs, _ = load_programs(raw)
    state = derive_desired(programs)
    member_rels = {(r.object_id, r.subject_id) for r in state.relations
                   if r.object_type == "program" and r.relation == "member"}
    assert member_rels == {
        ("SANDBOX_PROGRAM_ALPHA", "alice@example.com"),
        ("SANDBOX_PROGRAM_ALPHA", "bob@example.com"),
    }
    # objects ensured: the program + each user
    obj = {(o.type, o.id) for o in state.objects}
    assert ("program", "SANDBOX_PROGRAM_ALPHA") in obj
    assert ("user", "alice@example.com") in obj
    assert ("user", "bob@example.com") in obj


def test_empty_input_safe():
    programs, errors = load_programs({})
    assert programs == [] and errors == []
    assert derive_desired([]).relations == set()
