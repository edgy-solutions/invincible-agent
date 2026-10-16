"""GET /cases/{case_id} refuses a delegate (ruled 2026-10-16, ruling b).

A "delegate" is any caller acting under a delegate client -- a key of DELEGATE_ON_BEHALF_OF (here
svc:openddil). It reads the artifacts it seeded (GET /artifacts/{id}), never the whole case. The
refusal comes BEFORE the runner fetch, so an existing and an absent case answer identically.

Arms:
  refuse   svc:openddil -> 403 delegate_reads_artifacts_only; the fetch is never made; same body
           for an existing and an absent case.
  admit    the same svc:openddil still reads an artifact it seeded (200).
  control  a non-delegate service, the submitter and a stranger keep their pre-change answers.
  control  with the map unset svc:openddil is not refused 403: the arm keys on the map, not the name.

Run: uv run pytest tests/test_a_delegate_cannot_read_the_case.py -v
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from tests.test_a_delegate_reads_what_it_seeded import _Driver, _row  # noqa: E402
from tests.test_cases_route import (  # noqa: E402
    _CASE_ONE_INSTANCE, _SPEC1, _FakeRestate, _definition, _user,
)

DELEGATE = "svc:openddil"
_MAP = json.dumps({DELEGATE: ["operator.atlantia@example.com"]})


@pytest.fixture(autouse=True)
def _delegates(monkeypatch):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", _MAP)


@pytest.fixture
def fetches(monkeypatch):
    """Every call of the runner fetch, so 'never called' is an assertion and not an absence."""
    calls: list = []
    real = gateway._fetch_case

    async def _spy(case_id):
        calls.append(case_id)
        return await real(case_id)
    monkeypatch.setattr(gateway, "_fetch_case", _spy)
    return calls


@pytest.fixture
def client_for(monkeypatch):
    from agent_fleet.restate_analyst import workflow_definition
    from src.iagent import human_tasks

    def _make(user, fake_restate):
        monkeypatch.setattr(gateway.httpx, "AsyncClient", fake_restate)
        monkeypatch.setattr(workflow_definition, "get_workflow_definition",
                            lambda wf_id: _definition(wf_id, classification="SAFETY"))
        monkeypatch.setattr(human_tasks, "list_tasks_for_workflows", lambda ids: [])
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
        return TestClient(gateway.app)
    yield _make
    gateway.app.dependency_overrides.clear()


def _present():
    return _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=_SPEC1)


# ── refuse ───────────────────────────────────────────────────────────────────────────────────

def test_a_delegate_is_refused_the_case_before_the_fetch(client_for, fetches):
    c = client_for(_user(DELEGATE), _present())
    r = c.get("/cases/c-1")
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "delegate_reads_artifacts_only"
    assert fetches == [], "the runner was asked about the case before the delegate was refused"


def test_an_existing_and_an_absent_case_answer_a_delegate_identically(client_for, fetches):
    present = client_for(_user(DELEGATE), _present()).get("/cases/c-1")
    absent = client_for(_user(DELEGATE), _FakeRestate(case=None)).get("/cases/NEVER")
    assert present.status_code == absent.status_code == 403
    assert present.json() == absent.json()
    assert fetches == []


# ── admit ────────────────────────────────────────────────────────────────────────────────────

def test_the_same_delegate_still_reads_the_artifact_it_seeded(monkeypatch):
    monkeypatch.setattr(gateway, "neo4j_driver", _Driver({"A-1": _row(seeded_by=DELEGATE)}))
    user = type("U", (), {"authz_id": DELEGATE, "id": DELEGATE, "sub": DELEGATE, "email": DELEGATE,
                          "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    try:
        r = TestClient(gateway.app).get("/artifacts/A-1")
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "A-1"


# ── controls ─────────────────────────────────────────────────────────────────────────────────

def test_the_submitter_still_sees_the_case(client_for, fetches):
    r = client_for(_user("alice"), _present()).get("/cases/c-1")
    assert r.status_code == 200, r.text
    assert fetches == ["c-1"]


def test_a_stranger_still_gets_the_404(client_for):
    r = client_for(_user("mallory", domains=["NOTHING"]), _present()).get("/cases/c-1")
    assert r.status_code == 404
    assert r.json()["detail"] == "case not found"


def test_a_non_delegate_service_is_not_refused_as_a_delegate(client_for):
    r = client_for(_user("svc:other-service"), _present()).get("/cases/c-1")
    assert r.status_code == 404  # the existing gate: not the submitter, no entitled domain
    assert r.json()["detail"] == "case not found"


def test_with_the_map_unset_the_same_name_falls_through_to_the_existing_gate(
        client_for, monkeypatch):
    monkeypatch.delenv("DELEGATE_ON_BEHALF_OF")
    r = client_for(_user(DELEGATE), _present()).get("/cases/c-1")
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "case not found"
