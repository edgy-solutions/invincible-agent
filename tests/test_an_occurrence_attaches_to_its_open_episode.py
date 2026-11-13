"""An occurrence attaches to its open episode (architect, 2026-11-06).

    an episode is (asset_id, fault.item, fault_code); an occurrence is an episode opening, id =
    episode key + detected_at_ns. event_id is the occurrence id; case_id = event_id. Intake: same
    episode, case open -> attach the occurrence to it (recorded, no new case); case closed -> new
    case, `predecessor` = the closed case id.

These arms drive the REAL DOOR (`POST /ingest/events`, `gateway.ingest_event`) into the REAL RUNNER
HANDLERS (`WorkflowRunner.case/run/revise`, `CaseEpisode.attach`) through an in-process ingress that
dispatches each URL to the handler body on the `_Cluster` / `_Ctx` harness of
tests/test_a_case_runs_from_trigger_to_terminal.py. So the JOIN is tested -- the door's request
against the handler's answer -- not two doubles that agree by construction. Only the status table
(Postgres) is an in-memory stand-in, and it keeps the `sha256` the door's repeat check compares.

A case is HELD OPEN by running it as a task that parks on its approval (an unscripted answer
suspends instead of raising), as a real run does while its approver has not answered.

Each arm has a control that shares its gate and differs only in what the guard decides on.

Run: uv run --frozen pytest tests/test_an_occurrence_attaches_to_its_open_episode.py -v
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import unquote

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
yaml = pytest.importorskip("yaml")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import case_projection, gateway, ingest_status as ist  # noqa: E402
from src.iagent import content_kinds as _ck  # noqa: E402
from tests._can_drop_open import can_drop_open  # noqa: E402,F401
from tests.test_a_case_runs_from_trigger_to_terminal import (  # noqa: E402,F401
    _Cluster, _Promise, _answer, _body, _episode, _facts, policy, registered, restate, wr,
)

pytestmark = pytest.mark.usefixtures("can_drop_open")

_KIND = "episode-event"


class _Ingress:
    """The Restate ingress, in process: a URL goes to the handler body it names."""

    def __init__(self, cluster):
        self.cluster = cluster
        self.calls: list[tuple[str, dict | None]] = []
        self.tasks: list = []
        self.parked: asyncio.Future | None = None

    def urls(self, suffix):
        return [u for u, _ in self.calls if u.endswith(suffix)]

    async def _flush(self):
        while self.cluster.sends:
            h, k, a = self.cluster.sends.pop(0)
            await _body(h)(self.cluster.obj(k), a)

    async def _run(self, key, req):
        try:
            await _body(wr.run)(self.cluster.ctx(key), req)
        except Exception:  # noqa: BLE001 -- a /send's failure is the runner's, not the door's
            pass
        finally:
            await self._flush()

    async def dispatch(self, url, body):
        self.calls.append((url, body))
        _, _, rest = url.partition("/restate-ingress/")
        service, key, handler = rest.split("/")
        key = unquote(key)
        try:
            if handler == "case":
                out = await _body(wr.case)(self.cluster.ctx(key), None)
            elif handler == "attach":
                out = await _body(wr.attach)(self.cluster.obj(key), body)
            elif handler == "revise":
                out = await _body(wr.revise)(self.cluster.ctx(key), body)
            else:
                raise AssertionError(f"unrouted {url}")
        except restate.TerminalError as exc:
            return httpx.Response(exc.status_code, content=json.dumps(
                {"message": str(exc)}).encode(), request=httpx.Request("POST", url))
        finally:
            await self._flush()
        content = b"" if out is None else json.dumps(out).encode()
        return httpx.Response(200, content=content, request=httpx.Request("POST", url))

    async def run_send(self, url, body):
        self.calls.append((url, body))
        key = unquote(url.split("/WorkflowRunner/")[1].split("/")[0])
        self.parked = asyncio.get_running_loop().create_future()
        task = asyncio.ensure_future(self._run(key, body))
        self.tasks.append(task)
        await asyncio.wait({task, self.parked}, return_when=asyncio.FIRST_COMPLETED)
        # A one-way send the run made before it parked is delivered now: Restate does not hold a
        # send until its sender returns.
        await self._flush()
        return httpx.Response(202, content=b'{"invocationId":"inv"}',
                              request=httpx.Request("POST", url))


@pytest.fixture
def world(monkeypatch, policy, registered):
    """Door + runner + status table wired together; `world.post(facts)` is the producer."""
    cluster = _Cluster()
    ingress = _Ingress(cluster)

    async def _value(self):
        answer = self.ctx.cluster.answers.get((self.ctx._key, self.name))
        if answer is None:  # unscripted: the approver has not answered -- the run PARKS
            if ingress.parked is not None and not ingress.parked.done():
                ingress.parked.set_result(None)
            await asyncio.Event().wait()
        return answer
    monkeypatch.setattr(_Promise, "value", lambda self: _value(self))

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, **k):
            url = url.replace(gateway._RESTATE_INGRESS_URL, "http://x/restate-ingress")
            if url.endswith("/run/send"):
                return await ingress.run_send(url, json)
            return await ingress.dispatch(url, json)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)

    rows: dict = {}
    monkeypatch.setattr(ist, "get_row", lambda ingest_id: rows.get(ingest_id))

    def _received(**kw):
        rows[kw["ingest_id"]] = {"id": kw["ingest_id"], "sha256": kw["sha256"], "status": "received"}
        return rows[kw["ingest_id"]]
    monkeypatch.setattr(ist, "record_received", _received)
    monkeypatch.setattr(ist, "update_status", lambda ingest_id, status, **kw: rows[ingest_id].update(
        status=status, **kw))

    import types
    monkeypatch.setattr(_ck, "by_kind", lambda kind: types.SimpleNamespace(
        kind=kind, branch="event", domain=None, seeds_workflow="fault",
        identity_field="event_id") if kind == _KIND else None)

    user = type("U", (), {"authz_id": "alice@example.com", "id": "alice@example.com",
                          "sub": "alice@example.com", "email": "alice@example.com",
                          "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as client:
        class World:
            pass
        w = World()
        w.cluster, w.ingress, w.rows = cluster, ingress, rows

        def post(facts):
            return client.post("/ingest/events", json={
                "content_kind": _KIND, "on_behalf_of": "alice@example.com", "payload": facts})
        w.post = post
        yield w
    gateway.app.dependency_overrides.clear()


def _approve(world, *event_ids):
    for e in event_ids:
        world.cluster.answers[(f"{e}~1", "approval_decide")] = _answer("ok")


def _occurrences(world, facts, holder):
    return world.cluster.obj(_episode(facts)).state.get(f"occurrences:{holder}")


def test_A_REFILE_AFTER_CLOSE_OPENS_A_NEW_CASE_NAMING_ITS_PREDECESSOR(world):
    _approve(world, "E-1", "E-2")
    first = world.post(_facts("E-1"))
    assert first.status_code == 200, first.text
    assert world.cluster.case("E-1")["terminal"] == "done", world.cluster.case("E-1")
    assert world.cluster.case("E-1")["predecessor"] is None

    second = world.post(_facts("E-2"))
    assert second.status_code == 200, second.text
    assert second.json()["workflow"] == {"case_id": "E-2", "started": True}, second.json()
    case = world.cluster.case("E-2")
    assert case["predecessor"] == "E-1", case
    assert case["episode"] == _episode(_facts("E-2"))
    served = case_projection.project_workflow_case(case, {}, [])
    assert (served["predecessor"], served["episode_id"], served["stage"]) == (
        "E-1", case["episode"], "closed")
    # nothing was attached: the first case was closed, so this occurrence is its own case
    assert _occurrences(world, _facts(), "E-1") is None


def test_A_REFILE_WHILE_OPEN_ATTACHES_AND_OPENS_NO_CASE(world):
    first = world.post(_facts("E-1"))
    assert first.status_code == 200, first.text
    assert world.cluster.obj(_episode(_facts())).state["open"] == "E-1"  # E-1 is parked, open

    second = world.post(_facts("E-2"))
    assert second.status_code == 200, second.text
    assert second.json()["workflow"] == {"case_id": "E-1", "started": False, "attached": True}
    sends = [u for u in world.ingress.urls("/run/send")]
    assert len(sends) == 1 and "/E-1/" in sends[0], sends       # none for E-2
    assert "case" not in world.cluster.ctx("E-2").state
    assert [o["event_id"] for o in _occurrences(world, _facts(), "E-1")] == ["E-2"]
    row = world.rows[second.json()["ingest_id"]]
    assert row["case_id"] == "E-1" and "attached to open case E-1" in row["detail"], row


def test_A_REFILE_WHILE_OPEN_CONTROL_ANOTHER_EPISODE_OPENS_A_CASE(world):
    assert world.post(_facts("E-1")).status_code == 200
    other = dict(_facts("E-3"), fault={"code": "F13"})
    assert _episode(other) != _episode(_facts("E-1"))
    out = world.post(other)
    assert out.status_code == 200, out.text
    assert out.json()["workflow"] == {"case_id": "E-3", "started": True}, out.json()
    assert world.cluster.case("E-3") is not None
    assert _occurrences(world, _facts(), "E-1") is None


def test_THE_SAME_OCCURRENCE_TWICE_IS_IDEMPOTENT(world):
    one = world.post(_facts("E-1"))
    two = world.post(_facts("E-1"))
    assert one.status_code == two.status_code == 200, (one.text, two.text)
    assert two.json()["workflow"] == {"case_id": "E-1", "started": False}, two.json()
    assert len(world.ingress.urls("/run/send")) == 1       # one case
    assert world.ingress.urls("/revise") == []             # and no revision
    assert world.cluster.obj(_episode(_facts())).state.get("revision") is not None

    # while attached: the same E-2 twice is one occurrence entry
    assert world.post(_facts("E-2")).json()["workflow"]["attached"] is True
    again = world.post(_facts("E-2"))
    assert again.json()["workflow"]["attached"] is True, again.json()
    assert [o["event_id"] for o in _occurrences(world, _facts(), "E-1")] == ["E-2"]
    assert len(world.ingress.urls("/run/send")) == 1


def test_THE_SAME_OCCURRENCE_TWICE_CONTROL_DIFFERENT_BYTES_STILL_REVISE(world):
    assert world.post(_facts("E-1")).status_code == 200
    changed = world.post(_facts("E-1", note="a newer picture"))
    assert changed.status_code == 200, changed.text
    assert len(world.ingress.urls("/revise")) == 1
    assert changed.json()["rev"] == 2, changed.json()
    assert len(world.ingress.urls("/run/send")) == 1


@pytest.mark.asyncio
async def test_ATTACH_RECORDS_ON_THE_HOLDER_NEVER_A_CASE_AS_ITS_OWN_OCCURRENCE_AND_REFUSES_BLANK():
    c = _Cluster()
    o = c.obj("ep-x")
    attach = _body(wr.attach)
    assert await attach(o, {"event_id": "E-1"}) == {"attached_to": None, "predecessor": None}
    await _body(wr.claim)(o, {"case_id": "E-1"})
    assert await attach(o, {"event_id": "E-1"}) == {"attached_to": "E-1", "predecessor": None}
    assert "occurrences:E-1" not in o.state                  # not its own occurrence
    await attach(o, {"event_id": "E-2", "received_at": "t", "ingest_id": "i"})
    await attach(o, {"event_id": "E-2", "received_at": "t", "ingest_id": "i"})
    assert o.state["occurrences:E-1"] == [
        {"event_id": "E-2", "received_at": "t", "ingest_id": "i"}]
    await _body(wr.release)(o, {"case_id": "E-1"})
    assert o.state["last_closed"] == "E-1" and len(o.state["occurrences:E-1"]) == 1
    assert await attach(o, {"event_id": "E-3"}) == {"attached_to": None, "predecessor": "E-1"}
    for bad in (None, "", "  ", 7):
        with pytest.raises(restate.TerminalError) as exc:
            await attach(o, {"event_id": bad})
        assert exc.value.status_code == 400


@pytest.mark.parametrize("empty", [True, False], ids=["empty-200", "control-real-answer"])
def test_AN_EMPTY_ATTACH_ANSWER_IS_RUNNER_UNAVAILABLE_NEVER_A_GUESSED_NEW_CASE(world, monkeypatch, empty):
    real = world.ingress.dispatch

    async def _dispatch(url, body):
        if empty and url.endswith("/attach"):
            world.ingress.calls.append((url, body))
            return httpx.Response(200, content=b"", request=httpx.Request("POST", url))
        return await real(url, body)
    monkeypatch.setattr(world.ingress, "dispatch", _dispatch)

    out = world.post(_facts("E-1"))
    assert world.ingress.urls("/attach"), world.ingress.calls      # both arms reach the guard
    if empty:
        assert out.status_code == 503, out.text
        assert out.json()["detail"]["error"] == "runner_unavailable", out.json()
        assert world.ingress.urls("/run/send") == []
    else:
        assert out.status_code == 200, out.text
        assert len(world.ingress.urls("/run/send")) == 1


def test_AN_ATTACHED_OCCURRENCE_WHOSE_STATUS_ROW_FAILS_IS_STATUS_UNAVAILABLE(world, monkeypatch):
    assert world.post(_facts("E-1")).status_code == 200
    def _down(*a, **k):
        raise ist.IngestStatusConfigError("PROJECTOR_POSTGRES_DSN is unset")
    monkeypatch.setattr(ist, "update_status", _down)
    out = world.post(_facts("E-2"))
    assert out.status_code == 503, out.text
    assert out.json()["detail"]["error"] == "status_unavailable", out.json()
    # the occurrence is on the episode already; a resend re-attaches it once, never twice
    assert [o["event_id"] for o in _occurrences(world, _facts(), "E-1")] == ["E-2"]
    assert len(world.ingress.urls("/run/send")) == 1


# ── open means "not at a terminal stage", never "a workflow is alive" (architect, 2026-11-10) ──
#   The walk's occurrence attached to October's case, released on 10-29 and still held open by
#   an instance waiting on a step after its release. "A released case's lingering workflow is
#   terminated at release; a test with a released-but-running case proves a new occurrence opens
#   a new case with predecessor." The control for both arms is
#   test_A_REFILE_WHILE_OPEN_ATTACHES_AND_OPENS_NO_CASE: a case parked BEFORE its decision holds.

def _route_lo_to_a_decision_then_an_await(policy):
    """`lo` routes to a definition shaped like October's: an emit that disposes, then a
    signal_await nobody answers (unscripted, so it parks)."""
    (policy / "workflows" / "sends.yaml").write_text(yaml.safe_dump({
        "id": "sends", "name": "sends", "steps": [
            {"kind": "emit", "id": "send", "channel": "notice", "disposes": "sent",
             "template": {"event_id": "{trigger.event_id}"}},
            {"kind": "signal_await", "id": "ack", "signal": "ack", "audience": "ops:{trigger.tier}",
             "accepts": ["acked"]}]}), encoding="utf-8")
    (policy / "decisions" / "sends_chain.yaml").write_text(yaml.safe_dump({
        "decision": "sends_chain", "after": "sends", "matches": ["outcome"],
        "domain": {"outcome": ["sent"]}, "terminals": ["closed"],
        "rows": [{"when": {"outcome": "sent"}, "then": "closed"}]}), encoding="utf-8")
    (policy / "decisions" / "sel.yaml").write_text(yaml.safe_dump({
        "decision": "sel", "matches": ["level"], "domain": {"level": ["hi", "lo"]},
        "rows": [{"when": {"level": "hi"}, "then": "review"},
                 {"when": {"level": "lo"}, "then": "sends"}]}), encoding="utf-8")


def _opens_a_new_case_after(world, first):
    second = world.post(_facts("E-2"))
    assert second.status_code == 200, second.text
    assert second.json()["workflow"] == {"case_id": "E-2", "started": True}, second.json()
    assert world.cluster.case("E-2")["predecessor"] == first, world.cluster.case("E-2")
    assert _occurrences(world, _facts(), first) is None


def test_A_DECIDED_CASE_WITH_STEPS_LEFT_ENDS_ITS_WORKFLOW_AND_FREES_ITS_EPISODE(world, policy):
    _route_lo_to_a_decision_then_an_await(policy)
    _approve(world, "E-2")
    assert world.post(_facts("E-1", level="lo")).status_code == 200
    case = world.cluster.case("E-1")
    assert case["terminal"] == "closed", case
    assert case_projection.project_workflow_case(case, {}, [])["stage"] == "closed"
    # the step after the decision never began: no audience, no vocabulary, no park
    assert not [k for k in world.cluster.ctx("E-1~1").state if k.split(":")[-1] == "ack"]
    assert world.cluster.ctx("E-1~1").state.get("outbox:notice"), "the decision was sent"
    _opens_a_new_case_after(world, "E-1")


def test_A_CASE_AT_ITS_TERMINAL_FREES_ITS_EPISODE_WHILE_ITS_RUN_IS_STILL_WRITING(world, monkeypatch):
    real = wr._summarize

    async def _summarize(ctx, case, **kw):
        if case["case_id"] == "E-1":  # the summary write hangs; the run is alive past its terminal
            if world.ingress.parked is not None and not world.ingress.parked.done():
                world.ingress.parked.set_result(None)
            await asyncio.Event().wait()
        return await real(ctx, case, **kw)
    monkeypatch.setattr(wr, "_summarize", _summarize)
    _approve(world, "E-1", "E-2")
    assert world.post(_facts("E-1")).status_code == 200
    assert world.cluster.case("E-1")["terminal"] == "done"
    assert not world.ingress.tasks[0].done()  # E-1's run has not returned
    _opens_a_new_case_after(world, "E-1")


# ── episode_id is the source system's (architect, 2026-11-07) ────────────────────────────────
#   "An event carries `episode_id` as a declared field owned by the detector; the case serves
#   that. Our derived `ep-` key is used only when the event carries none, and then the case says
#   `episode_id_source: derived`. We don't mint identity for someone else's episode."

@pytest.mark.parametrize("carried, want_source", [
    ("OD-EP-9", "event"), (None, "derived"), ("", "derived"), ("  ", "derived")],
    ids=["carried", "control-absent", "control-blank", "control-whitespace"])
def test_THE_CASE_SERVES_THE_SOURCE_SYSTEMS_EPISODE_ID_AND_DERIVES_ONLY_WITHOUT_ONE(
        world, carried, want_source):
    _approve(world, "E-1")
    facts = _facts("E-1") if carried is None else _facts("E-1", source_episode=carried)
    assert world.post(facts).status_code == 200
    case = world.cluster.case("E-1")
    assert case["episode"] == _episode(facts) and case["episode"].startswith("ep-")
    want = carried if want_source == "event" else case["episode"]
    assert (case["episode_id"], case["episode_id_source"]) == (want, want_source), case
    served = case_projection.project_workflow_case(case, {}, [])
    assert (served["episode_id"], served["episode_id_source"]) == (want, want_source), served


def test_A_CASE_OPENED_BEFORE_THE_STAMP_IS_SERVED_ITS_DERIVED_KEY_AND_SAYS_SO():
    old = {"case_id": "E-0", "episode": "ep-abc", "terminal": None, "state": None}
    served = case_projection.project_workflow_case(old, {}, [])
    assert (served["episode_id"], served["episode_id_source"]) == ("ep-abc", "derived")
    none = case_projection.project_workflow_case(dict(old, episode=None), {}, [])
    assert (none["episode_id"], none["episode_id_source"]) == (None, None)
