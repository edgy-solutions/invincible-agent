"""One open review per notice (lane/74, item 2c, architect ruling 2026-11-19): "a newer review
supersedes an older pending one, which is cancelled and recorded as superseded."

"A notice" is the artifact's LOCATION (`artifact_uri`), never the LLM-derived `notice_id`.

Seals
  S1  the journal commands `_run_grouped_human_await` issues before its promise await are unchanged
  S2  `supersede`'s decision table, row by row
  S3  `submit_decision` refuses a decision carrying the reserved key
  S4  the run's post-await branch: SUPERSEDED, no dispatch; control: an accepted decision dispatches
  S5  the gateway supersedes the older pending reviews of the same artifact
  S6  controls: a different artifact supersedes nothing; no artifact makes no query
  S7  a failing supersede call still marks the rows, and the start still succeeds
  S8  the finder's SQL
  S9  the register path carries `artifact_uri` onto the row payload
"""
from __future__ import annotations

import ast
import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "agent_fleet" / "restate_analyst"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("restate")
pytest.importorskip("fastapi")

import dispatch_driver  # noqa: E402
import grouped_review_workflow as grw  # noqa: E402
import main as ra_main  # noqa: E402
import restate  # noqa: E402

from src.iagent import gateway, human_tasks  # noqa: E402
from tests.test_grouped_review_workflow import _allow_can_act  # noqa: E402,F401  (autouse fixture)
from tests.test_steward_correction import _approve, _request, _run_step, fx  # noqa: E402,F401

_SUPERSEDE = grw.supersede.__wrapped__
_SUBMIT = grw.submit_decision.__wrapped__
_URI = "s3://bucket/reviews/PCN-1/review.json"
_AUD = "promotion:SUSTAINMENT"
_ACTOR = "approver@example.com"
_NEW = "pcn-review-PCN-1-svc:review-starter-newhash000"
_OLD = "pcn-review-PCN-1-svc:review-starter-oldhash000"


# --------------------------------------------------------------------------------------------
# S1 — the replay rule
# --------------------------------------------------------------------------------------------
# A RECORDED JOURNAL SHAPE, not a derivation: the `ctx.*` journal commands (not `ctx.key()`, which
# is not journaled) that `_run_grouped_human_await` issues, in source order, up to and including its
# `ctx.promise(...)` await. Read once from
# `git show origin/master:agent_fleet/restate_analyst/main.py` (origin/master 08ce14f9).
# About 27 reviews are suspended at that await and must replay after the roll: a command added above
# it fails them all with 570. It may only change by a gated append.
MASTER_PRE_AWAIT = [
    ("set", "'batch_items'"), ("set", "'approver'"), ("set", "'notice_fingerprint'"),
    ("set", "'ingest_id'"), ("set", "'notice_id'"), ("set", "'doc_type'"),
    ("set", "'pipeline_version'"), ("set", "'extraction_warnings'"), ("set", "'artifact_uri'"),
    ("set", "_audience_key(promise_name)"),
    ("run", "'register_grouped_task'"),
    ("promise", "promise_name"),
]


def _pre_await_ctx_calls(src: str) -> list:
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_grouped_human_await")
    calls = sorted((n for n in ast.walk(fn) if isinstance(n, ast.Call)),
                   key=lambda n: (n.lineno, n.col_offset, -(n.end_col_offset or 0)))
    out = []
    for n in calls:
        f = n.func
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id == "ctx" and f.attr != "key"):
            out.append((f.attr, ast.unparse(n.args[0]) if n.args else None))
            if f.attr == "promise":
                return out
    raise AssertionError("no ctx.promise await found in _run_grouped_human_await")


def test_s1_the_journal_before_the_await_is_masters():
    src = (Path(ra_main.__file__)).read_text(encoding="utf-8")
    assert _pre_await_ctx_calls(src) == MASTER_PRE_AWAIT, (
        "a ctx command above the promise await changed: suspended reviews would fail replay (570)")


# --------------------------------------------------------------------------------------------
# doubles
# --------------------------------------------------------------------------------------------
class _Promise:
    def __init__(self, rec, name):
        self._rec, self._name = rec, name

    async def resolve(self, value):
        self._rec.append((self._name, value))


