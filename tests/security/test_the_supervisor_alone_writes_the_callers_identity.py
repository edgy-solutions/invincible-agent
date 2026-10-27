"""THE SUPERVISOR ALONE WRITES THE CALLER'S IDENTITY on a specialist dispatch.

RULING (architect, 2026-10-10, Q3): "Not acceptable as the final state, acceptable as the
interim. Rule: the supervisor is the only writer of user_email/entitled_domains on a specialist
dispatch, and it derives both from the verified token, never from the request body. Seal that
in a test (body-asserted user_email is ignored). The user token reaching specialists is Lane 1's
follow-up; it does not block #32."

THREE HOPS, ONE RULE, EACH DRIVEN THROUGH THE REAL CODE (the artifact is the value that reaches
the next hop, not the source that builds it):

  1. GATEWAY -- the real `orchestrate` route through a TestClient (so FastAPI's own body parse
     runs). A body carrying `user_email`, `entitled_domains` and `user_id` set to mallory's values
     (the request model declares none of them) must reach `generate_dagster_stream` with
     alice's `authz_id` and the entitlement-derived domains, and "mallory"/"FINANCE" must appear
     nowhere in what it received. CONTROL: the same request without the extra keys records
     identical identity kwargs.
  2. SUPERVISOR, SPECIALIST PATH -- the real `execute_subtask`, the matched-predicate branch,
     the specialist HTTP POST captured. THE ONLY THING `execute_subtask` READS FROM `task_def`
     IS `task_def.get("sub_query")` (a string, used as the routing text and as the payload's
     `user_query`); no nested dict of `task_def` reaches the payload builder. The test plants
     mallory's identity at the top level of `task_def` and inside every nested dict a builder
     could plausibly read (`params`, `slots`, `payload`, `config`, `produced_for`).
     CONTROL: a `task_def` without them posts identical values.
  3. SUPERVISOR, FALLBACK PATH -- the real `_call_engine_a_fallback`, the same. Its only
     task-derived inputs are `sub_query`, `rejected_predicate` (read: `verb_iri`) and
     `telemetry` (read: `subject_uri`, `subject_instance_id`, `subject_instance_label`); mallory
     is planted at the top level and nested in each.

RESULT ON TODAY'S CODE: all green (no task_def value reaches either payload's identity keys).
The mutants named in the report prove each arm can go red.

Run: uv run --frozen pytest tests/security/test_the_supervisor_alone_writes_the_callers_identity.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from src.iagent import gateway  # noqa: E402
from src.iagent.auth import User  # noqa: E402
from iagent.authz.topaz_client import EntitlementCell, Entitlements  # noqa: E402  (the module src.iagent.auth itself imports)

ALICE = "alice@example.com"
MALLORY = "mallory@example.com"

#: The identity keys a body or a task could try to assert.
_ASSERTED = {"user_email": MALLORY, "entitled_domains": ["FINANCE"], "user_id": "mallory"}


# ── 1. the gateway ────────────────────────────────────────────────────────────────────────────

def _alice() -> User:
    cell = EntitlementCell(persona="SUSTAINMENT_LEAD", domain="SUSTAINMENT")
    return User(id="u-alice", authz_id=ALICE, entitlement_source="topaz",
                entitlements=Entitlements(cells=[cell], default=cell))


@pytest.fixture
def stream_kwargs(monkeypatch):
    """Replaces `generate_dagster_stream` with a recorder (an empty async generator, so the
    StreamingResponse the route returns can be consumed)."""
    seen: list = []

    def _stub(request, **kw):
        seen.append({"request": request, **kw})

        async def _gen():
            return
            yield  # pragma: no cover

        return _gen()

    monkeypatch.setattr(gateway, "generate_dagster_stream", _stub)
    gateway.app.dependency_overrides[gateway.get_current_user] = _alice
    yield seen
    gateway.app.dependency_overrides.clear()


def _orchestrate(body_extra):
    body = {"message": "what is the status", "session_id": "s-q3", **body_extra}
    resp = TestClient(gateway.app).post("/orchestrate", json=body)
    assert resp.status_code == 200, resp.text


def _identity(kw):
    return {k: kw[k] for k in ("user_email", "entitled_domains", "user_id")}


def test_a_body_asserted_identity_is_ignored_by_the_gateway(stream_kwargs):
    _orchestrate({})
    [control] = stream_kwargs
    stream_kwargs.clear()
    _orchestrate(dict(_ASSERTED))
    [got] = stream_kwargs
    assert got["user_email"] == ALICE, got["user_email"]
    assert got["entitled_domains"] == ["SUSTAINMENT"], got["entitled_domains"]
    assert got["user_id"] == "u-alice", got["user_id"]
    # nowhere in anything the stream was handed, request model included
    blob = json.dumps({k: (v.model_dump() if hasattr(v, "model_dump") else v)
                       for k, v in got.items()}, default=str)
    assert "mallory" not in blob and "FINANCE" not in blob, blob
    # CONTROL: the same request without the extra keys records identical identity kwargs.
    assert _identity(got) == _identity(control)
    assert got["entitled_domains"] == control["entitled_domains"] == ["SUSTAINMENT"]


# ── 2. the supervisor, specialist path ────────────────────────────────────────────────────────

sup = pytest.importorskip("iagent.defs.dynamic_supervisor")

_ENDPOINT = "http://iagent-engine-x.sandbox.svc:8000/measure/thing"


class _Cfg:
    user_persona = "SUSTAINMENT_LEAD"
    entitled_domains = ["SUSTAINMENT"]
    user_email = ALICE
    user_id = "u-alice"
    trace_id = ""
    session_id = ""
    user_query = "what is the status"
    entity_refs = None
    pre_resolved = None
    slots = None
    spoken_slot = ""
    spoken_answer = ""
    bound_slots = None
    predicate_fallback_score_threshold = 0.5


class _Resp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"final_answer": "ok", "output_uri": "http://x#AgentResponse", "data": "",
                "sources": []}


@pytest.fixture
def posted(monkeypatch):
    sent: list = []

    def _post(url, json=None, headers=None, timeout=None):  # noqa: A002
        sent.append({"url": url, "body": json})
        return _Resp()

    monkeypatch.setattr(sup.requests, "post", _post)
    return sent


def _ctx():
    ctx = mock.MagicMock()
    ctx.run_id = "run-q3"
    return ctx


def _poisoned(extra=None):
    """A task_def carrying mallory at the top level and inside every nested dict."""
    nested = {k: (list(v) if isinstance(v, list) else v) for k, v in _ASSERTED.items()}
    td = {"sub_query": "what is the status", **_ASSERTED}
    for key in ("params", "slots", "payload", "config", "produced_for"):
        td[key] = dict(nested)
    td.update(extra or {})
    return td


def _specialist(monkeypatch, task_def):
    predicate = {"verb_iri": "mesh:thing", "endpoint": _ENDPOINT, "score": 0.9,
                 "owner_persona": "SUSTAINMENT_LEAD", "domains": ["SUSTAINMENT"], "slots": []}
    telemetry = {"subject_uri": "http://x#Thing", "subject_instance_id": "",
                 "subject_instance_label": ""}
    monkeypatch.setattr(sup, "_classify_route",
                        lambda *a, **k: ("matched", dict(predicate), dict(telemetry)))
    out = sup.execute_subtask.compute_fn.decorated_fn(_ctx(), _Cfg(), task_def)
    assert out["route_status"] == "matched", out
    return out


def test_a_task_asserted_identity_never_reaches_the_specialist_payload(monkeypatch, posted):
    _specialist(monkeypatch, {"sub_query": "what is the status"})
    [control] = posted
    posted.clear()
    _specialist(monkeypatch, _poisoned())
    [got] = posted
    assert got["url"] == _ENDPOINT
    body = got["body"]
    assert body["user_email"] == ALICE and body["entitled_domains"] == ["SUSTAINMENT"], body
    assert body["user_id"] == "u-alice", body
    blob = json.dumps(body, default=str)
    assert "mallory" not in blob and "FINANCE" not in blob, blob
    # CONTROL: identical identity values with no mallory keys in the task.
    for k in ("user_email", "entitled_domains", "user_id"):
        assert body[k] == control["body"][k], k


# ── 3. the supervisor, fallback path ──────────────────────────────────────────────────────────

def test_a_task_asserted_identity_never_reaches_the_fallback_payload(monkeypatch, posted):
    def _go(telemetry, rejected):
        posted.clear()
        sup._call_engine_a_fallback(
            _ctx(), sub_query="what is the status", config=_Cfg(),
            fallback_reason="low_confidence", fallback_score=0.1,
            rejected_predicate=rejected, telemetry=telemetry)
        [sent] = posted
        return sent["body"]

    control = _go({"subject_uri": "http://x#Thing"}, {"verb_iri": "mesh:thing"})
    nested = dict(_ASSERTED)
    got = _go({"subject_uri": "http://x#Thing", **_ASSERTED, "params": dict(nested),
               "produced_for": dict(nested)},
              {"verb_iri": "mesh:thing", **_ASSERTED, "params": dict(nested)})
    assert got["user_email"] == ALICE and got["entitled_domains"] == ["SUSTAINMENT"], got
    assert got["user_id"] == "u-alice", got
    blob = json.dumps(got, default=str)
    assert "mallory" not in blob and "FINANCE" not in blob, blob
    for k in ("user_email", "entitled_domains", "user_id"):
        assert got[k] == control[k], k
