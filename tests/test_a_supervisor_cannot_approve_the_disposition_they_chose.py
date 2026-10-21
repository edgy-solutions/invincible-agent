"""A supervisor cannot approve the disposition they chose (architect ruling 2026-10-21).

"A person who chose the disposition on a case cannot approve it as supervisor on the same
case." The act route compares the ACTOR (the principal, never the delegate) with the `by` of
the LAST non-system transition into `maint_supervisor_review`; a match is 409 `same_actor`.
Approve only; a reject is not refused. A runner that cannot be reached fails closed (503).

Run: uv run --frozen pytest tests/test_a_supervisor_cannot_approve_the_disposition_they_chose.py -v
"""
from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway, human_tasks  # noqa: E402

ENV_NAME = "DELEGATE_ON_BEHALF_OF"
DELEGATE = "svc:openddil"
BOB = "bob@example.com"
CAROL = "carol@example.com"
DAVE = "dave@example.com"
TASK_ID = "wf-1:maint_supervisor"
CASE = "case-1"
REVIEW = "maint_supervisor_review"


class _FakeResponse:
    status_code = 200

    def json(self):
        return {}


class _FakeRestate:
    """Stands in for `httpx.AsyncClient` against the Restate ingress; records every POST."""

    def __init__(self):
        self.posts = []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json})
        return _FakeResponse()


class _User:
    def __init__(self, authz_id):
        self.authz_id = authz_id
        self.sub = authz_id
        self.email = authz_id
        self.persona = "TEST"
        self.entitled_domains: list = []
        self.is_authenticated = True


def _tr(frm, outcome, to, by):
    return {"from": frm, "outcome": outcome, "to": to, "by": by}


def _walked(chooser=BOB, frm="maint_fault_propose"):
    return {"transitions": [
        _tr("triaged", "selected", "maint_fault_propose", "system"),
        _tr(frm, "replace_now", REVIEW, chooser),
    ]}


def _task(**over):
    base = {
        "task_id": TASK_ID, "kind": "maint_supervisor_approval", "audience": "maint_sup:ORG",
        "workflow_id": "wf-1", "workflow_service": "BPMNWorkflowRunner",
        "promise_name": "approval_wf-1:maint_supervisor", "payload": {}, "case_id": CASE,
    }
    base.update(over)
    return base


@pytest.fixture
def route(monkeypatch):
    monkeypatch.setattr(human_tasks, "_SEED_ROWS_CACHE", None, raising=False)
    monkeypatch.setattr(human_tasks, "validate_decision", lambda *a, **k: None)
    rows: list = []
    monkeypatch.setattr(human_tasks, "mark_task_resolved", lambda tid, **kw: 1)
    monkeypatch.setattr(human_tasks, "get_task_resolution", lambda tid, *, caller_id: None)
    monkeypatch.setattr(human_tasks, "list_tasks_for",
                        lambda caller_id, *, status="pending": rows)
    monkeypatch.setattr(human_tasks, "check_can_act", lambda audience, caller: True)
    fake = _FakeRestate()
    monkeypatch.setattr(gateway.httpx, "AsyncClient", fake)
    cases = {"case": _walked(), "raises": None, "fetched": []}

    async def fetch(case_id):
        cases["fetched"].append(case_id)
        if cases["raises"]:
            raise cases["raises"]
        return cases["case"]

    monkeypatch.setattr(gateway, "_fetch_case", fetch)
    rows[:] = [_task()]

    def login(authz_id):
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(authz_id)

    with TestClient(gateway.app) as c:
        yield c, fake, rows, cases, login, monkeypatch
    gateway.app.dependency_overrides.clear()


def _act(c, decision="approved", on_behalf_of=None):
    body = {"decision": decision, "comment": "because"}
    if on_behalf_of is not None:
        body["on_behalf_of"] = on_behalf_of
    return c.post(f"/human_tasks/{TASK_ID}/act", json=body)


def _err(resp):
    return resp.json()["detail"]["error"]