class _Shared:
    def __init__(self, state, key=_OLD):
        self._state, self._key = state, key
        self.resolved: list = []

    def key(self):
        return self._key

    async def get(self, name, **kw):
        return self._state.get(name)

    def promise(self, name, type_hint=None):
        return _Promise(self.resolved, name)


def _live(**over):
    state = {
        "batch_items": [{"mpn": "A", "subject": "http://internal/components/A",
                         "proposed_disposition": "dispatchQualification", "needs_review": False}],
        "approver": "qa", "notice_fingerprint": "IPCN25300X", "artifact_uri": _URI,
        "audience:decision": _AUD,
    }
    state.update(over)
    return state


def _sup_req(**over):
    r = {"superseded_by": _NEW, "acted_by": _ACTOR, "artifact_uri": _URI}
    r.update(over)
    return r


def _err(awaitable):
    with pytest.raises(restate.TerminalError) as ei:
        asyncio.run(awaitable)
    return ei.value


# --------------------------------------------------------------------------------------------
# S2 — the supersede handler's table
# --------------------------------------------------------------------------------------------
def test_s2_row1_no_active_review_is_404():
    assert _err(_SUPERSEDE(_Shared({}), _sup_req())).status_code == 404


@pytest.mark.parametrize("who", ["", "   ", None])
def test_s2_row2_no_actor_is_401(who):
    ctx = _Shared(_live())
    assert _err(_SUPERSEDE(ctx, _sup_req(acted_by=who))).status_code == 401
    assert ctx.resolved == []


@pytest.mark.parametrize("by", ["", "  ", None, _OLD])
def test_s2_row3_a_missing_or_self_superseder_is_422(by):
    ctx = _Shared(_live())
    assert _err(_SUPERSEDE(ctx, _sup_req(superseded_by=by))).status_code == 422
    assert ctx.resolved == []


@pytest.mark.parametrize("held,named", [
    ("", _URI),                      # a review with no artifact_uri
    (_URI, "s3://bucket/other.json"),  # a different artifact
    (_URI, ""),                      # a caller that names none
])
def test_s2_row4_not_the_same_artifact_is_409(held, named):
    ctx = _Shared(_live(artifact_uri=held))
    e = _err(_SUPERSEDE(ctx, _sup_req(artifact_uri=named)))
    assert e.status_code == 409 and "not_the_same_artifact" in str(e)
    assert ctx.resolved == []


def test_s2_a_review_with_no_artifact_key_at_all_is_409():
    state = _live()
    del state["artifact_uri"]
    ctx = _Shared(state)
    assert _err(_SUPERSEDE(ctx, _sup_req())).status_code == 409
    assert ctx.resolved == []


def test_s2_row5_a_decided_review_is_never_superseded():
    ctx = _Shared(_live(decision_consumed=True))
    out = asyncio.run(_SUPERSEDE(ctx, _sup_req()))
    assert out == {"status": "already_resolved", "superseded": False}
    assert ctx.resolved == [], "a decided review had its promise resolved"


def test_s2_row6_resolves_the_decision_promise_under_the_reserved_key():
    ctx = _Shared(_live())
    out = asyncio.run(_SUPERSEDE(ctx, _sup_req()))
    assert out == {"status": "superseded", "superseded": True}
    assert ctx.resolved == [("decision", {"__superseded__": {
        "superseded_by": _NEW, "acted_by": _ACTOR, "kind": "superseded"}})]


def test_s2_the_promise_is_the_one_submit_decision_resolves():
    a, b = _Shared(_live()), _Shared(_live())
    asyncio.run(_SUPERSEDE(a, _sup_req()))
    asyncio.run(_SUBMIT(b, {"decision": {"overrides": {}}, "acted_by": _ACTOR}))
    assert a.resolved[0][0] == b.resolved[0][0] == "decision"


# --------------------------------------------------------------------------------------------
# S3 — forgery
# --------------------------------------------------------------------------------------------
def test_s3_a_reviewer_decision_cannot_carry_the_reserved_key():
    ctx = _Shared(_live())
    forged = {"overrides": {}, "__superseded__": {"superseded_by": "x", "acted_by": _ACTOR}}
    out = asyncio.run(_SUBMIT(ctx, {"decision": forged, "acted_by": _ACTOR}))
    assert out["status"] == "still_pending" and out["accepted"] is False
    assert out["reason"] == "reserved_key"
    assert ctx.resolved == [], "a forged supersession resolved the promise"


