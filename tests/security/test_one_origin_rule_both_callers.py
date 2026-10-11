"""ONE origin rule, ONE function, BOTH callers (architect Q1 ruling, 2026-10-10).

"The gateway is wrong. _origin_visible_to_caller must accept an origin with no program -- that is
exactly a steward attestation. One rule, one function: move the check into a shared helper both
engine-o and the gateway call, test both callers against it."

ONE truth table (`CASES`) is run against three columns: the helper itself, the real gateway
`_origin_visible_to_caller`, and the real engine-o `notice_parts.read_notice_parts`. Each column
asserts the verdict AND whether Topaz (the membership question) was asked, so a caller that asks
too early (an existence oracle) or never (a skipped conjunct) reds in its own column.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.ontology_service import notice_parts as np_mod  # noqa: E402
from agent_fleet.utils import origin_entitlement as oe  # noqa: E402

TABLE = {"SUSTAINMENT": frozenset({"SUSTAINMENT"}), "FINANCE": frozenset({"FINANCE"})}
NOTICE = "PCN-T1"
CALLER = "alice-1"
PROG = "PROG_X"

# (id, viewer_domains, owner_domain, program, member_answer, expected, membership_asked)
CASES = [
    ("programless-consumable", ("SUSTAINMENT",), "SUSTAINMENT", None, False, True, False),
    ("programless-not-consumable", ("FINANCE",), "SUSTAINMENT", None, True, False, False),
    ("program-consumable-member", ("SUSTAINMENT",), "SUSTAINMENT", PROG, True, True, True),
    ("program-consumable-nonmember", ("SUSTAINMENT",), "SUSTAINMENT", PROG, False, False, True),
    ("program-not-consumable", ("FINANCE",), "SUSTAINMENT", PROG, True, False, False),
    ("owner-none", ("SUSTAINMENT",), None, PROG, True, False, False),
    ("owner-empty", ("SUSTAINMENT",), "", PROG, True, False, False),
    ("owner-blank", ("SUSTAINMENT",), "  ", PROG, True, False, False),
    ("blank-program-is-programless", ("SUSTAINMENT",), "SUSTAINMENT", "  ", False, True, False),
]
_IDS = [c[0] for c in CASES]


class _Member:
    def __init__(self, answer=True, raises=False):
        self.answer, self.raises, self.calls = answer, raises, []

    def __call__(self, program, caller_id=None):
        self.calls.append(program)
        if self.raises:
            raise RuntimeError("topaz down")
        return self.answer


# -- column 1: the helper ------------------------------------------------------

@pytest.mark.parametrize("case", CASES, ids=_IDS)
def test_helper_against_the_table(case):
    _, domains, owner, program, answer, expected, asked = case
    m = _Member(answer)
    got = oe.visible_by_origin(viewer_domains=iter(domains), owner_domain=owner, program=program,
                               table=TABLE, is_program_member=m)
    assert got is expected
    assert bool(m.calls) is asked
    if asked:
        assert m.calls == [program]


# -- column 2: the real gateway ------------------------------------------------

class _Cell:
    def __init__(self, d):
        self.domain = d


class _User:
    authz_id = "viewer@example.com"

    def __init__(self, domains):
        self.entitlements = type("E", (), {"cells": [_Cell(d) for d in domains]})()


@pytest.fixture()
def gateway(monkeypatch):
    import iagent.gateway as gw
    import iagent.human_tasks as ht

    monkeypatch.setattr(gw, "_load_domain_consumption_table", lambda: TABLE)

    def _go(rec, domains, member):
        monkeypatch.setattr(ht, "check_can_view_program", member)
        return gw._origin_visible_to_caller(rec, _User(domains))
    return _go


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=_IDS)
async def test_gateway_against_the_same_table(gateway, case):
    _, domains, owner, program, answer, expected, asked = case
    m = _Member(answer)
    got = await gateway({"origin_owner_domain": owner, "origin_program": program}, domains, m)
    assert got is expected
    assert bool(m.calls) is asked
    if asked:
        assert m.calls == [program]


# -- column 3: the real engine-o read ------------------------------------------

class _Rec:
    def __init__(self, d):
        self._d = d

    def data(self):
        return dict(self._d)


class _Driver:
    def __init__(self, row):
        self.row = row

    def session(self, **kw):
        row = self.row

        class _S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, cypher, params=None, **kw2):
                return [_Rec(row)]
        return _S()


def _row(owner, program):
    return {
        "notice": {"id": NOTICE, "type": "PCN", "provenance_obtained_via": "user-drop",
                   "provenance_ingest_id": "sha256:aa", "provenance_standing": "supervised"},
        "mpns": ["5530-1", "5530-2"],
        "dropped_by": "dropper-1",
        "has_artifact": True,
        "origin_owner_domain": owner,
        "origin_program": program,
        "origin_resolved_by": "record" if (program or "").strip() else "steward",
        "promoted": True,
        "promoted_by": "human:bob",
    }


def _engine_o(owner, program, domains, member):
    return np_mod.read_notice_parts(_Driver(_row(owner, program)), NOTICE, caller_id=CALLER,
                                    viewer_domains=domains, table=TABLE, can_view_program=member)


@pytest.mark.parametrize("case", CASES, ids=_IDS)
def test_engine_o_against_the_same_table(case):
    _, domains, owner, program, answer, expected, asked = case
    m = _Member(answer)
    out = _engine_o(owner, program, domains, m)
    assert bool(out["sources"]) is expected
    if not expected:
        assert out["reason"] == "unknown_notice"
    assert bool(m.calls) is asked
    if asked:
        assert m.calls == [program]


# -- both raise the same way ---------------------------------------------------

@pytest.mark.asyncio
async def test_a_consumable_caller_with_a_raising_membership_call_raises_in_all_three(gateway):
    from fastapi import HTTPException

    with pytest.raises(RuntimeError):
        oe.visible_by_origin(viewer_domains=("SUSTAINMENT",), owner_domain="SUSTAINMENT",
                             program=PROG, table=TABLE, is_program_member=_Member(raises=True))
    with pytest.raises(HTTPException) as exc:
        await gateway({"origin_owner_domain": "SUSTAINMENT", "origin_program": PROG},
                      ("SUSTAINMENT",), _Member(raises=True))
    assert exc.value.status_code == 503
    with pytest.raises(RuntimeError):
        _engine_o("SUSTAINMENT", PROG, ("SUSTAINMENT",), _Member(raises=True))


@pytest.mark.asyncio
async def test_control_a_non_consumable_caller_with_a_raising_membership_call_is_a_plain_deny(gateway):
    """Differs from the arm above in exactly one thing: the pure check refuses first."""
    m = _Member(raises=True)
    assert oe.visible_by_origin(viewer_domains=("FINANCE",), owner_domain="SUSTAINMENT",
                                program=PROG, table=TABLE, is_program_member=m) is False
    assert await gateway({"origin_owner_domain": "SUSTAINMENT", "origin_program": PROG},
                         ("FINANCE",), m) is False
    assert _engine_o("SUSTAINMENT", PROG, ("FINANCE",), m)["sources"] == []
    assert m.calls == []


# -- both callers ARE the helper's callers -------------------------------------

def test_both_callers_go_through_the_one_helper():
    import iagent.gateway as gw
    import iagent.origin as origin_mod

    # engine-o's read reaches the helper THROUGH `notice_visible` (Q7), asserted by the test below.
    for fn in (gw._origin_visible_to_caller, np_mod.notice_visible):
        src = inspect.getsource(fn)
        assert "visible_by_origin(" in src, fn.__name__
        assert "origin_visible(" not in src.replace("visible_by_origin(", ""), fn.__name__
        assert "can_consume(" not in src, fn.__name__
    assert np_mod.visible_by_origin is oe.visible_by_origin
    assert origin_mod.visible_by_origin is oe.visible_by_origin


# -- column 4: the real engine-o /resolve_instance (architect Q7, 2026-10-10) --------------------
# The same table, the same row, the same caller: the notice candidate is present IFF
# `read_notice_parts` returns the notice's sources. Agreement is the seal, so there is no second
# truth table.

@pytest.mark.parametrize("case", CASES, ids=_IDS)
def test_engine_o_resolve_instance_agrees_with_notice_parts_on_the_same_table(case, monkeypatch):
    from fastapi.testclient import TestClient

    from agent_fleet.ontology_service import main as eo

    _, domains, owner, program, answer, expected, asked = case
    row = _row(owner, program)
    m_read, m_resolve = _Member(answer), _Member(answer)

    read = np_mod.read_notice_parts(_Driver(row), NOTICE, caller_id=CALLER, viewer_domains=domains,
                                    table=TABLE, can_view_program=m_read)

    async def _jena(query, domain="MAINTENANCE", **kw):
        return [{"s": np_mod.NOTICE_IRI_PREFIX + NOTICE, "type": "http://x/pcn#Notice"}]

    monkeypatch.setattr(eo, "execute_sparql", _jena)
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", _Driver(row))
    monkeypatch.setattr(eo, "_load_domain_consumption_for_notice_parts", lambda: TABLE)
    monkeypatch.setattr(eo, "_notice_parts_can_view_program", m_resolve)
    resp = TestClient(eo.app).post("/resolve_instance", json={
        "identifier": NOTICE, "user_email": CALLER, "entitled_domains": list(domains)})
    assert resp.status_code == 200, resp.text
    present = bool(resp.json()["candidates"])

    assert present is bool(read["sources"]) is expected
    assert m_resolve.calls == m_read.calls  # Topaz is asked on the same rows, and no others
    assert bool(m_resolve.calls) is asked


def test_the_resolve_instance_gate_and_the_notice_parts_read_share_the_one_verdict():
    for fn in (np_mod.read_notice_parts, np_mod.visible_notice_ids):
        src = inspect.getsource(fn)
        assert "notice_visible(" in src, fn.__name__
        assert "visible_by_origin(" not in src, fn.__name__
    assert "visible_by_origin(" in inspect.getsource(np_mod.notice_visible)
