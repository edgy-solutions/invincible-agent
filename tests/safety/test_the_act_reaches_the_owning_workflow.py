"""HAZ-1003: `/act` resumes the workflow THAT OWNS the task, and resolves the projection
only after a CONFIRMED resume.

Before this fix, `act_on_human_task`'s generic resume path hardcoded
`/BPMNWorkflowRunner/{key}/approve` for EVERY workflow-backed task, and marked the projection
row resolved regardless of what that POST answered. A SafetyAcceptance acceptance (task_id
"acceptance", shared bare across every instance of the definition) therefore:

  * posted to a Restate service that was never running the suspended run (no `approve`
    handler existed on `SafetyAcceptance` at all before this), so the resume request itself
    had no workflow to answer it;
  * resolved the projection row ANYWAY, so the task showed resolved while the definition stayed
    suspended forever, unseen;
  * and because `task_id` was the bare step id, resolved EVERY pending row sharing that step id
    across every other workflow instance and type too.

This file seals the fix end to end: the resume target is derived from the row
(`workflow_service`/`promise_name`), re-checked against an allowlist before it is interpolated
into a Restate ingress URL, the projection is written only on a confirmed 200, the SQL scopes
the update to `workflow_id`, the register route refuses an unvetted service name at write time,
and engine-a's registration carries the composite task_id + both new fields for `_act` to use.

Run: uv run --frozen pytest tests/safety/test_the_act_reaches_the_owning_workflow.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway, human_tasks  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_RA), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── FAKES: the Restate ingress, as `httpx.AsyncClient` ─────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def json(self):
        return {}


class _FakeRestate:
    """Stands in for `httpx.AsyncClient` against the Restate ingress. Records every POST."""

    def __init__(self, status=200, boom=False):
        self.status, self.boom, self.posts = status, boom, []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json})
        if self.boom:
            raise RuntimeError("restate ingress unreachable")
        return _FakeResponse(self.status)


# ── THE ROUTE, through TestClient — arms 1-5 drive the real `/act` handler ─────────────────────

@pytest.fixture
def fresh_declarations(monkeypatch):
    monkeypatch.setattr(human_tasks, "_SEED_ROWS_CACHE", None, raising=False)


@pytest.fixture
def route(monkeypatch, fresh_declarations):
    calls = {"resolved": [], "settled": None}

    def mark_resolved(tid, **kw):
        calls["resolved"].append((tid, kw))
        return 1

    monkeypatch.setattr(human_tasks, "mark_task_resolved", mark_resolved)
    monkeypatch.setattr(human_tasks, "check_can_act", lambda audience, caller: True)
    monkeypatch.setattr(human_tasks, "get_task_resolution",
                         lambda tid, *, caller_id: calls["settled"])

    user = type("U", (), {"authz_id": "bob", "sub": "bob", "email": "bob@x",
                          "persona": "SAFETY_ENGINEER", "entitled_domains": ["SAFETY"],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c, calls, monkeypatch
    gateway.app.dependency_overrides.clear()


_TASK_ID = "wf-1:acceptance"


def _task(**over):
    base = {
        "task_id": _TASK_ID, "kind": "workflow_ack", "audience": "aud:safety-acceptance",
        "workflow_id": "wf-1", "workflow_service": "SafetyAcceptance",
        "promise_name": "approval_wf-1:acceptance", "payload": {},
    }
    base.update(over)
    return base


def _wire(route, task, client):
    c, calls, mp = route
    mp.setattr(human_tasks, "list_tasks_for", lambda caller, status="pending": [task])
    mp.setattr(gateway.httpx, "AsyncClient", client)
    return c, calls


def _act(c, decision="approved", comment=""):
    return c.post(f"/human_tasks/{_TASK_ID}/act", json={"decision": decision, "comment": comment})


# ── ARM 1: a new-shape row (workflow_service=SafetyAcceptance) resumes AGAINST THAT SERVICE ────

def test_ARM1_a_new_shape_row_routes_to_SafetyAcceptance_not_BPMNWorkflowRunner(route):
    fake = _FakeRestate(status=200)
    c, calls = _wire(route, _task(), fake)
    resp = _act(c)
    assert resp.status_code == 200, resp.text
    assert len(fake.posts) == 1
    url = fake.posts[0]["url"]
    assert "/SafetyAcceptance/" in url, f"posted to the wrong service: {url}"
    assert "/BPMNWorkflowRunner/" not in url
    assert url.endswith("/approve")
    assert "wf-1" in url


# ── ARM 2: a refused resume (403) is reported as a failure and the row STAYS PENDING ───────────

def test_ARM2_a_403_resume_is_502_and_the_row_stays_pending(route):
    fake = _FakeRestate(status=403)
    c, calls = _wire(route, _task(), fake)
    resp = _act(c)
    assert resp.status_code == 502, resp.text
    assert resp.json()["detail"]["error"] == "workflow_resume_failed"
    assert calls["resolved"] == [], "a refused resume must not mark the task resolved"


# ── ARM 3: a confirmed (200) resume resolves the projection EXACTLY ONCE ──────────────────────

def test_ARM3_a_200_resume_resolves_the_projection_exactly_once(route):
    fake = _FakeRestate(status=200)
    c, calls = _wire(route, _task(), fake)
    resp = _act(c, decision="approved", comment="looks good")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workflow_resumed"] is True
    assert body["rows_resolved"] == 1
    assert len(calls["resolved"]) == 1, "mark_task_resolved must be called exactly once"
    tid, kw = calls["resolved"][0]
    assert tid == _TASK_ID
    assert kw.get("workflow_id") == "wf-1", "the resolve must be scoped to this workflow_id"
    assert kw.get("decision") == "approved"


# ── ARM 4: an UNKNOWN workflow_service is refused BEFORE any POST, row stays pending ───────────

def test_ARM4_an_unknown_workflow_service_is_409_and_no_post_is_made(route):
    fake = _FakeRestate(status=200)
    c, calls = _wire(route, _task(workflow_service="EvilService"), fake)
    resp = _act(c)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "task_unresumable"
    assert fake.posts == [], "an unresumable row must never reach the ingress"
    assert calls["resolved"] == [], "an unresumable row must not be marked resolved"


# ── ARM 5: a LEGACY row (no workflow_service/promise_name) falls back to BPMNWorkflowRunner ────

def test_ARM5_a_legacy_row_with_no_workflow_service_falls_back_to_BPMNWorkflowRunner(route):
    legacy = _task()
    del legacy["workflow_service"]
    del legacy["promise_name"]
    fake = _FakeRestate(status=200)
    c, calls = _wire(route, legacy, fake)
    resp = _act(c)
    assert resp.status_code == 200, resp.text
    assert len(fake.posts) == 1
    assert "/BPMNWorkflowRunner/" in fake.posts[0]["url"]
    assert fake.posts[0]["json"]["promise_name"] is None


# ── ARM 6: the SQL update is scoped to workflow_id, via a recording-cursor double ──────────────

def test_ARM6_mark_task_resolved_scopes_the_UPDATE_by_workflow_id():
    fake_cur = mock.MagicMock()
    cur_cm = mock.MagicMock()
    cur_cm.__enter__ = mock.Mock(return_value=fake_cur)
    cur_cm.__exit__ = mock.Mock(return_value=False)
    fake_conn = mock.MagicMock()
    fake_conn.cursor.return_value = cur_cm
    conn_cm = mock.MagicMock()
    conn_cm.__enter__ = mock.Mock(return_value=fake_conn)
    conn_cm.__exit__ = mock.Mock(return_value=False)

    with mock.patch.object(human_tasks, "_pg_connect", return_value=conn_cm):
        human_tasks.mark_task_resolved(
            "wf-1:acceptance", caller_id="bob", decision="approved",
            comment="ok", workflow_id="wf-1",
        )

    sql, params = fake_cur.execute.call_args[0]
    assert "workflow_id IS NOT DISTINCT FROM %s" in sql, (
        "the UPDATE no longer scopes by workflow_id -- a cross-instance task_id collision "
        "(the HAZ-1003 defect) can resolve the wrong run's row again"
    )
    assert params[-1] == "wf-1", "the bound workflow_id must be the one the caller passed"

    # THE CONTROL: omitting workflow_id must still bind a (NULL-matching) value, not drop the
    # clause -- a legacy row's workflow_id is NULL and `NULL = NULL` is never true, so the SQL
    # must use IS NOT DISTINCT FROM and bind None here rather than skip the predicate.
    fake_cur.reset_mock()
    with mock.patch.object(human_tasks, "_pg_connect", return_value=conn_cm):
        human_tasks.mark_task_resolved(
            "legacy-task", caller_id="bob", decision="approved", comment="ok",
        )
    sql2, params2 = fake_cur.execute.call_args[0]
    assert "workflow_id IS NOT DISTINCT FROM %s" in sql2
    assert params2[-1] is None, "omitting workflow_id must bind NULL, matching legacy rows"


# ── ARM 7: engine-a's `_register_human_task`, driven through `_run_definition`, sends the ─────
# ── composite task_id + workflow_service + promise_name for a SafetyAcceptance-shaped step ────

class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _Captured(Exception):
    def __init__(self, name):
        self.name = name


class _CapturingPromise:
    def __init__(self, name):
        self._name = name

    def value(self):
        async def _a():
            raise _Captured(self._name)
        return _a()


class _AwaitCapturingCtx:
    """`WorkflowContext` stand-in: `ctx.run` executes the register synchronously (no real
    durability), and `ctx.promise(...).value()` raises the instant the step would suspend, so
    nothing past the register call executes. Same shape as `tests/test_promise_name_seal.py`."""

    def __init__(self, key="wf-7"):
        self._key = key
        self.state: dict = {}

    def key(self):
        return self._key

    def set(self, k, v):
        self.state[k] = v

    async def run(self, name, fn):
        r = fn()
        if hasattr(r, "__await__"):
            r = await r
        return r

    def promise(self, name, type_hint=None):
        return _CapturingPromise(name)


@pytest.fixture(autouse=True)
def _stub_can_act_and_mint(monkeypatch):
    import importlib
    for name in ("spo_step_executor", "agent_fleet.restate_analyst.spo_step_executor"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "check_can_act", lambda aud, who: True, raising=False)
    stub = lambda **_: "svc-token-stub"  # noqa: E731
    bound = 0
    for name in ("agent_fleet.utils.service_identity", "utils.service_identity", "main"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "mint_service_token", stub, raising=False)
        bound += 1
    assert bound, "mint_service_token was patched in ZERO modules -- update the name list"


def test_ARM7_safety_acceptance_registration_carries_composite_id_and_both_new_fields(
        monkeypatch):
    import main  # noqa: PLC0415 -- the flattened executor, per sys.path above

    posts = []

    def _record_post(url, json=None, headers=None, timeout=None):
        posts.append({"url": url, "json": json})
        return _Resp(200, {"task_id": json["task_id"], "recipients": ["approver@example.com"]})

    monkeypatch.setattr(main.requests, "post", _record_post)

    definition = {
        "id": "safety_acceptance_direct", "name": "Safety acceptance (direct)",
        "steps": [{
            "kind": "human_await", "id": "acceptance",
            "audience": "risk_acceptance_medium:SUSTAINMENT",
            "title": "Accept the risk", "summary": "A hazard awaits acceptance",
            "requested_by": "svc:safety",
        }],
    }
    ctx = _AwaitCapturingCtx(key="wf-7")
    with pytest.raises(_Captured):
        import asyncio
        asyncio.run(main._run_definition(
            ctx, "wf-7", definition, {"authz_id": "alice@example.com"},
            workflow_service="SafetyAcceptance",
        ))

    assert len(posts) == 1, f"expected exactly one register POST, got {posts}"
    body = posts[0]["json"]
    assert body["task_id"] == "wf-7:acceptance", (
        "the registered task_id is not the composite workflow_id:step_id -- a bare step id "
        "collides across every instance of this definition (the HAZ-1003 defect)"
    )
    assert body["workflow_service"] == "SafetyAcceptance"
    # The PROMISE name stays BARE (`approval_{step.id}`, one derivation, declared content) --
    # it is already scoped to this run by `ctx.promise` inside the workflow instance keyed on
    # `wf-7`. Only the REGISTERED task_id needs the composite form, because that is the one
    # value `mark_task_resolved`'s `WHERE task_id = %s` matches across EVERY instance.
    assert body["promise_name"] == "approval_acceptance"


# ── ARM 8: the register route refuses an unvetted workflow_service at WRITE time ───────────────

def test_ARM8_the_register_route_refuses_an_unknown_workflow_service(route):
    c, calls, mp = route
    resp = c.post("/internal/human_tasks/register", json={
        "kind": "workflow_ack", "task_id": "wf-9:step", "audience": "aud:x",
        "title": "t", "summary": "s", "requested_by": "svc:x",
        "workflow_id": "wf-9", "workflow_service": "EvilService",
    })
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "unknown_workflow_service"
