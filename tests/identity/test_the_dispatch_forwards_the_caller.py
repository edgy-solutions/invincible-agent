"""A subtask dispatched for a person always carries that person's token, whatever the verb.

Architect ruling 2026-11-02: "Every engine call the supervisor makes forwards the user's token;
'five hard-coded verbs' is a defect: the forwarding is in the dispatch, not per verb."

These drive the REAL `execute_subtask` against a request double that stands in for BOTH the
BFF's redeem endpoint and the engine, and assert the REQUEST each received (the `Authorization`
header, the slot), not a return value. Scope: the subtask leg only.

Run:  uv run --frozen python -m pytest tests/identity/test_the_dispatch_forwards_the_caller.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

SERVICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.SVC-SUPERVISOR.signature"
# A verb that was never in the removed allow-list.
_UNLISTED_VERB = "mesh:aVerbNobodyEverListed"


class _Log:
    @staticmethod
    def info(*a, **k): ...
    @staticmethod
    def warning(*a, **k): ...
    @staticmethod
    def error(*a, **k): ...


class _Ctx:
    run_id = "0f1e2d3c-run"
    log = _Log

    def __init__(self, slot=0):
        self._key = f"task_{slot}"

    def get_mapping_key(self):
        return self._key

    def log_event(self, *a, **k): ...
    def add_output_metadata(self, *a, **k): ...


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ds.requests.exceptions.HTTPError(str(self.status_code))

    def json(self):
        return self._body


def _drive(monkeypatch, *, user_email, slots=(0,), redeem_status=200, verb=_UNLISTED_VERB):
    """Run the real `execute_subtask` once per slot. Returns (engine_calls, redeem_calls, results);
    each call is the (url, headers, json) the double received."""
    engine_calls, redeem_calls, results = [], [], []
    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token",
        lambda *a, **k: SERVICE_TOKEN, raising=False,
    )
    predicate = {
        "verb_iri": verb, "endpoint": "http://engine-x/do", "owner_persona": "ANALYST",
        "domains": ["D"], "score": 0.99,
    }
    monkeypatch.setattr(
        ds, "_classify_route", lambda *a, **k: (ds._ROUTING_MATCHED, dict(predicate), {}),
    )

    def _post(url, json=None, headers=None, timeout=None):
        if str(url).endswith("/internal/identity/redeem"):
            redeem_calls.append((url, headers, json))
            if redeem_status != 200:
                return _Resp(redeem_status, {"detail": {"error": "not_found", "message": "x"}})
            return _Resp(200, {"token": f"CALLER-TOKEN-{json['call_id'].split('/')[1]}"})
        engine_calls.append((url, headers, json))
        return _Resp(200, {"answer": "ok", "data": {}, "sources": []})

    monkeypatch.setattr(ds.requests, "post", _post)
    config = ds.SupervisorQueryConfig(
        user_query="q", user_email=user_email, user_persona="ANALYST",
        entitled_domains=["D"], thread_id="t", trace_id="tr", session_id="s",
    )
    for slot in slots:
        results.append(ds.execute_subtask.compute_fn.decorated_fn(
            _Ctx(slot), config, {"sub_query": "q"}))
    return engine_calls, redeem_calls, results


def test_a_person_and_a_verb_never_listed_dispatches_with_the_redeemed_token(monkeypatch):
    engine, redeems, _ = _drive(monkeypatch, user_email="alice@example.com")

    assert len(redeems) == 1
    assert len(engine) == 1
    auth = engine[0][1]["Authorization"]
    assert auth == "Bearer CALLER-TOKEN-dispatch"
    assert SERVICE_TOKEN not in auth, "the engine call used the supervisor's own mint"


def test_a_person_whose_redemption_fails_is_refused_and_never_dispatched_as_the_service(monkeypatch):
    engine, redeems, results = _drive(
        monkeypatch, user_email="alice@example.com", redeem_status=404)

    assert len(redeems) == 1
    assert engine == [], "a POST reached the engine after the redemption failed"
    assert results[0]["expert_response"]["status"] == "caller_identity_unavailable"


@pytest.mark.parametrize("who", ["", "   ", "svc:supervisor", "SVC:other"])
def test_INTERIM_a_run_with_no_person_still_dispatches_as_the_service(monkeypatch, who):
    """INTERIM, not the final rule. The architect has ruled that a run with no person is a
    declared machine principal (`pipeline:<name>`), never svc:supervisor; that lands in the next
    PR and this arm is replaced then. It pins today's behaviour so the change is deliberate."""
    engine, redeems, _ = _drive(monkeypatch, user_email=who)

    assert redeems == [], "a run with no person asked the vault for a token"
    assert len(engine) == 1
    assert engine[0][1]["Authorization"] == f"Bearer {SERVICE_TOKEN}"


def test_the_per_verb_allow_list_is_gone():
    assert not hasattr(ds, "_CALLER_IDENTITY_VERBS")
    assert not hasattr(ds, "_verb_needs_caller_identity")
