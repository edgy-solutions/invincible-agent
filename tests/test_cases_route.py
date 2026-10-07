"""`GET /cases/{case_id}` (roll #20 item 3) -- the route, with the Restate ingress and
human_tasks stubbed the same way `tests/safety/test_the_act_reaches_the_owning_workflow.py`
stubs them (a fake `httpx.AsyncClient`, monkeypatched dependency overrides). The pure
projection/gate logic is sealed separately in `tests/test_case_projection.py`; this file seals
only the route's own wiring: which runner/DB calls it makes, and how it turns their outcomes
into 404 / 503 / 200.

Run: uv run --frozen pytest -q tests/test_cases_route.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway, human_tasks  # noqa: E402
from agent_fleet.restate_analyst import workflow_definition  # noqa: E402


# ── FAKE RESTATE INGRESS ─────────────────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self._data = data
        # Measured live: an absent case/spec arrives as an EMPTY 200, not JSON `null` --
        # `_restate_answer` reads `.content` before ever calling `.json()`. A 404 response's
        # content is never read before the route's own status-code check, but is set
        # consistently anyway.
        self.content = b"" if data is None else b"x"

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"restate responded {self.status_code}")


class _FakeRestate:
    """Stands in for `httpx.AsyncClient` against the Restate ingress. `case=None` means the
    `case` handler answers an empty 200 (no such case -- the realistic "absent" shape, measured
    live); `spec1=None` means `instance_spec` answers an empty 200 the same way. `case_404=True`
    forces a literal 404 from `/case` instead, for the (now secondary, but still real) arm where
    Restate itself 404s."""

    def __init__(self, case=None, spec1=None, boom=False, case_404=False):
        self.case, self.spec1, self.boom = case, spec1, boom
        self.case_404 = case_404
        self.posts = []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kw):
        self.posts.append({"url": url, "json": json})
        if self.boom:
            raise RuntimeError("restate ingress unreachable")
        if url.endswith("/case"):
            if self.case is not None:
                return _FakeResp(200, self.case)
            return _FakeResp(404) if self.case_404 else _FakeResp(200, None)
        if url.endswith("/instance_spec"):
            return _FakeResp(200, self.spec1) if self.spec1 is not None else _FakeResp(200, None)
        raise AssertionError(f"unexpected Restate URL {url}")


def _definition(id, *, classification=None):
    return SimpleNamespace(
        id=id, name=id, classification=classification, participants=[], domain_stages=[],
        steps=[SimpleNamespace(id="s1", kind="human_await", title="Approve", audience="aud:x")],
    )


def _user(authz_id, domains=()):
    return SimpleNamespace(
        authz_id=authz_id,
        entitlements=SimpleNamespace(cells=[SimpleNamespace(persona="P", domain=d)
                                            for d in domains]),
    )


@pytest.fixture
def client_for(monkeypatch):
    def _make(user, fake_restate, *, get_definition=None, task_rows=None,
              htp_boom: Exception | None = None):
        monkeypatch.setattr(gateway.httpx, "AsyncClient", fake_restate)
        if get_definition is not None:
            monkeypatch.setattr(workflow_definition, "get_workflow_definition", get_definition)

        def _tasks(workflow_ids):
            if htp_boom is not None:
                raise htp_boom
            return task_rows or []
        monkeypatch.setattr(human_tasks, "list_tasks_for_workflows", _tasks)

        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
        return TestClient(gateway.app)
    yield _make
    gateway.app.dependency_overrides.clear()


_CASE_NO_INSTANCES = {"case_id": "c-0", "instances": [], "transitions": [], "state": None,
                      "terminal": None}

_CASE_ONE_INSTANCE = {
    "case_id": "c-1",
    "instances": [{"n": 1, "instance_id": "c-1~1", "definition_id": "def-a"}],
    "transitions": [
        {"from": None, "outcome": "received", "to": "received", "by": "system", "at": "t0"},
        {"from": "def-a", "outcome": "approved", "to": "approved", "by": "alice", "at": "t1",
         "instance_id": "c-1~1"},
    ],
    "state": "approved", "terminal": "approved",
}

_SPEC1 = {"trigger": {"domain_type": "SAFETY", "dropped_by": {"authz_id": "alice"}}}


# ── 404: NO SUCH CASE ────────────────────────────────────────────────────────────────────────

def test_no_such_case_is_404_case_not_found(client_for):
    c = client_for(_user("bob"), _FakeRestate(case=None))
    resp = c.get("/cases/nope")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "case not found"


class _RealWireRestate:
    """Answers with REAL `httpx.Response` objects, so the parse under test is httpx's own, not a
    double's. Measured live (roll #20, rev 176): `WorkflowRunner/<unknown>/case` answers 200
    with an EMPTY body -- the handler returns `ctx.get("case")` = None, and Restate serialises
    None as nothing. Both earlier doubles invented the absent answer (a 404; a `.json()` of
    None), which is how GET /cases shipped answering 503 for an unknown case."""

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kw):
        return httpx.Response(200, content=b"", request=httpx.Request("POST", url))


def test_no_such_case_on_the_real_wire_is_404_not_503(client_for):
    c = client_for(_user("bob"), _RealWireRestate())
    resp = c.get("/cases/nope")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "case not found"


def test_a_literal_404_from_the_runner_is_still_404(client_for):
    c = client_for(_user("bob"), _FakeRestate(case=None, case_404=True))
    resp = c.get("/cases/nope")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "case not found"


# ── 404: UNENTITLED CALLER, IDENTICAL BODY TO "NO SUCH CASE" ───────────────────────────────

def test_unentitled_caller_gets_the_same_404_as_no_case(client_for):
    c = client_for(
        _user("mallory", domains=["NOTHING"]),
        _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=_SPEC1),
        get_definition=lambda wf_id: _definition(wf_id, classification="SAFETY"),
    )
    resp = c.get("/cases/c-1")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "case not found"


def test_submitter_sees_the_case(client_for):
    c = client_for(
        _user("alice", domains=[]),
        _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=_SPEC1),
        get_definition=lambda wf_id: _definition(wf_id, classification="SAFETY"),
    )
    resp = c.get("/cases/c-1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subject_ref"] == "c-1"
    assert len(body["instances"]) == 1
    assert body["instances"][0]["workflow_id"] == "c-1~1"
    assert body["instances"][0]["status"] == "completed"  # terminal set, state != failed


def test_entitled_by_domain_sees_the_case(client_for):
    c = client_for(
        _user("carol", domains=["safety"]),  # case-insensitive match to classification SAFETY
        _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=_SPEC1),
        get_definition=lambda wf_id: _definition(wf_id, classification="SAFETY"),
    )
    resp = c.get("/cases/c-1")
    assert resp.status_code == 200, resp.text


def test_case_with_no_instances_is_404_for_a_non_submitter(client_for):
    # No instances -> no facts -> only the (b) path applies, and labels is empty -> refused.
    c = client_for(_user("bob", domains=["ANYTHING"]), _FakeRestate(case=_CASE_NO_INSTANCES))
    resp = c.get("/cases/c-0")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "case not found"


# ── 503: RUNNER UNREACHABLE ──────────────────────────────────────────────────────────────────

def test_runner_unreachable_is_503(client_for):
    c = client_for(_user("bob"), _FakeRestate(boom=True))
    resp = c.get("/cases/c-1")
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "runner_unavailable"


# ── APPROVALS AND HITL-UNCONFIGURED FALLBACK ────────────────────────────────────────────────

def test_approvals_are_included_from_human_task_rows(client_for):
    rows = [{"task_id": "c-1~1:s1", "workflow_id": "c-1~1", "status": "pending",
             "decision": None, "acted_by": None, "acted_at": None, "comment": None}]
    c = client_for(_user("alice"), _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=_SPEC1),
                   get_definition=lambda wf_id: _definition(wf_id, classification="SAFETY"),
                   task_rows=rows)
    resp = c.get("/cases/c-1")
    assert resp.status_code == 200, resp.text
    approvals = resp.json()["approvals"]
    assert len(approvals) == 1
    assert approvals[0] == {"workflow_id": "c-1~1", "step_id": "s1", "status": "pending",
                            "decided_by": None, "decision": None, "reason": None,
                            "decided_at": None}


def test_hitl_unconfigured_is_empty_approvals_not_a_503(client_for):
    c = client_for(
        _user("alice"), _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=_SPEC1),
        get_definition=lambda wf_id: _definition(wf_id, classification="SAFETY"),
        htp_boom=human_tasks.HumanTaskConfigError("no PG DSN"),
    )
    resp = c.get("/cases/c-1")
    assert resp.status_code == 200, resp.text
    assert resp.json()["approvals"] == []


# ── OPTIONS / OUTPUT_ARTIFACT ─────────────────────────────────────────────────────────────

def test_options_and_output_artifact_are_empty_in_the_response(client_for):
    c = client_for(_user("alice"), _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=_SPEC1),
                   get_definition=lambda wf_id: _definition(wf_id, classification="SAFETY"))
    resp = c.get("/cases/c-1")
    body = resp.json()
    assert body["options"] == []
    assert body["output_artifact"] is None
