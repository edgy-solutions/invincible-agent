"""An engine's refusal-bearing 401/403/409 reaches the user as a REFUSAL, not as an outage.

`execute_subtask` called `raise_for_status()` on the engine's reply, so a policy refusal
(`{"detail": {"error", "refusal": {"policy_id", "missing_binding"}}}`) landed in the transport
handler and read "engine could not be reached ... system fault" -- and reddened the run through
`assert_every_engine_answered`. A refusal is an answer; the relay carries it down the success
path as the same `{refused: true, ...}` dict a 200-refusal produces. Only 401/403/409 relay.

Run:  .venv/Scripts/python -X utf8 -m pytest tests/test_the_supervisor_relays_an_engine_refusal.py -q
"""
from __future__ import annotations

import json as _json
import sys
from pathlib import Path

import pytest
import requests

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dagster import build_op_context  # noqa: E402

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

SERVICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.SVC-SUPERVISOR.signature"
FAMILY = "task_grants"  # a real family: policy/grantors/task_grants.yaml


class _Ctx:
    run_id = "run-1"

    class log:
        @staticmethod
        def info(*a, **k): ...
        @staticmethod
        def warning(*a, **k): ...
        @staticmethod
        def error(*a, **k): ...

    def log_event(self, *a, **k): ...
    def add_output_metadata(self, *a, **k): ...


def _response(status, body=None, *, raw=None, content_type="application/json"):
    r = requests.Response()
    r.status_code = status
    r._content = raw if raw is not None else _json.dumps(body).encode("utf-8")
    r.headers["Content-Type"] = content_type
    return r


def _refusal_body():
    return {"detail": {
        "error": "cell_not_entitled",
        "refusal": {"policy_id": FAMILY, "missing_binding": "x"},
        "message": "m",
    }}


def _drive(monkeypatch, post):
    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token",
        lambda *a, **k: SERVICE_TOKEN, raising=False,
    )
    monkeypatch.setattr(ds, "_classify_route", lambda *a, **k: (
        ds._ROUTING_MATCHED,
        {"verb_iri": "mesh:queryKnowledgeGraph", "endpoint": "http://engine-e/q",
         "owner_persona": "AUDITOR", "domains": ["MAINTENANCE"], "score": 0.99},
        {},
    ))
    monkeypatch.setattr(ds.requests, "post", post)
    config = ds.SupervisorQueryConfig(
        user_query="q", user_email="alice@example.com", user_persona="AUDITOR",
        entitled_domains=["MAINTENANCE"], thread_id="t", trace_id="tr", session_id="s",
    )
    return ds.execute_subtask.compute_fn.decorated_fn(_Ctx(), config, {"sub_query": "q"})


def _returning(resp):
    return lambda url, json=None, headers=None, timeout=None: resp


def _assert_outage(result):
    er = result["expert_response"]
    assert er["status"] == "engine_unreachable", er
    assert er["reason"] == "transport_failure", er


@pytest.mark.parametrize("status", [403, 401, 409])
def test_a_refusal_bearing_4xx_is_relayed_as_a_refusal(monkeypatch, status):
    from iagent.authz.refusal import _grantable_by, grantors

    result = _drive(monkeypatch, _returning(_response(status, _refusal_body())))
    er = result["expert_response"]

    assert er["refused"] is True
    assert er["outcome"] == "cell_not_entitled"
    assert er["reason"] == "m"
    assert er["status_code"] == status
    assert er["refusal"]["grantable_by"] == _grantable_by(grantors()[FAMILY])
    assert er.get("status") != "engine_unreachable"


def test_a_403_with_a_non_json_body_is_still_an_outage(monkeypatch):
    resp = _response(403, raw=b"<html>Forbidden</html>", content_type="text/html")
    _assert_outage(_drive(monkeypatch, _returning(resp)))


def test_a_403_with_json_but_no_refusal_is_still_an_outage(monkeypatch):
    _assert_outage(_drive(monkeypatch, _returning(_response(403, {"detail": "Forbidden"}))))


def test_only_401_403_409_relay(monkeypatch):
    _assert_outage(_drive(monkeypatch, _returning(_response(500, _refusal_body()))))


def test_a_connection_error_is_still_an_outage(monkeypatch):
    def _boom(*a, **k):
        raise requests.ConnectionError("refused")

    _assert_outage(_drive(monkeypatch, _boom))


def test_a_relayed_refusal_does_not_redden_the_run(monkeypatch):
    result = _drive(monkeypatch, _returning(_response(403, _refusal_body())))
    ds.assert_every_engine_answered(build_op_context(), [result], ui_payload="{}")


def test_a_grantor_map_that_will_not_load_still_relays_the_refusal(monkeypatch):
    """The grantor map is loaded ON the deny path. If it cannot be read, the refusal still
    travels as a refusal -- with the engine's two names and NO `grantable_by`, because an engine
    never speaks for the deployment's grantor -- rather than crashing the op."""
    def _broken(_upstream):
        raise RuntimeError("grantor map unreadable")

    monkeypatch.setattr(ds, "relay_refusal", _broken)
    result = _drive(monkeypatch, _returning(_response(403, _refusal_body())))
    er = result["expert_response"]

    assert er["refused"] is True
    assert er["refusal"] == {"policy_id": FAMILY, "missing_binding": "x"}
    assert er.get("status") != "engine_unreachable"
