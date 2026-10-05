"""POST /internal/origin/write (item B, 2026-10-03) -- the origin_record case's `written`
direct_call step's own transport. Harness mirrors tests/test_gateway_ingest_routes.py:
TestClient(gateway.app) + dependency_overrides[get_current_user]; `origin_writer.write_origin`
is faked so these are tests of the ROUTE's gate and translation, not of the graph write itself
(covered in tests/test_origin_writer.py).

WHAT THESE DEFEND (item B's named mutants, (b)/(c)/(e)):
  (b) the route accepts any caller -- only `svc:case-runner` may call this; every other caller
      gets 403 before `origin_writer.write_origin` is ever reached.
  (c) on_behalf_of not recorded -- the Initiator handed to `write_origin` carries the STEWARD's
      `approver_sub` from `approval_chain`, as a `kind: delegate` write, never the case
      runner's own identity standing in for the steward's.
  (e) the bound check skipped -- an `approval_chain` with no `role: steward` entry (or one with
      no `approver_sub`) is refused 422 before `write_origin` is ever reached.
Plus the two passthrough shapes the spec names explicitly: `written`/`write_refused` both
answer 200 (a refused write is a normal outcome, never an HTTP error).

Run: uv run --frozen pytest tests/test_origin_write_route.py -v
"""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import origin_writer  # noqa: E402

# the SAME workflow_definition module object `main`/the real executor validates with -- see
# tests/test_a_case_runs_from_trigger_to_terminal.py's own import for why (sys.path, not a
# package import: `agent_fleet/restate_analyst` is not itself a package).
from tests.test_a_case_runs_from_trigger_to_terminal import wd  # noqa: E402

BODY = {
    "artifact_id": "ART-9",
    "dropped_by": {"authz_id": "dropper@x"},
    "origin": {"owner_domain": "aviation", "program": "PRG-1",
               "obtained_via": "contract_deliverable"},
    "evidence": {"source": "contract", "citation": "CDRL A001 para 3"},
    "approval_chain": [
        {"step": 1, "role": "steward", "approver_sub": "steward@x", "decision": "approved"},
    ],
}


def _user(authz_id):
    return type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": None, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()


@pytest.fixture
def client():
    def _make(authz_id):
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _user(authz_id)
        return TestClient(gateway.app)
    yield _make
    gateway.app.dependency_overrides.clear()


class _Calls(list):
    """A list of captured `write_origin` calls that can also hold the canned result the fake
    returns -- so a test can flip to `write_refused` without a second fixture."""


@pytest.fixture
def fake_write_origin(monkeypatch):
    """Captures every write_origin call instead of touching Neo4j; returns `written` by
    default. A test that wants `write_refused` calls `.set_result(...)`."""
    calls = _Calls()
    result = {"status": "written", "reason": None}

    def _fake(resolution, *, graph_writer, initiator, dropper_is_program_member):
        calls.append({
            "resolution": resolution, "initiator": initiator,
            "dropper_is_program_member": dropper_is_program_member,
        })
        return result

    monkeypatch.setattr(origin_writer, "write_origin", _fake)

    def _set_result(status, reason=None):
        result["status"], result["reason"] = status, reason

    calls.set_result = _set_result
    return calls


# ── (b) THE CALLER GATE ─────────────────────────────────────────────────────────────────────

def test_A_NON_CASE_RUNNER_CALLER_IS_REFUSED_BEFORE_WRITE_ORIGIN_IS_REACHED(client, fake_write_origin):
    resp = client("alice@example.com").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 403, resp.text
    assert fake_write_origin == [], fake_write_origin


def test_AN_UNAUTHENTICATED_CALLER_IS_ALSO_REFUSED(client, fake_write_origin):
    resp = client("").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 403, resp.text
    assert fake_write_origin == [], fake_write_origin


def test_THE_CASE_RUNNERS_OWN_IDENTITY_PASSES_THE_GATE(client, fake_write_origin):
    resp = client("svc:case-runner").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 200, resp.text
    assert len(fake_write_origin) == 1, fake_write_origin


