"""The maintenance case's ActionRecord is WRITTEN at `released` (ADR-0041 §8.1; 2026-10-09).

Before this the record was emitted into the instance's Restate state and read by nobody: no
workflow produced a case-linked artifact, so the runner's `seeded_by` stamp matched nothing. The
runner now reads the `maintenance_action` outbox at `released` and POSTs each record to
`/internal/cases/{case_id}/action-record` as `svc:case-runner`, BEFORE the stamp.

Arms:
  route   POST /internal/cases/{case_id}/action-record: caller gate, each 422, the case_id check
          before any write, what lands on the node, idempotence on the derived id.
  runner  a maintenance case reaching `released` POSTs the record (case_id == the case) before
          the stamp; `tier_refused` writes none; `on_behalf_of` is the delegate, else the approver.

Run: uv run pytest tests/test_the_runner_writes_the_action_record_at_released.py -v
"""
from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("restate")
from fastapi.testclient import TestClient  # noqa: E402

import requests  # noqa: E402
import restate  # noqa: E402
from src.iagent import gateway  # noqa: E402
from tests.test_a_case_runs_from_trigger_to_terminal import (  # noqa: E402
    DOOR_BLOCK, _answer, _body, _Cluster, wr)
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: E402,F401
    ACK, DECIDE, TRIGGER, _declared_walk_double, _event, _real_policy, registered)

import spo_step_executor as ex  # noqa: E402 -- on sys.path once the harness above is imported

DELEGATE = "svc:openddil"
PERSON = "alice@example.com"
RUNNER = gateway._CASE_RUNNER_SERVICE_AUTHZ_ID
_MAP = json.dumps({DELEGATE: ["operator.atlantia@example.com"]})


@pytest.fixture(autouse=True)
def _delegates(monkeypatch):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", _MAP)
    monkeypatch.setenv("CORTEX_BFF_URL", "http://bff:1")


# =============================================================================================
# route
# =============================================================================================

class _Tx:
    def __init__(self, store):
        self.store = store

    def run(self, cypher, **params):
        self.store.tx_calls.append((cypher, params))
        if "MERGE (a:AnswerArtifact {id: $id})" in cypher:
            self.store.ids.add(params["id"])

        class _O:
            def single(_s):
                return {"watermark": 1}

            def __iter__(_s):
                return iter(())
        return _O()


class _Session:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.store.reads.append((cypher, params))
        n = 1 if params.get("id") in self.store.ids else 0

        class _O:
            def single(_s):
                return {"n": n}
        return _O()

    def execute_write(self, fn, *args):
        return fn(_Tx(self.store), *args)


class _Store:
    """A driver double that remembers which artifact ids exist, so idempotence is observable."""

    def __init__(self):
        self.ids, self.tx_calls, self.reads = set(), [], []

    def session(self):
        return _Session(self)


