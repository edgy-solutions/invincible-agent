"""AN EXCLUDED ACTOR IS NEVER ROUTED THE TASK -- the row stays routed to everyone else.

Ruled by the architect on 2026-10-02 (item 5): "Don't route the excluded steward: audience
resolution removes the dropper before assignment; the row stays visible to others; direct access
refused with reason as today."

Before this, `excludes` reached only the executor's gate: the dropper of an artifact got the
origin-confirmation card in their queue like any other steward, and was refused only when they
answered it. Now the exclusion travels the whole register path:

  definition `excludes` -> executor binds it (strict) -> register body `excludes`
  -> `HumanTaskRegisterRequest.excludes` (DECLARED: the model drops unknown fields silently)
  -> `human_tasks.register_task` removes those actors from Topaz's set BEFORE any row exists.

The gate is unchanged and stays the backstop (sealed in
tests/test_an_origin_suggestion_runs_as_a_case.py). An exclusion that empties the audience is
NoEntitledRecipients, the same terminal 422 an ungranted audience gets.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

from tests.test_a_case_runs_from_trigger_to_terminal import main, wd
from tests import test_an_origin_suggestion_runs_as_a_case as og
from tests.test_an_origin_suggestion_runs_as_a_case import _real_policy, writer  # noqa: F401 -- fixtures

_HT = Path(__file__).resolve().parents[1] / "src" / "iagent" / "human_tasks.py"
_spec = importlib.util.spec_from_file_location("iagent_human_tasks_excl", _HT)
ht = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ht)  # type: ignore[union-attr]

DROPPER, STEWARD, OTHER = og.DROPPER, og.STEWARD, "steward-2@x"


# ── THE REGISTER: Topaz's actors, minus the excluded, before any row ────────────────────────

def _cm(value):
    cm = mock.MagicMock()
    cm.__enter__ = mock.Mock(return_value=value)
    cm.__exit__ = mock.Mock(return_value=False)
    return cm


def _register(actors, **over):
    """Run register_task against `actors`; return (result, recipient_ids of the rows written)."""
    rows = []
    conn = mock.MagicMock()
    conn.cursor.return_value = _cm(mock.MagicMock())
    kw = dict(kind="workflow_ack", task_id="SG-1~1:confirm", audience=og.AUDIENCE, title="t",
              summary="s", requested_by="svc:x")
    kw.update(over)
    with mock.patch.object(ht, "_resolve_audience_actors", return_value=list(actors)), \
         mock.patch.object(ht, "_pg_connect", return_value=_cm(conn)) as pg, \
         mock.patch.object(ht.psycopg2.extras, "execute_values",
                           side_effect=lambda c, sql, vals: rows.extend(vals)):
        out = ht.register_task(**kw)
    assert pg.called, "no row was written"
    return out, [r[5] for r in rows]


def test_THE_EXCLUDED_ACTOR_GETS_NO_ROW_AND_EVERY_OTHER_ACTOR_DOES():
    out, routed = _register([STEWARD, DROPPER, OTHER], excludes=[DROPPER])
    assert routed == [STEWARD, OTHER], routed
    assert out["recipients"] == [STEWARD, OTHER], out


@pytest.mark.parametrize("actor, barred", [("Dropper@X", DROPPER), (DROPPER, "DROPPER@x")])
def test_THE_EXCLUSION_IS_CASEFOLDED_AS_THE_GATE_COMPARES(actor, barred):
    """Both sides folded: Topaz's spelling of the actor and the trigger's spelling of the bar."""
    _, routed = _register([STEWARD, actor], excludes=[barred])
    assert routed == [STEWARD], routed


def test_CONTROL_NO_EXCLUSION_ROUTES_EVERY_ACTOR():
    for over in ({}, {"excludes": []}, {"excludes": None}):
        _, routed = _register([STEWARD, DROPPER], **over)
        assert routed == [STEWARD, DROPPER], (over, routed)


def test_AN_EXCLUSION_THAT_EMPTIES_THE_AUDIENCE_IS_REFUSED_BEFORE_ANY_ROW():
    with mock.patch.object(ht, "_resolve_audience_actors", return_value=["Dropper@x"]), \
         mock.patch.object(ht, "_pg_connect") as pg:
        with pytest.raises(ht.NoEntitledRecipients, match="excluded"):
            ht.register_task(kind="workflow_ack", task_id="SG-1~1:confirm", audience=og.AUDIENCE,
                             title="t", summary="s", requested_by="svc:x", excludes=[DROPPER])
    assert not pg.called, "a row was written for a task nobody may act on"


# ── THE ROUTE: the request model must DECLARE the field, or it is silently dropped ──────────

@pytest.fixture
def route(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from src.iagent import gateway, human_tasks
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


_BODY = {"kind": "workflow_ack", "task_id": "SG-1~1:confirm", "audience": og.AUDIENCE,
         "title": "t", "summary": "s", "requested_by": "svc:x"}


def test_THE_ROUTE_HANDS_THE_EXCLUSION_TO_THE_REGISTER(route):
    c, seen = route
    resp = c.post("/internal/human_tasks/register", json={**_BODY, "excludes": [DROPPER]})
    assert resp.status_code == 200, resp.text
    assert [kw.get("excludes") for kw in seen] == [[DROPPER]], seen


def test_CONTROL_A_REQUEST_WITHOUT_ONE_REGISTERS_WITH_NONE(route):
    c, seen = route
    assert c.post("/internal/human_tasks/register", json=_BODY).status_code == 200
    assert [kw.get("excludes") for kw in seen] == [[]], seen


# ── THE RUNNER: the bound exclusion rides the register body, and only when declared ─────────

class _Resp:
    status_code, text = 200, ""

    def json(self):
        return {"recipients": []}

    def raise_for_status(self):
        return None


@pytest.mark.parametrize("task_excludes, sent", [([DROPPER], [DROPPER]), (None, None), ([], None)])
def test_THE_REGISTER_BODY_CARRIES_THE_EXCLUSION_ONLY_WHEN_DECLARED(monkeypatch, task_excludes, sent):
    posts = []
    monkeypatch.setattr(main, "mint_service_token", lambda **_: "svc-token-stub")
    monkeypatch.setattr(main.requests, "post",
                        lambda url, json=None, **k: posts.append(json) or _Resp())
    task = {"id": "SG-1~1:confirm", "audience": og.AUDIENCE}
    if task_excludes is not None:
        task["excludes"] = task_excludes
    main._register_human_task("SG-1~1", task)
    assert len(posts) == 1, posts
    assert posts[0].get("excludes") == sent, posts[0]
    assert ("excludes" in posts[0]) is (sent is not None), posts[0]


@pytest.fixture
def routed(monkeypatch):
    tasks: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": tasks.append(dict(task)) or {})
    return tasks


@pytest.mark.asyncio
async def test_THE_ORIGIN_CASE_REGISTERS_ITS_CONFIRM_TASK_WITHOUT_ITS_DROPPER(routed, writer):
    out, _ = await og._run(og._suggestion(), [(og.CONFIRM, "accepted")])
    assert out["terminal"] == "resolved", out
    by_step = {t["id"].rsplit(":", 1)[1]: t.get("excludes") for t in routed}
    assert by_step.get("confirm") == [DROPPER], by_step
    # Only the step that declares one: every other task this case registers is routed whole.
    assert all(v is None for k, v in by_step.items() if k != "confirm"), by_step


# ── THE PATH THAT WOULD HONOUR IT IN NAME ONLY ──────────────────────────────────────────────

def _step(**over):
    return wd.HumanAwaitStep(**{"kind": "human_await", "id": "review", "audience": "a:b", **over})


def test_EXCLUDES_ON_A_GROUPED_AWAIT_IS_REFUSED_AT_LOAD():
    """The grouped path never binds `excludes`: it would neither route around nor refuse."""
    with pytest.raises(ValidationError, match="excludes"):
        _step(excludes=["{trigger.x}"], completion={"mode": "grouped"})


def test_CONTROL_A_GROUPED_AWAIT_WITHOUT_ONE_AND_A_SINGLE_AWAIT_WITH_ONE_BOTH_LOAD():
    for over in ({"completion": {"mode": "grouped"}}, {"excludes": ["{trigger.x}"]}):
        try:
            _step(**over)
        except ValidationError as e:
            raise AssertionError(f"a step the grouped refusal must not touch was refused: {over}: {e}")
