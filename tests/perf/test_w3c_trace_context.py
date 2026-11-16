"""W3C Trace Context at the door, the case and the return leg (perf PR B).

`POST /ingest/events` reads `traceparent`/`tracestate`, opens `bff.ingest_event` on that trace and
hands the case runner a `trace_context`; the runner keeps it (data only) when its traceparent
parses; `GET /cases/{id}/action` answers a 200 with `traceparent` (and the stored `tracestate`)
and nothing on a refusal. The answer path joins a caller's `traceparent` too.

Doubles, as in tests/test_ingest_routes_admit_a_declared_delegate.py and
tests/test_a_case_action_record_names_who_chose_approved_released.py: a fake Restate ingress, a
fake neo4j driver, and a recording `observed_trace` / `build_trace_values` / `annotate_span`.

Run: uv run pytest tests/perf/test_w3c_trace_context.py -q
"""
from __future__ import annotations

import json
import types
from contextlib import contextmanager

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("restate")
from fastapi.testclient import TestClient  # noqa: E402
from provenance_telemetry import parse_traceparent, trace_id_for  # noqa: E402

from src.iagent import content_kinds as _ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import trace_spans as ts  # noqa: E402
from tests._can_drop_open import can_drop_open  # noqa: F401,E402
from tests.test_a_case_action_record_names_who_chose_approved_released import (  # noqa: F401,E402
    DELEGATE, OTHER_DELEGATE, _CASE, _SPEC1, _delegates, _record, _row, client_for,
)
from tests.test_cases_route import _FakeRestate, _user  # noqa: E402

TID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = "00f067aa0ba902b7"
TP = f"00-{TID}-{PARENT}-01"
TS = "vendor=a,other=b"
DOOR_SPAN = "d" * 16

_PAYLOAD = {
    "kind": "maintenance_fault", "event_id": "evt-001", "asset_id": "ASSET-1",
    "owning_tier": "tier-1", "fault": {"item": "pump", "fault_code": "F-01"},
    "picture": {"battle_condition": {"mission_essential": False,
                                     "basis": {"rule": "R1", "observed_at": "2026-10-03T00:00:00Z"}},
                "spares": [], "nearest_spare": None},
    "label": {"originator_nation": "US"},
}


# -- the parsers and the precedence -----------------------------------------------------------------

def test_request_trace_context_precedence():
    ctx = ts.request_trace_context({"traceparent": TP, "tracestate": TS, "X-Trace-Id": "legacy"})
    assert (ctx.trace_id, ctx.parent_span_id, ctx.tracestate, ctx.source) == (TID, PARENT, TS, "traceparent")
    ctx = ts.request_trace_context({"traceparent": "garbage", "tracestate": TS, "X-Trace-Id": " legacy "})
    assert (ctx.trace_id, ctx.parent_span_id, ctx.tracestate, ctx.source) == ("legacy", None, None, "x-trace-id")
    ctx = ts.request_trace_context({})
    assert ctx.source == "minted" and len(ctx.trace_id) == 32 and ctx.parent_span_id is None


def test_an_invalid_traceparent_voids_its_tracestate():
    ctx = ts.request_trace_context({"traceparent": "00-" + "0" * 32 + f"-{PARENT}-01", "tracestate": TS})
    assert ctx.source == "minted" and ctx.tracestate is None


# -- the door ---------------------------------------------------------------------------------------

@pytest.fixture
def telemetry(monkeypatch):
    """Records what the routes hand `build_trace_values`, `observed_trace` and `annotate_span`."""
    rec = {"values": [], "spans": [], "annotations": []}
    real = gateway.build_trace_values

    def values(**kw):
        rec["values"].append(kw)
        return real(**kw)

    @contextmanager
    def span(mapping, vals, *, name="operation", parent_span_id=None, **_k):
        rec["spans"].append({"name": name, "parent_span_id": parent_span_id, "values": vals})
        yield

    monkeypatch.setattr(gateway, "build_trace_values", values)
    monkeypatch.setattr(gateway, "observed_trace", span)
    monkeypatch.setattr(gateway, "annotate_span", lambda **kw: rec["annotations"].append(kw))
    monkeypatch.setattr(gateway, "current_span_id", lambda: "")  # telemetry off unless a test says
    return rec