def _login(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": authz_id, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


@pytest.fixture
def api(monkeypatch):
    store = _Store()
    monkeypatch.setattr(gateway, "neo4j_driver", store)
    _login(RUNNER)
    yield TestClient(gateway.app), store
    gateway.app.dependency_overrides.clear()


def _record(case_id="EV-1", action_id="EV-1~2"):
    return {"action_id": action_id, "event_id": "EV-1", "asset_id": "AST-7",
            "provenance": {"case_id": case_id, "workflow_instance_id": action_id}}


def _body_of(case_id="EV-1", **over):
    b = {"record": _record(case_id), "seeded_by": DELEGATE, "on_behalf_of": PERSON}
    b.update(over)
    return b


def _node_statements(store):
    return [c for c, _p in store.tx_calls]


def test_a_caller_that_is_not_the_case_runner_gets_403_and_nothing_is_read_or_written(api):
    c, store = api
    _login(DELEGATE)
    r = c.post("/internal/cases/EV-1/action-record", json=_body_of())
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_case_runner"
    assert store.reads == [] and store.tx_calls == []


@pytest.mark.parametrize("over,error", [
    ({"on_behalf_of": "  "}, "on_behalf_of_required"),
    ({"seeded_by": PERSON}, "seeded_by_not_a_declared_delegate"),
    ({"record": {**_record(), "action_id": "  "}}, "action_id_required"),
    ({"record": {k: v for k, v in _record().items() if k != "action_id"}}, "action_id_required"),
])
def test_each_422_and_none_of_them_writes(api, over, error):
    c, store = api
    r = c.post("/internal/cases/EV-1/action-record", json=_body_of(**over))
    assert r.status_code == 422 and r.json()["detail"]["error"] == error, r.text
    assert store.reads == [] and store.tx_calls == []


def test_a_blank_on_behalf_of_is_422_by_absence_too(api):
    c, _ = api
    b = _body_of()
    del b["on_behalf_of"]
    assert c.post("/internal/cases/EV-1/action-record", json=b).status_code == 422


@pytest.mark.parametrize("prov", [{"case_id": "OTHER"}, {}, None, "EV-1"])
def test_a_record_naming_another_case_is_refused_with_no_write(api, prov):
    c, store = api
    rec = _record()
    if prov is None:
        del rec["provenance"]
    else:
        rec["provenance"] = prov
    r = c.post("/internal/cases/EV-1/action-record", json=_body_of(record=rec))
    assert r.status_code == 422 and r.json()["detail"]["error"] == "case_id_mismatch", r.text
    assert store.reads == [] and store.tx_calls == [] and store.ids == set()


def test_the_write_carries_case_id_seeded_by_kind_and_the_owner(api):
    c, store = api
    r = c.post("/internal/cases/EV-1/action-record", json=_body_of())
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["case_id"] == "EV-1" and out["written"] is True
    assert out["artifact_id"] == gateway.action_record_artifact_id("EV-1", "EV-1~2")
    by_cypher = {c: p for c, p in store.tx_calls}
    assert by_cypher["MATCH (a:AnswerArtifact {id: $id}) SET a.case_id = $case_id"] == {
        "id": out["artifact_id"], "case_id": "EV-1"}
    assert by_cypher["MATCH (a:AnswerArtifact {id: $id}) SET a.seeded_by = $seeded_by"] == {
        "id": out["artifact_id"], "seeded_by": DELEGATE}
    merge = next(p for c, p in store.tx_calls if "MERGE (a:AnswerArtifact {id: $id})" in c)
    assert merge["kind"] == "maintenance-action-record" and merge["status"] == "complete"
    assert json.loads(merge["rendered_output"])["record"] == _record()
    owner = next(p for c, p in store.tx_calls if "PRODUCED_FOR" in c)
    assert owner["user_id"] == PERSON
    actor = next(p for c, p in store.tx_calls if "PRODUCED_BY" in c)
    assert actor["actor_id"] == RUNNER


def test_without_seeded_by_the_node_carries_none(api):
    c, store = api
    r = c.post("/internal/cases/EV-1/action-record", json=_body_of(seeded_by=None))
    assert r.status_code == 200 and r.json()["written"] is True
    assert not any("seeded_by" in cy for cy in _node_statements(store))
    assert any("a.case_id" in cy for cy in _node_statements(store))


def test_a_retry_writes_nothing_and_reports_written_false(api):
    c, store = api
    first = c.post("/internal/cases/EV-1/action-record", json=_body_of()).json()
    n_writes = len(store.tx_calls)
    again = c.post("/internal/cases/EV-1/action-record", json=_body_of()).json()
    assert (first["written"], again["written"]) == (True, False)
    assert again["artifact_id"] == first["artifact_id"]
    assert len(store.tx_calls) == n_writes, "the retry wrote again"


def test_the_id_derives_from_the_case_and_the_action_and_nothing_random():
    f = gateway.action_record_artifact_id
    assert f("EV-1", "EV-1~2") == f("EV-1", "EV-1~2")
    assert len({f("EV-1", "EV-1~2"), f("EV-1", "EV-1~3"), f("EV-2", "EV-1~2")}) == 3


# =============================================================================================
# runner
# =============================================================================================

class _Resp:
    def __init__(self, status=200):
        self.status_code = status


@pytest.fixture
def posts(monkeypatch, _declared_walk_double):
    """Every POST the runner makes to the BFF's internal routes, in order. The maintenance walk's
    own declared-query POST (installed by `_declared_walk_double`) keeps answering as before."""
    seen: list = []
    walk = requests.post

    def _post(url, json=None, headers=None, timeout=None, **kw):
        if "/internal/cases/" in url:
            seen.append((url, json, headers))
            return _Resp()
        return walk(url, json=json, headers=headers, timeout=timeout, **kw)
    monkeypatch.setattr(requests, "post", _post)
    return seen


class _SeededCluster(_Cluster):
    async def start(self, key, trigger, facts, provenance=DOOR_BLOCK, seeded_by=None):
        req = {"trigger": trigger, "facts": facts, "provenance": provenance}
        if seeded_by is not None:
            req["seeded_by"] = seeded_by
        try:
            return await _body(wr.run)(self.ctx(key), req)
        finally:
            while self.sends:
                h, k, a = self.sends.pop(0)
                await _body(h)(self.obj(k), a)


async def _drive(answers, seeded_by=None, key="EV-1"):
    scripted = {}
    for n, a in enumerate(answers, start=1):
        if a is None:
            continue
        promise, verb, who = (*a, "m@x") if len(a) == 2 else a
        scripted[(f"{key}~{n}", promise)] = _answer(verb, who, f"because {n}")
    c = _SeededCluster(scripted)
    out = await c.start(key, TRIGGER, copy.deepcopy(_event(key)), seeded_by=seeded_by)
    return out, c


def _kinds(posts):
    return [u.rsplit("/", 1)[1] for u, _j, _h in posts]


RELEASED = [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")]
REFUSED_THEN_RELEASED = [(DECIDE, "replace_after_resupply"), (ACK, "tier_refused", "tier@x"),
                         (DECIDE, "defer_with_restriction"), (ACK, "released", "tier@x")]


@pytest.mark.asyncio
async def test_a_released_case_posts_its_record_before_the_stamp(registered, posts):
    out, _ = await _drive(RELEASED, seeded_by=DELEGATE)
    assert out["status"] == "CLOSED"
    assert _kinds(posts) == ["action-record", "seeded-by"], _kinds(posts)
    url, body, headers = posts[0]
    assert url == "http://bff:1/internal/cases/EV-1/action-record"
    assert body["record"]["provenance"]["case_id"] == "EV-1"
    assert body["record"]["action_id"] == body["record"]["provenance"]["workflow_instance_id"]
    assert body["seeded_by"] == DELEGATE and body["on_behalf_of"] == DELEGATE
    assert headers == {"Authorization": "Bearer case-runner-token"}
    assert posts[1][1] == {"seeded_by": DELEGATE}


@pytest.mark.asyncio
async def test_a_tier_refusal_writes_no_record(registered, posts):
    await _drive(REFUSED_THEN_RELEASED, seeded_by=DELEGATE)
    records = [j for u, j, _h in posts if u.endswith("/action-record")]
    assert len(records) == 1, [r["record"]["action_id"] for r in records]
    # the refused instance emitted a record too (the emit precedes the ack); it is not written
    assert records[0]["record"]["action_id"] == "EV-1~4", records[0]["record"]["action_id"]
    assert _kinds(posts) == ["action-record", "seeded-by"]


@pytest.mark.asyncio
async def test_a_person_seeded_case_is_written_on_behalf_of_the_last_approver(registered, posts):
    await _drive([(DECIDE, "replace_after_resupply", "boss@x"), (ACK, "released", "tier@x")])
    assert _kinds(posts) == ["action-record"], "no seeded_by, so no stamp"
    body = posts[0][1]
    assert body["seeded_by"] is None and body["on_behalf_of"] == "boss@x", body


@pytest.mark.asyncio
async def test_the_write_runs_once_per_record_in_its_own_journal_step(registered, posts):
    _, c = await _drive(RELEASED, seeded_by=DELEGATE)
    runs = c.ctx("EV-1").runs
    assert [r for r in runs if r.startswith("write_action_record")] == ["write_action_record_2_1"]
    assert runs.index("write_action_record_2_1") < runs.index("stamp_seeded_by_2"), runs


@pytest.mark.asyncio
async def test_a_refused_write_fails_the_case_visibly(registered, monkeypatch):
    monkeypatch.setattr(ex, "mint_case_runner_token", lambda **kw: "t")
    walk = requests.post
    monkeypatch.setattr(requests, "post", lambda url, **kw: (
        _Resp(403) if url.endswith("/action-record") else walk(url, **kw)))
    with pytest.raises(restate.TerminalError) as exc:
        await _drive(RELEASED, seeded_by=DELEGATE)
    assert exc.value.status_code == 502