def test_s3_control_the_same_decision_without_the_key_is_accepted():
    ctx = _Shared(_live())
    out = asyncio.run(_SUBMIT(ctx, {"decision": {"overrides": {}}, "acted_by": _ACTOR}))
    assert out["status"] == "accepted" and len(ctx.resolved) == 1


def test_s3_submit_on_a_superseded_review_says_so():
    ctx = _Shared(_live(decision_consumed=True, superseded_by=_NEW))
    out = asyncio.run(_SUBMIT(ctx, {"decision": {"overrides": {}}, "acted_by": _ACTOR}))
    assert out["status"] == "superseded" and out["accepted"] is False
    assert out["superseded_by"] == _NEW
    assert ctx.resolved == []
    ctx2 = _Shared(_live(decision_consumed=True))
    out2 = asyncio.run(_SUBMIT(ctx2, {"decision": {"overrides": {}}, "acted_by": _ACTOR}))
    assert out2["status"] == "already_resolved"


# --------------------------------------------------------------------------------------------
# S4 — after the await
# --------------------------------------------------------------------------------------------
def _superseded_value():
    return {"__superseded__": {"superseded_by": _NEW, "acted_by": _ACTOR, "kind": "superseded"}}


@pytest.mark.asyncio
async def test_s4_a_superseded_wake_dispatches_nothing(fx):  # noqa: F811
    out, ctx = await _run_step(_superseded_value(), fx)
    assert out["status"] == "SUPERSEDED" and out["superseded_by"] == _NEW
    assert out["count"] == 0 and out["dispatched_keys"] == [] and out["dispatch_enqueued"] == 0
    assert ctx.state["superseded_by"] == _NEW
    assert ctx.state["decision_consumed"] is True
    assert ctx.sends == [], "a superseded review fanned out"
    assert fx.writes == [] and fx.resolved == []
    assert [t["kind"] for t in fx.minted] == ["grouped_review"], "only the review's own task is registered"


@pytest.mark.asyncio
async def test_s4_control_an_accepted_decision_still_dispatches(fx):  # noqa: F811
    out, ctx = await _run_step(_approve(), fx)
    assert out["status"] == "RESOLVED" and out["count"] >= 1
    assert ctx.sends, "the normal path stopped dispatching"
    assert "superseded_by" not in ctx.state


@pytest.mark.asyncio
async def test_s4_the_task_row_carries_the_artifact_location(fx):  # noqa: F811
    _, ctx = await _run_step(_approve(), fx, request=_request(artifact_uri=_URI))
    assert fx.minted[0]["artifact_uri"] == _URI
    _, ctx = await _run_step(_approve(), fx, request=_request())
    assert fx.minted[-1]["artifact_uri"] == ""


# --------------------------------------------------------------------------------------------
# the gateway's start route
# --------------------------------------------------------------------------------------------
class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._b, self.text = status, body, "SECRET-BODY-TEXT"

    def json(self):
        return self._b


class _World:
    def __init__(self, monkeypatch, *, older=(), supersede_answer=None, supersede_raises=None,
                 started_id=_NEW):
        self.posts, self.finds, self.marks = [], [], []
        world = self
        answer = supersede_answer or {"status": "superseded", "superseded": True}

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None):
                world.posts.append({"url": url, "json": json})
                if url.endswith("/ReviewStarter/start_review"):
                    return _Resp({"status": "STARTED", "workflow_id": started_id})
                if supersede_raises is not None:
                    raise supersede_raises
                return _Resp(answer)

        monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(gateway, "_review_on_behalf_of", lambda uri: "")

        def _find(kind, artifact_uri, *, excluding_task_id):
            world.finds.append((kind, artifact_uri, excluding_task_id))
            return [{"task_id": o["task_id"], "workflow_id": o["workflow_id"]} for o in older
                    if o.get("uri", artifact_uri) == artifact_uri and o["task_id"] != excluding_task_id]
        monkeypatch.setattr(human_tasks, "pending_reviews_for_artifact", _find)

        def _mark(task_id, superseded_by=None):
            world.marks.append((task_id, superseded_by))
            return 2
        monkeypatch.setattr(human_tasks, "supersede_open_task", _mark)

    def ingress_supersedes(self):
        return [p for p in self.posts if p["url"].endswith("/supersede")]