# ── (c) on_behalf_of IS RECORDED ────────────────────────────────────────────────────────────

def test_ON_BEHALF_OF_IS_THE_STEWARDS_APPROVER_SUB_NOT_THE_CASE_RUNNERS_OWN(client, fake_write_origin):
    resp = client("svc:case-runner").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 200, resp.text
    [call] = fake_write_origin
    initiator = call["initiator"]
    assert initiator.kind == "delegate", initiator
    assert initiator.subject == "svc:case-runner", initiator
    assert initiator.on_behalf_of == "steward@x", initiator


def test_ON_BEHALF_OF_TAKES_THE_LAST_STEWARD_ENTRY_WHEN_SEVERAL_EXIST(client, fake_write_origin):
    body = dict(BODY, approval_chain=[
        {"step": 1, "role": "steward", "approver_sub": "first@x", "decision": "approved"},
        {"step": 2, "role": "steward", "approver_sub": "second@x", "decision": "approved"},
    ])
    resp = client("svc:case-runner").post("/internal/origin/write", json=body)
    assert resp.status_code == 200, resp.text
    [call] = fake_write_origin
    assert call["initiator"].on_behalf_of == "second@x", call["initiator"]


# ── (e) THE BOUND CHECK ─────────────────────────────────────────────────────────────────────

def test_NO_STEWARD_ENTRY_IN_THE_APPROVAL_CHAIN_IS_REFUSED_422(client, fake_write_origin):
    body = dict(BODY, approval_chain=[
        {"step": 1, "role": "requester", "approver_sub": "someone@x", "decision": "approved"},
    ])
    resp = client("svc:case-runner").post("/internal/origin/write", json=body)
    assert resp.status_code == 422, resp.text
    assert fake_write_origin == [], fake_write_origin


def test_A_STEWARD_ENTRY_WITH_NO_APPROVER_SUB_IS_REFUSED_422(client, fake_write_origin):
    body = dict(BODY, approval_chain=[
        {"step": 1, "role": "steward", "approver_sub": "", "decision": "approved"},
    ])
    resp = client("svc:case-runner").post("/internal/origin/write", json=body)
    assert resp.status_code == 422, resp.text
    assert fake_write_origin == [], fake_write_origin


def test_AN_EMPTY_APPROVAL_CHAIN_IS_REFUSED_422(client, fake_write_origin):
    body = dict(BODY, approval_chain=[])
    resp = client("svc:case-runner").post("/internal/origin/write", json=body)
    assert resp.status_code == 422, resp.text
    assert fake_write_origin == [], fake_write_origin


# ── BOTH OUTCOMES ANSWER 200, NEVER AN HTTP ERROR ───────────────────────────────────────────

def test_A_WRITTEN_RESULT_ANSWERS_200(client, fake_write_origin):
    resp = client("svc:case-runner").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "written", "reason": None}, resp.json()


def test_A_WRITE_REFUSED_RESULT_ALSO_ANSWERS_200_NOT_AN_HTTP_ERROR(client, fake_write_origin):
    fake_write_origin.set_result("write_refused", "dropper is not a program member")
    resp = client("svc:case-runner").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "status": "write_refused", "reason": "dropper is not a program member",
    }, resp.json()


# ── (d) THE ACCEPT STEP IS direct_call, NOT signal_await ────────────────────────────────────

def test_THE_WRITTEN_STEP_IS_A_GATED_direct_call_NOT_A_signal_await():
    [step] = [s for s in wd.get_workflow_definition("origin_record").steps if s.id == "written"]
    assert step.kind == "direct_call", step
    assert step.capability == "origin.write", step
    assert step.endpoint == "{origin_write_endpoint}", step
    assert set(step.extra_payload) == {
        "artifact_id", "dropped_by", "origin", "evidence", "approval_chain",
    }, step.extra_payload
