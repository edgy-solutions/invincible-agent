"""A task holder reads its case (architect ruling 2026-10-17).

A task registered from a case run carries that case's id (`human_task_projection.case_id`), and a
caller who holds ANY task row on a case may read it (`GET /cases/{id}` and `/action`) though
`can_view_case` would refuse them. The refusal stays the identical 404 for everyone else.

Arms:
  column   register_task writes case_id (None when absent); the migration and the create SQL add
           it; list_tasks_for selects it (Electric forwards columns verbatim).
  route    the register route declares case_id (blank = absent) and hands it to register_task.
  holder   holds_task_on_case keys on (case_id, recipient_id), any status; blank args are False.
  gate     a holder reads the case and its action record; a non-holder, a holder of ANOTHER case,
           and an unreadable store all get the unchanged 404.
  runner   the case run's register carries the case id; a body with none omits the field.

Run: uv run pytest tests/test_a_task_holder_reads_its_case.py -v
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from tests.test_a_case_runs_from_trigger_to_terminal import main  # noqa: E402
from tests import test_an_origin_suggestion_runs_as_a_case as og  # noqa: E402
from tests.test_an_origin_suggestion_runs_as_a_case import _real_policy, writer  # noqa: E402,F401
from tests.test_cases_route import (  # noqa: E402
    _CASE_ONE_INSTANCE, _SPEC1, _FakeRestate, _definition, _user,
)

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("iagent_human_tasks_f2", _ROOT / "src/iagent/human_tasks.py")
ht = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ht)  # type: ignore[union-attr]


def _cm(value):
    cm = mock.MagicMock()
    cm.__enter__ = mock.Mock(return_value=value)
    cm.__exit__ = mock.Mock(return_value=False)
    return cm


# -- column ----------------------------------------------------------------------------------

def _register(**over):
    rows, sqls = [], []
    conn = mock.MagicMock()
    conn.cursor.return_value = _cm(mock.MagicMock())
    kw = dict(kind="workflow_ack", task_id="c-1~1:s1", audience="aud:x", title="t", summary="s",
              requested_by="svc:x")
    kw.update(over)
    with mock.patch.object(ht, "_resolve_audience_actors", return_value=["a@x", "b@x"]), \
         mock.patch.object(ht, "_pg_connect", return_value=_cm(conn)), \
         mock.patch.object(ht.psycopg2.extras, "execute_values",
                           side_effect=lambda c, sql, vals: (sqls.append(sql), rows.extend(vals))):
        ht.register_task(**kw)
    return rows, sqls[0]


def test_every_recipient_row_carries_the_case_id():
    rows, sql = _register(case_id="c-1")
    assert [r[-1] for r in rows] == ["c-1", "c-1"]
    assert "promise_name, case_id)" in sql
    assert len(rows[0]) == 21


def test_CONTROL_a_task_with_no_case_writes_none():
    rows, _ = _register()
    assert [r[-1] for r in rows] == [None, None]


def test_the_migration_and_the_create_sql_add_the_column():
    assert "ADD COLUMN IF NOT EXISTS case_id TEXT" in ht._MIGRATION_SQL
    sql = (_ROOT / "sql/create_human_task_projection.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS case_id TEXT" in sql


def test_the_queue_read_selects_case_id():
    seen = []
    cur = mock.MagicMock()
    cur.execute.side_effect = lambda sql, params=None: seen.append(sql)
    cur.fetchall.return_value = []
    conn = mock.MagicMock()
    conn.cursor.return_value = _cm(cur)
    with mock.patch.object(ht, "_pg_connect", return_value=_cm(conn)):
        ht.list_tasks_for("a@x")
    assert "case_id" in seen[0].split("FROM")[0], seen[0]


# -- route -----------------------------------------------------------------------------------

@pytest.fixture
def route(monkeypatch):
    from src.iagent import human_tasks
    seen = []
    monkeypatch.setattr(human_tasks, "register_task",
                        lambda **kw: seen.append(kw) or {"task_id": kw["task_id"], "recipients": []})
    user = type("U", (), {"authz_id": "svc", "sub": "svc", "email": "svc@x", "persona": "SVC",
                          "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    try:
        with TestClient(gateway.app) as c:
            yield c, seen
    finally:
        gateway.app.dependency_overrides.clear()


_BODY = {"kind": "workflow_ack", "task_id": "c-1~1:s1", "audience": "aud:x",
         "title": "t", "summary": "s", "requested_by": "svc:x"}


@pytest.mark.parametrize("sent, got", [("c-1", "c-1"), ("  c-1 ", "c-1"), ("", None),
                                       ("   ", None), (None, None)])
def test_the_register_route_hands_the_case_id_on(route, sent, got):
    c, seen = route
    assert c.post("/internal/human_tasks/register", json={**_BODY, "case_id": sent}).status_code == 200
    assert [kw.get("case_id") for kw in seen] == [got], seen


def test_CONTROL_a_request_without_one_registers_with_none(route):
    c, seen = route
    assert c.post("/internal/human_tasks/register", json=_BODY).status_code == 200
    assert [kw.get("case_id") for kw in seen] == [None], seen


# -- holder ----------------------------------------------------------------------------------

def _holds(row, *, case_id="c-1", caller="bob"):
    cur = mock.MagicMock()
    cur.fetchone.return_value = row
    conn = mock.MagicMock()
    conn.cursor.return_value = _cm(cur)
    with mock.patch.object(ht, "_pg_connect", return_value=_cm(conn)):
        out = ht.holds_task_on_case(case_id, caller)
    return out, cur


def test_a_row_for_this_case_and_recipient_is_a_hold_whatever_its_status():
    out, cur = _holds((1,))
    assert out is True
    sql, params = cur.execute.call_args[0]
    assert "case_id = %s" in sql and "recipient_id = %s" in sql
    assert "status" not in sql
    assert params == ("c-1", "bob")


def test_CONTROL_no_row_is_no_hold():
    assert _holds(None)[0] is False


@pytest.mark.parametrize("case_id, caller", [("", "bob"), ("c-1", ""), (None, "bob")])
def test_a_blank_argument_is_no_hold_and_asks_nothing(case_id, caller):
    out, cur = _holds((1,), case_id=case_id, caller=caller)
    assert out is False and not cur.execute.called


# -- gate ------------------------------------------------------------------------------------

@pytest.fixture
def client_for(monkeypatch):
    from agent_fleet.restate_analyst import workflow_definition
    from src.iagent import human_tasks
    held = set()

    def _holds_stub(case_id, caller):
        return (case_id, caller) in held

    def _make(user, fake, holds=()):
        held.clear()
        held.update(holds)
        monkeypatch.setattr(gateway.httpx, "AsyncClient", fake)
        monkeypatch.setattr(workflow_definition, "get_workflow_definition",
                            lambda wf_id: _definition(wf_id, classification="SAFETY"))
        monkeypatch.setattr(human_tasks, "list_tasks_for_workflows", lambda ids: [])
        monkeypatch.setattr(human_tasks, "holds_task_on_case", _holds_stub)
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
        return TestClient(gateway.app)
    yield _make
    gateway.app.dependency_overrides.clear()


def _present():
    return _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=_SPEC1)


def test_a_task_holder_who_cannot_otherwise_view_reads_the_case(client_for):
    r = client_for(_user("bob"), _present(), holds={("c-1", "bob")}).get("/cases/c-1")
    assert r.status_code == 200, r.text


def test_CONTROL_the_same_stranger_without_a_task_gets_the_404(client_for):
    r = client_for(_user("bob"), _present()).get("/cases/c-1")
    assert r.status_code == 404 and r.json()["detail"] == "case not found"


def test_a_task_on_another_case_admits_nothing(client_for):
    r = client_for(_user("bob"), _present(), holds={("c-2", "bob"), ("c-1", "carol")}).get("/cases/c-1")
    assert r.status_code == 404 and r.json()["detail"] == "case not found"


def test_an_unreadable_task_store_is_the_same_404(client_for, monkeypatch):
    from src.iagent import human_tasks

    def _boom(case_id, caller):
        raise human_tasks.HumanTaskConfigError("no store")
    c = client_for(_user("bob"), _present())
    monkeypatch.setattr(human_tasks, "holds_task_on_case", _boom)
    r = c.get("/cases/c-1")
    assert r.status_code == 404 and r.json()["detail"] == "case not found"


def test_the_holder_reads_the_action_record_too(client_for):
    c = client_for(_user("bob"), _present(), holds={("c-1", "bob")})
    assert c.get("/cases/c-1/action").status_code != 404
    c2 = client_for(_user("bob"), _present())
    assert c2.get("/cases/c-1/action").status_code == 404


def test_the_viewer_who_already_reads_the_case_never_asks_the_store(client_for, monkeypatch):
    from src.iagent import human_tasks
    asked = []
    c = client_for(_user("alice"), _present())
    monkeypatch.setattr(human_tasks, "holds_task_on_case", lambda *a: asked.append(a) or False)
    assert c.get("/cases/c-1").status_code == 200
    assert asked == []


# -- runner ----------------------------------------------------------------------------------

class _Resp:
    status_code, text = 200, ""

    def json(self):
        return {"recipients": []}

    def raise_for_status(self):
        return None


@pytest.mark.parametrize("case_id, present", [("c-1", True), (None, False), ("", False)])
def test_the_register_body_carries_case_id_only_when_given(monkeypatch, case_id, present):
    posts = []
    monkeypatch.setattr(main, "mint_service_token", lambda **_: "svc-token-stub")
    monkeypatch.setattr(main.requests, "post", lambda url, json=None, **k: posts.append(json) or _Resp())
    main._register_human_task("c-1~1", {"id": "c-1~1:s1", "audience": "aud:x"}, "workflow_ack", case_id)
    assert ("case_id" in posts[0]) is present, posts[0]
    if present:
        assert posts[0]["case_id"] == "c-1"


@pytest.mark.asyncio
async def test_the_case_runs_register_names_its_case(monkeypatch, writer):
    seen = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack", case_id=None: seen.append((wf, case_id)) or {})
    out, _ = await og._run(og._suggestion(), [(og.CONFIRM, "accepted")])
    assert out["terminal"] == "resolved", out
    assert seen and all(c == "SG-1" for _, c in seen), seen