_OLDER = [{"task_id": "grouped:" + _OLD, "workflow_id": _OLD}]


def _req(**kw):
    base = dict(notice_id="PCN-1", impacted_parts=[{"affected_mpn": "A"}], request_key="rk-1",
                artifact_uri=_URI)
    base.update(kw)
    return gateway.ReviewStartRequest(**base)


def _start(req, authz_id="svc:review-starter"):
    user = SimpleNamespace(authz_id=authz_id)
    return asyncio.run(gateway._start_review_core(req, current_user=user, raw_token="tok"))


# S5
def test_s5_a_newer_review_of_the_same_artifact_supersedes_the_older_pending_one(monkeypatch):
    w = _World(monkeypatch, older=_OLDER)
    out = _start(_req())
    assert w.finds == [(gateway._GROUPED_REVIEW_KIND, _URI, "grouped:" + _NEW)]
    assert gateway._GROUPED_REVIEW_KIND == "grouped_review"
    (call,) = w.ingress_supersedes()
    assert call["url"].endswith(f"/GroupedReview/{gateway._restate_key(_OLD)}/supersede")
    assert call["json"] == {"superseded_by": _NEW, "acted_by": "svc:review-starter",
                            "artifact_uri": _URI}
    assert w.marks == [("grouped:" + _OLD, _NEW)]
    assert out["status"] == "STARTED"
    assert out["superseded"] == [{"workflow_id": _OLD, "task_id": "grouped:" + _OLD,
                                  "ended": True, "rows_superseded": 2}]


def test_s5_an_already_resolved_older_review_is_not_reported_ended(monkeypatch):
    w = _World(monkeypatch, older=_OLDER,
               supersede_answer={"status": "already_resolved", "superseded": False})
    out = _start(_req())
    assert w.marks == [("grouped:" + _OLD, _NEW)]  # the writer touches only pending rows
    assert out["superseded"][0]["ended"] is False


def test_s5_the_new_task_is_excluded_so_an_idempotent_start_supersedes_nothing(monkeypatch):
    w = _World(monkeypatch, older=[{"task_id": "grouped:" + _NEW, "workflow_id": _NEW}])
    out = _start(_req())
    assert w.finds[0][2] == "grouped:" + _NEW
    assert w.ingress_supersedes() == [] and w.marks == []
    assert out["superseded"] == []


# S6
def test_s6_a_different_artifact_supersedes_nothing(monkeypatch):
    w = _World(monkeypatch, older=[{**_OLDER[0], "uri": "s3://bucket/reviews/PCN-1/other.json"}])
    out = _start(_req())
    assert w.finds and w.ingress_supersedes() == [] and w.marks == []
    assert out["superseded"] == []


def test_s6_no_artifact_makes_no_query_and_no_call(monkeypatch):
    w = _World(monkeypatch, older=_OLDER)
    out = _start(_req(artifact_uri=None))
    assert w.finds == [] and w.ingress_supersedes() == [] and w.marks == []
    assert "superseded" not in out


# S7
@pytest.mark.parametrize("exc", [RuntimeError("SECRET-BODY-TEXT"), TimeoutError("SECRET-BODY-TEXT")])
def test_s7_a_failed_supersede_call_still_marks_the_rows_and_the_start_succeeds(monkeypatch, caplog, exc):
    w = _World(monkeypatch, older=_OLDER, supersede_raises=exc)
    with caplog.at_level(logging.DEBUG):
        out = _start(_req())
    assert out["status"] == "STARTED"
    assert w.marks == [("grouped:" + _OLD, _NEW)]
    assert out["superseded"] == [{"workflow_id": _OLD, "task_id": "grouped:" + _OLD,
                                  "ended": False, "rows_superseded": 2}]
    lines = [r.getMessage() for r in caplog.records if "supersede" in r.getMessage()]
    assert lines and any(_OLD in ln and type(exc).__name__ in ln for ln in lines)
    assert "SECRET-BODY-TEXT" not in caplog.text


