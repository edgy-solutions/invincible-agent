"""Engine O ``/plan``: an unparseable planner answer degrades, and no 502 leaks the prompt.

The ruling: a planner answer the parser rejects returns a single task holding the
person's question, flagged degraded, never a failed run; and the error path stops
returning the planner's prompt and the persona roster, whatever else happens.

``BamlValidationError.__str__`` embeds the full prompt (roster included), the raw model
output and a detailed message, so no handler may interpolate it.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from baml_py.errors import (
    BamlClientHttpError,
    BamlTimeoutError,
    BamlValidationError,
)
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.ontology_service import main as eo  # noqa: E402
from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

PROMPT_CANARY = "SYSTEM_PROMPT_CANARY"
ROSTER_CANARY = "ROSTER_CANARY_PERSONA"
RAW_CANARY = "I'm sorry, but I can't comply with that."
DETAIL_CANARY = "detail canary"
QUERY = "what failures are recorded for part 5530-184"
CANARIES = (PROMPT_CANARY, ROSTER_CANARY, "I'm sorry", DETAIL_CANARY)


class _Planner:
    def __init__(self, action):
        self.action = action

    async def DecomposeQuery(self, **_kw):
        if isinstance(self.action, BaseException):
            raise self.action
        return self.action


@pytest.fixture
def plan(monkeypatch):
    async def _personas():
        return [ROSTER_CANARY]

    async def _persona_string():
        return f"{PROMPT_CANARY} {ROSTER_CANARY}"

    monkeypatch.setattr(eo, "fetch_active_personas", _personas)
    monkeypatch.setattr(eo, "get_baml_persona_string", _persona_string)
    client = TestClient(eo.app, raise_server_exceptions=False)

    def _post(action):
        monkeypatch.setattr(eo, "b", _Planner(action))
        return client.post("/plan", json={"query": QUERY, "domain": "ANY_DOMAIN"})

    return _post


def _refusal():
    return BamlValidationError(
        prompt=f"{PROMPT_CANARY} ... {ROSTER_CANARY}",
        message="Failed to parse",
        raw_output=RAW_CANARY,
        detailed_message=DETAIL_CANARY,
    )


def test_a_refusal_returns_one_degraded_task_holding_the_question(plan, caplog):
    with caplog.at_level(logging.DEBUG):
        r = plan(_refusal())
    assert r.status_code == 200
    body = r.json()
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["sub_query"] == QUERY
    assert body["tasks"][0]["target_persona"] == ""
    assert body["degraded"] == "planner_unparseable"
    for c in CANARIES:
        assert c not in r.text
    assert "BamlValidationError" in caplog.text
    for c in CANARIES:
        assert c not in caplog.text


def test_control_an_http_error_is_still_a_502(plan):
    r = plan(BamlClientHttpError("client", "boom", 500, "detailed"))
    assert r.status_code == 502


def test_control_a_timeout_is_still_a_502(plan):
    r = plan(BamlTimeoutError("client", "slow"))
    assert r.status_code == 502


def test_control_an_empty_model_is_still_a_502(plan):
    empty = SimpleNamespace(
        model_dump=lambda: {"tasks": [], "extracted_concepts": [], "reasoning": ""}
    )
    assert plan(empty).status_code == 502


def test_no_502_carries_the_prompt_or_the_roster(plan):
    r = plan(RuntimeError(f"{PROMPT_CANARY} {ROSTER_CANARY}"))
    assert r.status_code == 502
    assert PROMPT_CANARY not in r.text
    assert ROSTER_CANARY not in r.text
    assert "RuntimeError" in r.json()["detail"]


def test_the_supervisor_fans_out_the_one_degraded_task(monkeypatch):
    degraded = {
        "tasks": [{"sub_query": QUERY, "target_persona": "", "tools_needed": [],
                   "expected_output": "Direct response to the user's query."}],
        "extracted_concepts": [], "reasoning": "", "domain": "MAINTENANCE",
        "degraded": "planner_unparseable",
    }

    def _post(url, json=None, headers=None, timeout=None, **_kw):
        return httpx.Response(200, json=degraded, request=httpx.Request("POST", url))

    monkeypatch.setattr(ds.requests, "post", _post)
    monkeypatch.setattr(ds, "_caller_token_for", lambda *a, **k: "")
    monkeypatch.setattr(ds, "_resolve_serialized", lambda ctx: _Null(), raising=False)

    class _Ctx:
        run_id = "run-1"
        log = logging.getLogger("test.plan.degrade")

        def add_output_metadata(self, *_a, **_k):
            pass

        def log_event(self, *_a, **_k):
            pass

    config = ds.SupervisorQueryConfig(user_query=QUERY, thread_id="t", user_persona="X")
    out = list(ds.create_task_plan.compute_fn.decorated_fn(_Ctx(), config))
    dyn = [o for o in out if o.__class__.__name__ == "DynamicOutput"]
    assert len(dyn) == 1
    assert dyn[0].value["sub_query"] == QUERY


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
