"""`GET /cases/{case_id}/action` -- who chose, who approved, who released a maintenance case.

The stored ActionRecord (an AnswerArtifact, written at `released`) gives the work order, the
approval chain and the cited data modules; the case's transitions give who chose the option and
who released. Stubbed like `tests/test_cases_route.py` (a fake Restate ingress) and
`tests/test_the_runner_writes_the_action_record_at_released.py` (a fake neo4j driver).

Arms: the chain and its provenance; the delegate species (own case 200, anyone else's 403 with
one identical body and no runner call, GET /cases/{id} still 403); the viewer species (the same
404 as GET /cases/{id}, no record 404); an absent act stays absent; 503s; newest of two records.

Run: uv run pytest tests/test_a_case_action_record_names_who_chose_approved_released.py -q
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway, human_tasks  # noqa: E402
from agent_fleet.restate_analyst import workflow_definition  # noqa: E402
from tests.test_cases_route import _FakeRestate, _definition, _user  # noqa: E402

DELEGATE = "svc:openddil"
OTHER_DELEGATE = "svc:other"
_MAP = json.dumps({DELEGATE: ["operator.atlantia@example.com"],
                   OTHER_DELEGATE: ["operator.other@example.com"]})


@pytest.fixture(autouse=True)
def _delegates(monkeypatch):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", _MAP)


def _record(action_id="act-1", **over):
    rec = {
        "action_id": action_id, "event_id": "ev-1", "asset_id": "asset-9", "owning_tier": "T2",
        "label": "Replace pump",
        "work_order": {"option": "replace", "readiness": "ready", "task": "swap the pump",
                       "task_refs": ["DMC-A"], "parts": ["P-1"], "outcome": "released"},
        "approval_chain": [
            {"step": 1, "role": "supervisor", "approver_sub": "sue", "decision": "approved",
             "decided_at": "t3", "decision_record_ref": "r1"},
            {"step": 2, "role": "qa", "approver_sub": "quentin", "decision": "rejected",
             "decided_at": "t3b", "decision_record_ref": "r2"},
            {"step": 3, "role": "chief", "approver_sub": "carl", "decision": "approved",
             "decided_at": "t4", "decision_record_ref": "r3", "acted_via": "svc:openddil"},
        ],
        "provenance": {"case_id": "c-1",
                       "manual_nodes_consulted": ["DMC-A", "DMC-B", None, "DMC-A", "", "DMC-C"]},
    }
    rec.update(over)
    return rec


def _row(rec, *, artifact_id="action-record-1", seeded_by=DELEGATE, valid_as_of=100):
    return {"id": artifact_id, "seeded_by": seeded_by, "valid_as_of": valid_as_of,
            "rendered_output": json.dumps({"kind": gateway.ACTION_RECORD_KIND, "record": rec})}


_CASE = {
    "case_id": "c-1",
    "instances": [{"n": 1, "instance_id": "c-1~1", "definition_id": "def-a"}],
    "transitions": [
        {"from": None, "outcome": "received", "to": "received", "by": "system", "at": "t0"},
        {"from": "a", "outcome": "replace", "to": "b", "by": "early-chooser", "at": "t1",
         "instance_id": "c-1~1"},
        {"from": "a", "outcome": "replace", "to": "b", "by": "mia", "at": "t2",
         "instance_id": "c-1~1"},
        {"from": "b", "outcome": "released", "to": "c", "by": "early-releaser", "at": "t5",
         "instance_id": "c-1~1"},
        {"from": "b", "outcome": "released", "to": "c", "by": "rex", "at": "t6",
         "instance_id": "c-1~1"},
    ],
    "state": "closed", "terminal": "closed", "seeded_by": DELEGATE,
}
_SPEC1 = {"trigger": {"domain_type": "SAFETY", "dropped_by": {"authz_id": "alice"}}}


class _Driver:
    """A fake neo4j driver: `rows` maps case_id -> AnswerArtifact rows; `boom` raises."""

    def __init__(self, rows, boom=False):
        self.rows, self.boom, self.runs = rows, boom, []

    def session(self):
        return self

    def __enter__(self):
        if self.boom:
            raise RuntimeError("neo4j unreachable")
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.runs.append((cypher, params))
        assert params["kind"] == gateway.ACTION_RECORD_KIND
        return iter(list(self.rows.get(params["case_id"], [])))


@pytest.fixture
def client_for(monkeypatch):
    def _make(user, restate, rows=None, *, neo_boom=False):
        monkeypatch.setattr(gateway.httpx, "AsyncClient", restate)
        monkeypatch.setattr(workflow_definition, "get_workflow_definition",
                            lambda wf_id: _definition(wf_id, classification="SAFETY"))
        monkeypatch.setattr(human_tasks, "list_tasks_for_workflows", lambda ids: [])
        monkeypatch.setattr(gateway, "neo4j_driver", _Driver(rows or {}, boom=neo_boom))
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
        return TestClient(gateway.app)
    yield _make
    gateway.app.dependency_overrides.clear()


def _viewer():
    return _user("alice", domains=[])


# -- the viewer species ----------------------------------------------------------------------

def test_a_viewer_gets_the_chain_chose_approved_released(client_for):
    c = client_for(_viewer(), _FakeRestate(case=_CASE, spec1=_SPEC1), {"c-1": [_row(_record())]})
    resp = c.get("/cases/c-1/action")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["acts"] == [
        {"act": "chose", "who": "mia", "at": "t2", "option": "replace", "instance_id": "c-1~1"},
        {"act": "approved", "who": "sue", "at": "t3", "role": "supervisor"},
        {"act": "approved", "who": "carl", "at": "t4", "role": "chief",
         "acted_via": "svc:openddil"},
        {"act": "released", "who": "rex", "at": "t6", "instance_id": "c-1~1"},
    ]
    assert body["dmcs_cited"] == ["DMC-A", "DMC-B", "DMC-C"]
    # the record verbatim at the top level, plus the additive keys only
    rec = _record()
    assert {k: v for k, v in body.items() if k in rec} == rec
    assert set(body) - set(rec) == {"case_id", "artifact_id", "acts", "dmcs_cited"}
    assert (body["case_id"], body["artifact_id"]) == ("c-1", "action-record-1")


def test_a_case_without_a_released_hop_has_no_released_act(client_for):
    case = dict(_CASE, transitions=[t for t in _CASE["transitions"]
                                    if t["outcome"] != "released"])
    c = client_for(_viewer(), _FakeRestate(case=case, spec1=_SPEC1), {"c-1": [_row(_record())]})
    chain = c.get("/cases/c-1/action").json()["acts"]
    assert [a["act"] for a in chain] == ["chose", "approved", "approved"]
    assert all(a["who"] is not None and a["at"] is not None for a in chain)


def test_a_non_entitled_human_gets_the_same_404_as_a_nonexistent_case(client_for):
    mallory = _user("mallory", domains=["NOTHING"])
    rows = {"c-1": [_row(_record())]}
    c = client_for(mallory, _FakeRestate(case=_CASE, spec1=_SPEC1), rows)
    refused = c.get("/cases/c-1/action")
    c = client_for(mallory, _FakeRestate(case=None), rows)
    missing = c.get("/cases/nope/action")
    assert refused.status_code == missing.status_code == 404
    assert refused.json() == missing.json() == {"detail": "case not found"}


def test_a_viewable_case_with_no_record_is_404_no_action_record(client_for):
    c = client_for(_viewer(), _FakeRestate(case=_CASE, spec1=_SPEC1), {})
    resp = c.get("/cases/c-1/action")
    assert resp.status_code == 404
    assert resp.json()["detail"] == {"error": "no_action_record"}


def test_two_records_answer_the_newest_and_list_both(client_for):
    old = _row(_record("act-old"), artifact_id="ar-old", valid_as_of=10)
    new = _row(_record("act-new"), artifact_id="ar-new", valid_as_of=20)
    c = client_for(_viewer(), _FakeRestate(case=_CASE, spec1=_SPEC1), {"c-1": [new, old]})
    body = c.get("/cases/c-1/action").json()
    assert (body["artifact_id"], body["action_id"]) == ("ar-new", "act-new")
    assert "record" not in body
    assert body["action_ids"] == ["act-old", "act-new"]


def test_a_runner_that_raises_is_503_runner_unavailable(client_for):
    c = client_for(_viewer(), _FakeRestate(boom=True), {"c-1": [_row(_record())]})
    resp = c.get("/cases/c-1/action")
    assert resp.status_code == 503
    assert resp.json()["detail"] == {"error": "runner_unavailable"}


def test_a_neo4j_that_raises_is_503_artifact_store_unavailable(client_for):
    c = client_for(_viewer(), _FakeRestate(case=_CASE, spec1=_SPEC1), neo_boom=True)
    resp = c.get("/cases/c-1/action")
    assert resp.status_code == 503
    assert resp.json()["detail"] == {"error": "artifact_store_unavailable"}
    c = client_for(_user(DELEGATE), _FakeRestate(case=_CASE), neo_boom=True)
    assert c.get("/cases/c-1/action").status_code == 503


# -- the delegate species --------------------------------------------------------------------

def test_a_delegate_reads_the_action_record_of_a_case_it_seeded(client_for):
    c = client_for(_user(DELEGATE), _FakeRestate(case=_CASE), {"c-1": [_row(_record())]})
    resp = c.get("/cases/c-1/action")
    assert resp.status_code == 200, resp.text
    assert [a["act"] for a in resp.json()["acts"]] == ["chose", "approved", "approved",
                                                         "released"]


def test_a_delegate_is_refused_identically_on_anothers_case_no_seeder_and_no_case(client_for):
    rows = {"c-2": [_row(_record(), seeded_by=OTHER_DELEGATE)],
            "c-3": [_row(_record(), seeded_by=None)]}
    cases = {"c-2": dict(_CASE, seeded_by=OTHER_DELEGATE), "c-3": dict(_CASE, seeded_by=None),
             "c-nope": None}
    bodies = []
    for case_id, case in cases.items():
        c = client_for(_user(DELEGATE), _FakeRestate(case=case, spec1=_SPEC1), rows)
        resp = c.get(f"/cases/{case_id}/action")
        assert resp.status_code == 403, (case_id, resp.text)
        assert resp.json()["detail"]["error"] == "not_your_case"
        assert gateway.neo4j_driver.runs == [], f"{case_id}: the artifact store was read"
        bodies.append(resp.json())
    assert bodies[0] == bodies[1] == bodies[2]


def test_a_delegates_own_case_with_no_record_is_404_nothing_yet(client_for):
    c = client_for(_user(DELEGATE), _FakeRestate(case=_CASE), {})
    resp = c.get("/cases/c-1/action")
    assert resp.status_code == 404
    assert resp.json()["detail"] == {"error": "no_action_record"}


def test_a_record_seeded_by_another_is_403_even_on_the_delegates_case(client_for):
    rows = {"c-1": [_row(_record(), seeded_by=OTHER_DELEGATE)]}
    c = client_for(_user(DELEGATE), _FakeRestate(case=_CASE), rows)
    resp = c.get("/cases/c-1/action")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "not_your_case"


def test_a_delegate_with_an_unreachable_runner_is_503(client_for):
    c = client_for(_user(DELEGATE), _FakeRestate(boom=True), {"c-1": [_row(_record())]})
    resp = c.get("/cases/c-1/action")
    assert resp.status_code == 503
    assert resp.json()["detail"] == {"error": "runner_unavailable"}


def test_a_delegate_is_still_refused_on_the_whole_case(client_for):
    runner = _FakeRestate(case=_CASE, spec1=_SPEC1)
    c = client_for(_user(DELEGATE), runner, {"c-1": [_row(_record())]})
    resp = c.get("/cases/c-1")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "delegate_reads_artifacts_only"
    assert runner.posts == []
