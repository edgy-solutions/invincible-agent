"""The inbox's REST list and its Electric feed are ONE predicate, and a timeout retires the row.

A viewer saw a task whose `human_await` had timed out appear from REST `/me/human_tasks` and
vanish. Two defects met: the REST WHERE and the feed WHERE were the same predicate written twice
with no seal joining them, and a timeout wrote nothing to `human_task_projection`, so the row
stayed `pending` for ever and both surfaces offered a task nobody could act on.

  a. REST (`list_tasks_for`'s real SQL) returns exactly {pending -> viewer}. (There was a feed; the
     proxy no longer streams the inbox, ADR-0068 s8, so there is one reader.)
  b. The proxy refuses the task table and makes no upstream call.
  c. An expired human_await POSTs `/internal/human_tasks/expire` with the step's task_id and
     workflow_id; its result still reads TIMED_OUT / timed_out; a 403 changes neither.
  d. `expire_open_task` touches only pending rows, and honours the workflow_id scope.
  e. The route is declared in the gating manifest with register's auth.

Run: uv run --frozen pytest tests/routing/test_the_queue_and_the_feed_are_one_predicate.py -v
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_RA), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402

VIEWER = "viewer@example.com"
OTHER = "other@example.com"
CASE = "case-1"

_COLS = ("id", "kind", "task_id", "workflow_id", "audience", "status", "title", "summary",
         "requested_by", "subject_ref", "payload", "created_at", "workflow_service",
         "promise_name", "case_id", "recipient_id", "updated_at")

# (id, recipient, status, workflow_id)
_ROWS = [
    ("pending-viewer", VIEWER, "pending", "wf-1"),
    ("pending-other", OTHER, "pending", "wf-1"),
    ("superseded-viewer", VIEWER, "superseded", "wf-1"),
    ("resolved-viewer", VIEWER, "approved", "wf-1"),
    ("timed-out-viewer", VIEWER, "timed_out", "wf-1"),
]


def _table() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute(f"CREATE TABLE human_task_projection ({', '.join(_COLS)})")
    for n, (rid, rcp, status, wf) in enumerate(_ROWS):
        db.execute(
            f"INSERT INTO human_task_projection ({', '.join(_COLS)}) "
            f"VALUES ({', '.join('?' * len(_COLS))})",
            (rid, "workflow_ack", f"t-{rid}", wf, "aud", status, "T", "S", "r", None, "{}",
             n, None, None, CASE, rcp, 0))
    db.commit()
    return db


class _Cur:
    def __init__(self, db):
        self._db, self._c, self.rowcount = db, None, -1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self._c = self._db.execute(sql.replace("%s", "?"), tuple(params))
        self.rowcount = self._c.rowcount

    def fetchall(self):
        return self._c.fetchall()


class _Conn:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, cursor_factory=None):
        return _Cur(self._db)

    def commit(self):
        self._db.commit()


@pytest.fixture
def db(monkeypatch):
    d = _table()
    monkeypatch.setattr(ht, "_pg_connect", lambda: _Conn(d))
    return d


def test_a_REST_offers_exactly_the_viewers_open_task(db):
    """There is no feed to agree with any more (ADR-0068 s8: the proxy no longer streams the inbox);
    the REST list is the one reader, and it offers exactly {pending -> viewer}."""
    rest = {r["id"] for r in ht.list_tasks_for(VIEWER)}
    assert rest == {"pending-viewer"}, f"the viewer's open tasks are {sorted(rest)}"


def test_b_the_proxy_no_longer_streams_the_inbox(monkeypatch):
    """The proxy REFUSES the task table: no upstream call is made. The seals of the refusal are in
    tests/test_the_shape_proxy_serves_only_its_allow_list.py."""
    monkeypatch.setenv("ELECTRIC_SHAPES_FILE", str(_REPO / "policy" / "electric_shapes.yaml"))
    import asyncio

    from fastapi import HTTPException

    called = []

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, **k):
            called.append(params)
            raise AssertionError("the proxy reached upstream for the task table")

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)

    class _Req:
        class query_params:
            @staticmethod
            def multi_items():
                return [("table", "human_task_projection")]

    user = type("U", (), {"authz_id": VIEWER, "id": VIEWER, "email": VIEWER})()
    with pytest.raises(HTTPException) as e:
        asyncio.run(gateway.electric_shape_proxy(_Req(), user))
    assert e.value.status_code == 403
    assert e.value.detail["refusal"]["policy_id"] == "electric_shapes"
    assert called == []


def test_d_expire_touches_only_pending_rows_and_honours_the_workflow_scope(db):
    def status(rid):
        return db.execute("SELECT status FROM human_task_projection WHERE id = ?",
                          (rid,)).fetchone()[0]

    assert ht.expire_open_task("t-resolved-viewer", "wf-1") == 0
    assert status("resolved-viewer") == "approved", "a resolved row was overwritten"
    assert ht.expire_open_task("t-pending-viewer", "wf-OTHER") == 0
    assert status("pending-viewer") == "pending", "the workflow_id scope was ignored"
    assert ht.expire_open_task("t-pending-viewer", "wf-1") == 1
    assert status("pending-viewer") == "timed_out"
    assert ht.list_tasks_for(VIEWER) == []
    # No workflow scope given -> task_id alone.
    assert ht.expire_open_task("t-pending-other", None) == 1
    assert status("pending-other") == "timed_out"
    with pytest.raises(ValueError):
        ht.mark_task_resolved("t-x", caller_id=VIEWER, decision=ht.TIMED_OUT)


# -- c. the engine ---------------------------------------------------------------------------

restate = pytest.importorskip("restate")
import main  # noqa: E402  -- the real executor


class _Promise:
    def value(self):
        async def _v():
            return "EXPIRED"
        return _v()


class _Ctx:
    def __init__(self):
        self.state: dict = {}

    def key(self):
        return "seal-key"

    def set(self, k, v):
        self.state[k] = v

    async def run(self, name, fn):
        return fn()

    def promise(self, name, type_hint=None):
        return _Promise()

    def sleep(self, delta):
        async def _s():
            return None
        return _s()


def _definition():
    return {
        "id": "seal_expire", "name": "seal", "classification": None,
        "participants": [{"role": "initiator"}],
        "domain_stages": ["open", "closed"],
        "steps": [{
            "kind": "human_await", "id": "ack", "promise_name": "ack",
            "audience": "seal_kind:SUSTAINMENT", "subject_ref": "{subject}",
            "title": "ack {subject}", "summary": "seal fixture",
            "completion": {"mode": "single", "quorum": "any_of", "claiming": False},
            "deadline_seconds": 60,
        }],
        "observable_state": {"visible": ["domain_stages"], "internal": []},
    }


@pytest.fixture
def engine(monkeypatch):
    seen: dict = {"registered": [], "posts": [], "code": 200}

    async def _select(**arms):
        await arms["approved"]
        arms["expired"].close()
        return ("expired", None)

    class _R:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

        def json(self):
            return {"expired": 1}

    def _post(url, json=None, headers=None, timeout=None):
        seen["posts"].append((url, json))
        return _R(seen["code"])

    def _register(workflow_id, task, kind="workflow_ack", case_id=None):
        seen["registered"].append((task["id"], workflow_id))
        return {}

    monkeypatch.setattr(restate, "select", _select)
    monkeypatch.setattr(main, "_register_human_task", _register)
    monkeypatch.setattr(main, "mint_service_token", lambda: "tok")
    monkeypatch.setattr(main.requests, "post", _post)
    return seen


async def _drive():
    return await main._run_definition(
        _Ctx(), "wf-seal", _definition(), {"subject": "S-1", "authz_id": "a@x"})


@pytest.mark.asyncio
async def test_c_an_expired_await_retires_its_row_and_still_reads_timed_out(engine):
    out = await _drive()
    expire = [p for p in engine["posts"] if p[0].endswith("/internal/human_tasks/expire")]
    assert len(expire) == 1, f"posts: {engine['posts']}"
    (task_id, wf), = engine["registered"]
    assert expire[0][1] == {"task_id": task_id, "workflow_id": wf}
    assert out["outcome"] == "timed_out"


@pytest.mark.asyncio
async def test_c_a_denied_expire_changes_nothing_and_does_not_raise(engine):
    engine["code"] = 403
    out = await _drive()
    assert any(p[0].endswith("/internal/human_tasks/expire") for p in engine["posts"])
    assert out["outcome"] == "timed_out"


# -- e. the manifest -------------------------------------------------------------------------

def test_e_the_expire_route_is_declared_with_registers_auth():
    import yaml
    m = yaml.safe_load((_REPO / "docs" / "architecture" / "endpoint_gating_manifest.yaml")
                       .read_text(encoding="utf-8"))
    routes = m["services"]["gateway"]["routes"]

    def find(p):
        return next((r for r in routes if r.get("path") == p), None)

    reg, exp = find("/internal/human_tasks/register"), find("/internal/human_tasks/expire")
    assert exp is not None, "the expire route is undeclared"
    assert exp["method"] == "POST"
    assert (exp["identity"], exp["gate"], exp["class"]) == (reg["identity"], reg["gate"], reg["class"])
    assert any(getattr(r, "path", None) == "/internal/human_tasks/expire" for r in gateway.app.routes)
