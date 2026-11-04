"""ROUTE-LEVEL SEAL -- `/internal/origin/write` refuses a drop when `check_can_view_program` says no.

Architect, 2026-11-03: "yes to the route-level seal on dropped_by: check_can_view_program -> false,
route refuses the drop." `dropped_by.authz_id` is a program-membership check, not a delegation, so it is
sealed here and carries NO xfail marker.

What is real: the route, the case-runner gate, the steward-approval handling, and `origin_writer.write_origin`
with its `origin.check_dropper_bound`. What is stubbed: `human_tasks.check_can_view_program` (the one thing
under test) and the graph writer (the boundary). The `_fake` write_origin in tests/test_origin_write_route.py
hides this refusal; it is not used here.

The refusal is READ from the writer (what `origin.check_dropper_bound` raises), not typed.
The Topaz OUTAGE is a different seal: tests/security/test_a_malformed_pdp_answer_is_503_at_every_site.py
covers it; it is not duplicated here.
"""
from __future__ import annotations

import copy

import pytest

pytest.importorskip("fastapi")
iagent_mesh = pytest.importorskip("iagent_mesh")
from iagent_mesh.write_results import MeshWriteResult  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import origin_writer  # noqa: E402
from tests.identity._identity_support import install_delegates, pair_and_outsider  # noqa: E402
from tests.identity.test_a_service_token_cannot_name_a_user_outside_the_delegate_list import (  # noqa: E402
    _login)
from tests.test_origin_write_route import BODY as _SHAPE  # noqa: E402  (a valid request shape)

RUNNER = gateway._CASE_RUNNER_SERVICE_AUTHZ_ID


@pytest.fixture(autouse=True)
def _clean():
    yield
    gateway.app.dependency_overrides.clear()


class _Graph:
    calls: list = []

    def __init__(self, *a, **k):
        pass

    def write_node(self, initiator, *, label, id, payload):
        _Graph.calls.append({"initiator": initiator, "label": label, "id": id, "payload": payload})
        return MeshWriteResult.written()


def _post(monkeypatch, *, member, program="keep", raise_server_exceptions=True):
    """Drive the real route as the case runner with a valid steward approval; only the membership
    answer and the graph boundary are stubbed. Returns (response, membership_calls)."""
    from agent_fleet.utils.mesh_writers import neo4j_graph

    served = install_delegates(monkeypatch)
    steward, dropper = pair_and_outsider(served, RUNNER)
    asked = []
    monkeypatch.setattr(ht, "check_can_view_program",
                        lambda prog, who: (asked.append((prog, who)), member)[1])
    _Graph.calls = []
    monkeypatch.setattr(neo4j_graph, "Neo4jGraphWriter", _Graph)

    async def no_filing(*a, **k):
        return None
    monkeypatch.setattr(gateway, "_file_promotion_if_ready", no_filing)

    body = copy.deepcopy(_SHAPE)
    body["origin"]["obtained_via"] = next(
        k for k, v in origin_writer._RESOLVED_BY_BY_OBTAINED_VIA.items() if v != "unresolved")
    body["dropped_by"] = {"authz_id": dropper}
    body["approval_chain"] = [{"step": 1, "role": "steward", "approver_sub": steward,
                               "decision": "approved"}]
    if program != "keep":
        if program is _ABSENT:
            body["origin"].pop("program", None)
        else:
            body["origin"]["program"] = program
    _login(RUNNER)
    from fastapi.testclient import TestClient
    r = TestClient(gateway.app, raise_server_exceptions=raise_server_exceptions).post(
        "/internal/origin/write", json=body)
    return r, asked, body


_ABSENT = object()


def _writer_refusal(body):
    """The reason the writer itself gives a non-member, read off `origin.check_dropper_bound`."""
    o = body["origin"]
    obj = origin_writer.origin.Origin(
        owner_domain=o["owner_domain"], program=o["program"], obtained_via=o["obtained_via"])
    try:
        origin_writer.origin.check_dropper_bound(False, obj)
    except origin_writer.origin.DropperNotProgramMember as exc:
        return str(exc)
    raise AssertionError("the writer did not refuse a non-member")


def test_leg1_a_dropper_the_pdp_says_is_not_a_member_is_refused_and_nothing_is_written(monkeypatch):
    r, asked, body = _post(monkeypatch, member=False)
    j = r.json()
    assert r.status_code == 200 and j["status"] == "write_refused", (r.status_code, r.text[:300])
    assert j["reason"] == _writer_refusal(body), j
    assert _Graph.calls == [], _Graph.calls


def test_leg2_control_the_same_request_with_a_member_is_written(monkeypatch):
    r, asked, body = _post(monkeypatch, member=True)
    j = r.json()
    assert r.status_code == 200 and j["status"] == "written" and j["reason"] is None, (r.text[:300])
    assert len(_Graph.calls) == 1 and _Graph.calls[0]["id"] == body["artifact_id"], _Graph.calls


def test_leg3_the_answer_is_about_this_dropper_and_this_program(monkeypatch):
    r, asked, body = _post(monkeypatch, member=True)
    assert asked == [(body["origin"]["program"], body["dropped_by"]["authz_id"])], asked


@pytest.mark.parametrize("absent", ["missing", "null", "empty"])
def test_leg4_a_drop_with_no_program_is_refused_not_written(monkeypatch, absent):
    """`program` falsy sets dropper_is_program_member False WITHOUT asking the PDP. The drop must be
    refused by the writer (200 write_refused), nothing written, the PDP not asked about nothing."""
    value = {"missing": _ABSENT, "null": None, "empty": ""}[absent]
    r, asked, _ = _post(monkeypatch, member=True, program=value, raise_server_exceptions=False)
    assert r.status_code < 500, (r.status_code, r.text[:200])
    j = r.json()
    assert j.get("status") == "write_refused" and _Graph.calls == [], (r.text[:300], _Graph.calls)
    assert asked == [], "no program: the PDP must not be asked about nothing"
