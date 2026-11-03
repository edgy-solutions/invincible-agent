"""Engine S's per-person verbs are dispatched with the CALLER's token, not `svc:supervisor`.

Engine S reads the person only from the bearer (`measures._caller_authz_id`), and
`_visible_records` refuses a service identity (`NoPerson`, a 422 `no_person`). Lane saf's 192
walk: "what failures are recorded for part 5530-184" routed to `whatFailedOnThisPart` and was
dispatched as `svc:supervisor`. Since the architect ruling of 2026-11-02 the dispatch forwards the caller on EVERY verb for a
run that has a person, so there is no set to list a verb in: this file keeps the instance (arm 1)
and a control that an ordinary verb of the same engine is forwarded too (arm 2). The old arm 3,
which derived "every measure reaching `_visible_records`" from measures.py and checked each was
listed, had nothing left to check against and is gone with its detector and control.

Run:  uv run --frozen python -m pytest tests/identity/test_the_per_person_verb_call_carries_the_caller.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

ALICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE-PING-ROOTED.signature"
SERVICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.SVC-SUPERVISOR.signature"


class _Ctx:
    run_id = "0f1e2d3c-run"

    class log:
        @staticmethod
        def info(*a, **k): ...
        @staticmethod
        def warning(*a, **k): ...
        @staticmethod
        def error(*a, **k): ...

    def log_event(self, *a, **k): ...
    def add_output_metadata(self, *a, **k): ...


class _Resp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"answer": "ok", "data": {}, "sources": []}


def _predicate(verb):
    return {
        "verb_iri": f"mesh:{verb}",
        "endpoint": f"http://engine-s/measure/{verb}",
        "owner_persona": "SAFETY_ENGINEER",
        "domains": ["SUSTAINMENT"],
        "score": 0.99,
    }


def _drive(monkeypatch, verb):
    """Run the real `execute_subtask` for one routed verb; return (POST headers, redemptions)."""
    sent, redeemed = {}, []
    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token",
        lambda *a, **k: SERVICE_TOKEN, raising=False,
    )
    monkeypatch.setattr(
        ds, "_classify_route",
        lambda *a, **k: (ds._ROUTING_MATCHED, _predicate(verb), {}),
    )

    def _redeem(context, config):
        redeemed.append(1)
        return ALICE_TOKEN

    monkeypatch.setattr(ds, "_redeem_caller_token", _redeem)

    def _post(url, json=None, headers=None, timeout=None):
        sent["url"], sent["headers"] = url, headers
        return _Resp()

    monkeypatch.setattr(ds.requests, "post", _post)
    config = ds.SupervisorQueryConfig(
        user_query="what failures are recorded for part 5530-184",
        user_email="alice@example.com",
        user_persona="SAFETY_ENGINEER",
        entitled_domains=["SUSTAINMENT"],
        thread_id="thread-1",
        trace_id="trace-1",
        session_id="session-1",
    )
    ds.execute_subtask.compute_fn.decorated_fn(
        _Ctx(), config, {"sub_query": config.user_query}
    )
    return sent.get("headers"), redeemed


# ── arm 1: the instance ───────────────────────────────────────────────────────────

def test_what_failed_on_this_part_is_dispatched_with_the_callers_token(monkeypatch):
    headers, redeemed = _drive(monkeypatch, "whatFailedOnThisPart")

    assert redeemed == [1], "the per-person verb did not redeem the caller's identity"
    assert headers["Authorization"] == f"Bearer {ALICE_TOKEN}"


# ── arm 2: control, differs from arm 1 ONLY in the verb ───────────────────────────

def test_an_ordinary_engine_s_verb_is_dispatched_with_the_callers_token_too(monkeypatch):
    """The ruling (architect, 2026-11-02): the forwarding is in the dispatch, not per verb. A
    verb that never read the person before is forwarded all the same."""
    headers, redeemed = _drive(monkeypatch, "assessDeferralRisk")

    assert redeemed == [1], "an ordinary verb of a run with a person did not redeem"
    assert headers["Authorization"] == f"Bearer {ALICE_TOKEN}"