def test_s7_a_non_200_answer_is_a_failure_that_logs_no_body(monkeypatch, caplog):
    w = _World(monkeypatch, older=_OLDER)

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            if url.endswith("/ReviewStarter/start_review"):
                return _Resp({"status": "STARTED", "workflow_id": _NEW})
            return _Resp({}, status=404)
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _C)
    with caplog.at_level(logging.DEBUG):
        out = _start(_req())
    assert out["superseded"][0]["ended"] is False and w.marks
    assert "SECRET-BODY-TEXT" not in caplog.text


# --------------------------------------------------------------------------------------------
# S8 — the finder's SQL
# --------------------------------------------------------------------------------------------
class _Cur:
    def __init__(self, rec, rows):
        self._rec, self._rows = rec, rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._rec.append((sql, params))

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rec, rows):
        self._rec, self._rows = rec, rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cur(self._rec, self._rows)


def _db(monkeypatch, rows=()):
    rec: list = []
    monkeypatch.setattr(human_tasks, "_pg_connect", lambda: _Conn(rec, list(rows)))
    return rec


def test_s8_the_finder_sql_is_parameterised_and_keyed_on_the_artifact(monkeypatch):
    rec = _db(monkeypatch, rows=[("grouped:a", "wf-a")])
    out = human_tasks.pending_reviews_for_artifact("grouped_review", _URI, excluding_task_id="grouped:new")
    assert out == [{"task_id": "grouped:a", "workflow_id": "wf-a"}]
    ((sql, params),) = rec
    flat = " ".join(sql.split())
    assert "payload->>'artifact_uri' = %s" in flat
    assert "status = 'pending'" in flat
    assert "task_id <> %s" in flat and "kind = %s" in flat
    assert "DISTINCT" in flat
    assert flat.index("kind = %s") < flat.index("artifact_uri' = %s") < flat.index("task_id <> %s")
    assert params == ("grouped_review", _URI, "grouped:new")
    for value in ("grouped_review", _URI, "grouped:new"):
        assert value not in sql, "a value was interpolated into the statement"
    assert "notice_id" not in flat


@pytest.mark.parametrize("uri", ["", "   ", None])
def test_s8_an_empty_artifact_returns_nothing_without_querying(monkeypatch, uri):
    rec = _db(monkeypatch)
    assert human_tasks.pending_reviews_for_artifact("grouped_review", uri, excluding_task_id="x") == []
    assert rec == []


# --------------------------------------------------------------------------------------------
# S9 — the register path
# --------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_s9_the_grouped_task_reaches_the_row_payload_with_its_artifact(monkeypatch):
    sent = []

    def _post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                               json=lambda: {"task_id": "t"})
    monkeypatch.setattr(dispatch_driver.requests, "post", _post)
    monkeypatch.setattr(dispatch_driver, "mint_service_token", lambda **_: "tok", raising=False)

    class _Ctx:
        def __init__(self):
            self.state = {}

        def key(self):
            return "wf-9"

        def set(self, k, v):
            self.state[k] = v

        async def run(self, name, fn):
            return fn()

        def promise(self, name, type_hint=None):
            class _P:
                def value(self_inner):
                    async def _a():
                        return _superseded_value()
                    return _a()
            return _P()

    out = await ra_main._run_grouped_human_await(
        _Ctx(), "wf-9", SimpleNamespace(
            id="s", audience="disposition_review:SUSTAINMENT", title=None, summary=None,
            requested_by=None, completion=SimpleNamespace(claiming=False)),
        "decision", _request(artifact_uri=_URI), {}, "")
    assert out["status"] == "SUPERSEDED"
    (body,) = sent
    assert body["payload"]["artifact_uri"] == _URI

    # the route stores `payload` untouched
    stored = {}
    monkeypatch.setattr(human_tasks, "register_task",
                        lambda **kw: stored.update(kw) or {"recipients": []})
    monkeypatch.setattr(gateway, "_audit_delegate_named", lambda *a, **k: None)
    req = gateway.HumanTaskRegisterRequest(**{k: body[k] for k in (
        "kind", "task_id", "audience", "title", "summary", "requested_by", "workflow_id", "payload")})
    user = SimpleNamespace(authz_id=body["requested_by"])
    await gateway.register_human_task(req, current_user=user)
    assert stored["payload"]["artifact_uri"] == _URI