def test_1_the_chooser_approving_is_refused_and_nothing_resumes(route):
    c, fake, rows, cases, login, mp = route
    login(BOB)
    resp = _act(c)
    assert resp.status_code == 409, resp.text
    assert _err(resp) == "same_actor", resp.json()
    assert resp.json()["detail"]["case_id"] == CASE
    assert fake.posts == [], "the resume must not be called for a refused same-actor approval"


def test_2_a_different_supervisor_approving_resumes(route):
    c, fake, rows, cases, login, mp = route
    login(CAROL)
    resp = _act(c)
    assert resp.status_code == 200, resp.text
    assert len(fake.posts) == 1
    assert cases["fetched"] == [CASE], "the control must have consulted the case"


def test_3_a_delegate_acting_for_the_chooser_is_refused(route):
    c, fake, rows, cases, login, mp = route
    mp.setenv(ENV_NAME, json.dumps({DELEGATE: [BOB]}))
    login(DELEGATE)
    resp = _act(c, on_behalf_of=BOB)
    assert resp.status_code == 409, resp.text
    assert _err(resp) == "same_actor", resp.json()
    assert fake.posts == []


def test_4_the_escalation_path_chooser_is_refused(route):
    c, fake, rows, cases, login, mp = route
    cases["case"] = _walked(chooser=BOB, frm="maint_fault_escalate")
    login(BOB)
    resp = _act(c)
    assert resp.status_code == 409, resp.text
    assert _err(resp) == "same_actor", resp.json()
    assert fake.posts == []


def test_5_the_last_transition_into_review_wins(route):
    c, fake, rows, cases, login, mp = route
    first, last = BOB, CAROL
    cases["case"] = {"transitions": [
        _tr("triaged", "selected", "maint_fault_propose", "system"),
        _tr("maint_fault_propose", "replace_now", REVIEW, first),
        _tr(REVIEW, "rejected", "maint_fault_propose", DAVE),
        _tr("maint_fault_propose", "replace_later", REVIEW, last),
    ]}
    to_review = [t["by"] for t in cases["case"]["transitions"] if t["to"] == REVIEW]
    assert to_review[0] != to_review[-1], "the fixture must distinguish last from any"
    login(first)
    resp = _act(c)
    assert resp.status_code == 200, resp.text
    assert len(fake.posts) == 1
    login(last)
    resp = _act(c)
    assert resp.status_code == 409, resp.text
    assert _err(resp) == "same_actor", resp.json()
    assert len(fake.posts) == 1, "the refused act must not add a resume"


def test_6_a_system_transition_into_review_is_ignored(route):
    c, fake, rows, cases, login, mp = route
    cases["case"] = {"transitions": [
        _tr("maint_fault_propose", "replace_now", REVIEW, BOB),
        _tr("maint_fault_propose", "timeout", REVIEW, "system"),
    ]}
    login(BOB)
    resp = _act(c)
    assert resp.status_code == 409, resp.text
    assert _err(resp) == "same_actor", resp.json()


def test_7_the_chooser_rejecting_is_not_refused(route):
    c, fake, rows, cases, login, mp = route
    login(BOB)
    resp = _act(c, decision="rejected")
    assert resp.status_code == 200, resp.text
    assert len(fake.posts) == 1


def test_8_an_unreachable_runner_fails_closed(route):
    c, fake, rows, cases, login, mp = route
    cases["raises"] = RuntimeError("connect refused")
    login(CAROL)
    resp = _act(c)
    assert resp.status_code == 503, resp.text
    assert _err(resp) == "runner_unavailable", resp.json()
    assert fake.posts == []


def test_9_a_kind_outside_the_map_is_not_refused(route):
    c, fake, rows, cases, login, mp = route
    rows[:] = [_task(kind="maint_fault_approval")]
    login(BOB)
    resp = _act(c)
    assert resp.status_code == 200, resp.text
    assert cases["fetched"] == [], "an unmapped kind must not even consult the case"


def test_10_an_unauthorized_chooser_gets_403_not_409(route):
    c, fake, rows, cases, login, mp = route
    mp.setattr(human_tasks, "check_can_act", lambda audience, caller: False)
    login(BOB)
    resp = _act(c)
    assert resp.status_code == 403, resp.text
    assert _err(resp) == "not_authorized_to_act", resp.json()
    assert cases["fetched"] == []
