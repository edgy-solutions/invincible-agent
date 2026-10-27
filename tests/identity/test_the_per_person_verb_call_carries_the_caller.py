"""Engine S's per-person verbs are dispatched with the CALLER's token, not `svc:supervisor`.

Engine S reads the person only from the bearer (`measures._caller_authz_id`), and
`_visible_records` refuses a service identity (`NoPerson`, a 422 `no_person`). Lane saf's 192
walk: "what failures are recorded for part 5530-184" routed to `whatFailedOnThisPart` and was
dispatched as `svc:supervisor`. The fix goes through the existing `_CALLER_IDENTITY_VERBS` set;
this file seals the instance (arms 1-2) and the class (arm 3: every measure that reaches the
person filter is in the set, derived from measures.py rather than restated).

Run:  uv run --frozen python -m pytest tests/identity/test_the_per_person_verb_call_carries_the_caller.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

ALICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE-PING-ROOTED.signature"
SERVICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.SVC-SUPERVISOR.signature"

_MEASURES = _ROOT / "agent_fleet" / "safety_agent" / "measures.py"
_PERSON_READERS = {"_visible_records", "_caller_authz_id"}


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


# ── the production fn -> verb mapping, read from the engine's own VERBS table ─────

def _verb_by_fn():
    from agent_fleet.safety_agent import main as engine_s

    return {v["fn"]: ds._verb_local_name(v["verb"]) for v in engine_s.VERBS}


def _reaching_person_filter(source: str) -> set:
    """Measure functions that reach `_visible_records`/`_caller_authz_id`, transitively."""
    fns = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    calls = {
        name: {c.func.id for c in ast.walk(n)
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        for name, n in fns.items()
    }
    reach = {name for name, cs in calls.items() if cs & _PERSON_READERS}
    reach -= _PERSON_READERS
    while True:
        more = {name for name, cs in calls.items() if cs & reach} - reach
        if not more:
            return reach
        reach |= more


# ── arm 1: the instance ───────────────────────────────────────────────────────────

def test_what_failed_on_this_part_is_dispatched_with_the_callers_token(monkeypatch):
    headers, redeemed = _drive(monkeypatch, "whatFailedOnThisPart")

    assert redeemed == [1], "the per-person verb did not redeem the caller's identity"
    assert headers["Authorization"] == f"Bearer {ALICE_TOKEN}"


# ── arm 2: control, differs from arm 1 ONLY in the verb ───────────────────────────

def test_an_ordinary_engine_s_verb_stays_on_the_service_identity(monkeypatch):
    headers, redeemed = _drive(monkeypatch, "assessDeferralRisk")

    assert redeemed == [], "a verb that never reads the person must not redeem"
    assert headers["Authorization"] == f"Bearer {SERVICE_TOKEN}"


# ── arm 3: the class ──────────────────────────────────────────────────────────────

def test_every_measure_that_reaches_the_person_filter_is_a_caller_identity_verb():
    reach = _reaching_person_filter(_MEASURES.read_text(encoding="utf-8"))
    by_fn = _verb_by_fn()
    verbs = {by_fn[f] for f in reach}

    assert "whatFailedOnThisPart" in verbs, "detector positive control: the known verb"
    assert verbs, "detector positive control: a non-empty derived set"
    assert not (reach - set(by_fn)), "a measure reaches the person filter with no verb"
    missing = verbs - ds._CALLER_IDENTITY_VERBS
    assert not missing, f"per-person verbs dispatched as svc:supervisor: {sorted(missing)}"


def test_the_detector_sees_a_person_read_added_to_the_control_verb():
    """Mutant on a COPY of the source: the control measure now reads the person -> it joins
    the derived set, so arm 3 would go red on it."""
    src = _MEASURES.read_text(encoding="utf-8")
    assert "assess_deferral_risk" not in _reaching_person_filter(src)
    mutated = src.replace(
        "def assess_deferral_risk(state: Any = None, *, work_order_id: str) -> Dict[str, Any]:\n",
        "def assess_deferral_risk(state: Any = None, *, work_order_id: str) -> Dict[str, Any]:\n"
        "    _visible_records([])\n",
        1,
    )
    assert mutated != src
    reach = _reaching_person_filter(mutated)
    assert "assess_deferral_risk" in reach
    assert ds._verb_local_name(_verb_by_fn()["assess_deferral_risk"]) not in \
        ds._CALLER_IDENTITY_VERBS