@pytest.fixture
def events(monkeypatch, can_drop_open):
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(_ck, "by_kind", lambda kind: types.SimpleNamespace(
        kind=kind, branch="event", domain="maintenance-bridge",
        seeds_workflow="maintenance_fault", identity_field="event_id")
        if kind == "maintenance-fault-event" else None)
    monkeypatch.setattr(ist, "record_received", lambda **kw: {"id": kw["ingest_id"], "status": "received"})
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: None)
    calls: list[dict] = []

    class _Resp:
        status_code = 200

        def __init__(self, url=""):
            self.content = b'{"attached_to":null,"predecessor":null}' if url.endswith("/attach") else b""

        def raise_for_status(self):
            pass

        def json(self):
            if self.content:
                return json.loads(self.content)
            raise json.JSONDecodeError("Expecting value", "", 0)

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, **k):
            calls.append({"url": url, "json": json})
            return _Resp(url)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    user = types.SimpleNamespace(authz_id="alice@example.com", id="alice@example.com",
                                 sub="alice@example.com", email="alice@example.com",
                                 persona=None, entitled_domains=[], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", "{}")
    with TestClient(gateway.app) as c:
        def post(headers=None, payload=None):
            return c.post("/ingest/events", headers=headers or {}, json={
                "content_kind": "maintenance-fault-event", "on_behalf_of": "alice@example.com",
                "payload": payload or _PAYLOAD})
        yield post, calls
    gateway.app.dependency_overrides.clear()


def _sent(calls):
    (one,) = [c for c in calls if c["url"].endswith("/run/send")]
    return one["json"]


def test_the_door_continues_an_inbound_traceparent_telemetry_off(events, telemetry):
    post, calls = events
    assert post({"traceparent": TP, "tracestate": TS}).status_code == 200
    tc = _sent(calls)["trace_context"]
    assert tc == {"traceparent": TP, "tracestate": TS}  # no door span: the inbound parent unchanged
    (span,) = telemetry["spans"]
    assert span["name"] == "bff.ingest_event" and span["parent_span_id"] == PARENT
    assert telemetry["values"][0]["trace_id"] == TID


def test_the_door_parents_the_case_on_its_own_span_when_telemetry_is_on(events, telemetry, monkeypatch):
    monkeypatch.setattr(gateway, "current_span_id", lambda: DOOR_SPAN)
    post, calls = events
    assert post({"traceparent": TP, "tracestate": TS}).status_code == 200
    tc = _sent(calls)["trace_context"]
    assert parse_traceparent(tc["traceparent"]) == (TID, DOOR_SPAN, "01")
    assert tc["tracestate"] == TS


def test_an_invalid_traceparent_falls_back_to_x_trace_id(events, telemetry):
    post, calls = events
    assert post({"traceparent": "00-nope", "X-Trace-Id": "legacy-id"}).status_code == 200
    tc = _sent(calls)["trace_context"]
    got = parse_traceparent(tc["traceparent"])
    assert got is not None and got[0] == trace_id_for("legacy-id") and tc["tracestate"] is None
    assert telemetry["values"][0]["trace_id"] == "legacy-id"
    assert telemetry["spans"][0]["parent_span_id"] is None


def test_no_inbound_context_still_names_the_bffs_own_trace(events, telemetry):
    post, calls = events
    assert post().status_code == 200
    got = parse_traceparent(_sent(calls)["trace_context"]["traceparent"])
    assert got is not None and got[0] == telemetry["values"][0]["trace_id"]


def test_the_door_span_carries_opaque_ids_only(events, telemetry):
    post, calls = events
    assert post({"traceparent": TP}).status_code == 200
    # everything the door hands the span layer, keys and values
    handed = json.dumps([telemetry["values"], telemetry["annotations"]], default=str)
    for secret in ("ASSET-1", "tier-1", "pump", "F-01", "originator_nation", "US", "picture",
                   "battle_condition", "R1", "spares", "fault_code", "label", "asset_id"):
        assert secret not in handed, secret
    (note,) = telemetry["annotations"]
    assert set(note) == {"outcome", "content_kind", "ingest_id", "case_id"}
    assert note["outcome"] == "started" and note["case_id"] == "evt-001"
    assert set(telemetry["values"][0]) <= {"trace_id", "authz_id", "engine", "verb"}


def test_a_refusal_names_its_error_code_on_the_span(events, telemetry):
    post, _calls = events
    bad = {k: v for k, v in _PAYLOAD.items() if k != "event_id"}
    assert post(payload=bad).status_code == 422
    assert telemetry["annotations"][0]["outcome"] == "payload_missing_identity_field"


# -- the runner keeps it ----------------------------------------------------------------------------

def test_the_runner_keeps_a_valid_trace_context_and_drops_an_invalid_one():
    from agent_fleet.restate_analyst import workflow_runner as wr
    assert wr._kept_trace_context({"traceparent": TP, "tracestate": TS}) == \
        {"traceparent": TP, "tracestate": TS}
    assert wr._kept_trace_context({"traceparent": TP, "tracestate": "bad member"})["tracestate"] is None
    assert wr._kept_trace_context({"traceparent": "00-" + "0" * 32 + f"-{PARENT}-01"}) is None
    assert wr._kept_trace_context({"traceparent": TP.upper()}) is None
    assert wr._kept_trace_context(None) is None


@pytest.mark.asyncio
async def test_a_case_stores_the_kept_context_and_an_older_bff_has_none(monkeypatch, tmp_path):
    from tests import test_a_case_runs_from_trigger_to_terminal as T
    monkeypatch.setattr(T.main, "_register_human_task", lambda *a, **k: {})
    monkeypatch.setattr(T.main, "_expire_human_task", lambda wf, task: None)
    monkeypatch.setenv("CASE_TRIGGER_DIR", str(T._dump(tmp_path / "t", T._TRIGGERS)))
    monkeypatch.setenv("DECISION_TABLE_DIR", str(T._dump(tmp_path / "d", T._TABLES)))
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR", str(T._dump(tmp_path / "w", T._DEFINITIONS)))
    monkeypatch.setattr(T.wd, "load_stub_verbs", lambda: {})
    monkeypatch.setattr(T.wr, "_write_case_summary", lambda *a, **k: None)

    async def start(key, **extra):
        c = T._Cluster({(f"{key}~1", "approval_decide"): T._answer("ok")})
        req = {"trigger": "fault", "facts": T._facts(key), "provenance": T.DOOR_BLOCK, **extra}
        try:
            await T._body(T.wr.run)(c.ctx(key), req)
        finally:
            while c.sends:
                h, k, a = c.sends.pop(0)
                await T._body(h)(c.obj(k), a)
        return c.case(key)

    kept = await start("E-1", trace_context={"traceparent": TP, "tracestate": TS})
    assert kept["trace_context"] == {"traceparent": TP, "tracestate": TS}
    bad = await start("E-2", trace_context={"traceparent": "junk", "tracestate": TS})
    older = await start("E-3")
    assert "trace_context" not in bad and "trace_context" not in older


# -- the return leg ---------------------------------------------------------------------------------

_TC = {"traceparent": TP, "tracestate": TS}
_ROWS = {"c-1": [_row(_record())]}


def _delegate_get(client_for, *, case, rows=_ROWS, user=DELEGATE, headers=None):
    c = client_for(_user(user), _FakeRestate(case=case, spec1=_SPEC1), rows)
    return c.get("/cases/c-1/action", headers=headers or {})


def test_a_200_for_an_admitted_delegate_carries_the_stored_trace(client_for, telemetry):
    r = _delegate_get(client_for, case=dict(_CASE, trace_context=_TC))
    assert r.status_code == 200, r.text
    assert r.headers["traceparent"] == TP  # telemetry off: the stored parent
    assert r.headers["tracestate"] == TS
    assert telemetry["spans"][0]["name"] == "bff.case_action"
    assert telemetry["spans"][0]["parent_span_id"] == PARENT


def test_a_200_parents_the_header_on_the_return_span_when_telemetry_is_on(client_for, telemetry, monkeypatch):
    monkeypatch.setattr(gateway, "current_span_id", lambda: DOOR_SPAN)
    r = _delegate_get(client_for, case=dict(_CASE, trace_context=_TC))
    assert parse_traceparent(r.headers["traceparent"]) == (TID, DOOR_SPAN, "01")


def test_the_body_is_unchanged_by_the_trace(client_for, telemetry):
    with_tc = _delegate_get(client_for, case=dict(_CASE, trace_context=_TC)).json()
    without = _delegate_get(client_for, case=dict(_CASE)).json()
    assert with_tc == without


def test_an_inbound_traceparent_on_the_get_is_not_adopted(client_for, telemetry):
    other = f"00-{'a' * 32}-{'b' * 16}-01"
    r = _delegate_get(client_for, case=dict(_CASE, trace_context=_TC),
                      headers={"traceparent": other, "tracestate": "x=y"})
    assert r.headers["traceparent"] == TP and r.headers["tracestate"] == TS
    r = _delegate_get(client_for, case=dict(_CASE), headers={"traceparent": other})
    assert "traceparent" not in r.headers


def test_a_403_and_a_404_carry_no_trace_header(client_for, telemetry):
    case = dict(_CASE, trace_context=_TC)
    refused = _delegate_get(client_for, case=case, user=OTHER_DELEGATE)
    assert refused.status_code == 403 and refused.json()["detail"]["error"] == "not_your_case"
    missing = _delegate_get(client_for, case=case, rows={})
    assert missing.status_code == 404 and missing.json()["detail"]["error"] == "no_action_record"
    for r in (refused, missing):
        assert "traceparent" not in r.headers and "tracestate" not in r.headers


def test_control_a_case_without_a_trace_context_answers_200_with_no_header(client_for, telemetry):
    r = _delegate_get(client_for, case=dict(_CASE))
    assert r.status_code == 200
    assert "traceparent" not in r.headers and "tracestate" not in r.headers
    assert telemetry["spans"] == []


# -- the answer path ----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_traceparent_on_an_answer_request_parents_the_root_span(telemetry):
    async def stream():
        yield 1

    ctx = ts.request_trace_context({"traceparent": TP})
    out = [e async for e in gateway._traced_stream(
        stream(), trace_id=ctx.trace_id, session_id="s", authz_id="a",
        parent_span_id=ctx.parent_span_id)]
    assert out == [1]
    (span,) = telemetry["spans"]
    assert span["name"] == "bff.orchestrate" and span["parent_span_id"] == PARENT
    assert telemetry["values"][0]["trace_id"] == TID


def test_orchestrate_hands_the_parsed_context_to_the_root_span():
    import inspect
    src = inspect.getsource(gateway.orchestrate)
    assert "request_trace_context(http_request.headers)" in src
    assert "parent_span_id=_trace_ctx.parent_span_id" in src


# -- the engine site that seeds a LiteLLM generation --------------------------------------------------

def test_the_litellm_metadata_trace_is_the_requests_32_hex_id_verbatim():
    import inspect
    from agent_fleet.restate_analyst import main as ra
    code = "\n".join(l for l in inspect.getsource(ra).splitlines() if not l.lstrip().startswith("#"))
    # Seal on the call site's form: the id comes from the leaf's trace_id_for, never a hash of it.
    assert "trace_id=trace_id_for(_tid)" in code
    assert "create_trace_id(" not in code
    assert ra.trace_id_for(TID) == TID
    assert ra.trace_id_for("not-hex") == trace_id_for("not-hex") != "not-hex"
