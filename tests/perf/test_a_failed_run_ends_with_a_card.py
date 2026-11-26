"""A FAILED RUN ENDS WITH A CARD NAMING THE STEP AND THE TRACE ID (ADR-0072 8.1, ruled 2026-11-15).

Before: a run that failed yielded "Pipeline failed." and then, because it had not succeeded,
a SECOND error (`ui_payload_timeout`) and no card -- on both backends, and on the durable one
with a cause that said `dagster`. Now the stream names the failed step and the trace id in the
`pipeline_error`, delivers the run's own card if it made one, else a failure card.

DRIVEN THROUGH THE REAL ``_generate_dagster_stream_inner`` on both backends (Dagster scripted
at the helper seams; the durable path through a real ``DurableAnswers`` on a mock transport).
THE CONTROL is the same run succeeding: it delivers its answer and no failure card. THE MUTANT
is dropping the card on FAILURE (the `elif _run_failure` branch): tests 1 and 3 then fail.

Run:  uv run --frozen python -m pytest tests/perf/test_a_failed_run_ends_with_a_card.py -q
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# `stubbed_stream` replaces the global httpx.AsyncClient; the durable client needs the real one.
_RealAsyncClient = httpx.AsyncClient

import iagent.gateway as gw  # noqa: E402
from iagent.identity_vault import IdentityVault  # noqa: E402
from src.iagent.durable_answers import DurableAnswers  # noqa: E402
from tests.planning.test_seed_panel_gates_and_fallback import stubbed_stream  # noqa: E402,F401

RUN = "run-fail-1"
TRACE = "trace-8f1c"
ALICE = "alice@example.com"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE-FAILCARD.signature"
OWN = {"components": [{"archetype": "TABLE", "marker": "own"}]}
ANSWER = {"components": [{"archetype": "TABLE", "marker": "answer"}]}
STEPS = [
    {"stepKey": "create_task_plan", "status": "SUCCESS", "endTime": 1.0},
    {"stepKey": "execute_subtask[1]", "status": "FAILURE", "endTime": 3.0},
    {"stepKey": "execute_subtask[0]", "status": "FAILURE", "endTime": 2.0},
]


def _req():
    return gw.InterviewRequest(
        message="how is NP-MERIDIAN's variance",
        session_id="s-failcard-1",
        answering_artifact_id="artifact-1",
        bound_slots={"program_id": "NP-MERIDIAN"},
    )


@pytest.fixture
def base(stubbed_stream, monkeypatch):  # noqa: F811
    monkeypatch.setattr(gw, "VAULT", IdentityVault())
    monkeypatch.setattr(
        gw, "_pre_resolved_from_ask",
        lambda *a, **k: {
            "subject_uri": "http://invincible-agent/fin#Program",
            "subject_instance_id": "NP-MERIDIAN", "subject_instance_label": "",
            "verb_iri": "mesh:finVarianceAnalysis", "owner_persona": "",
        },
    )
    real_sleep = asyncio.sleep

    async def _nosleep(_s=0, *a, **k):
        await real_sleep(0)

    monkeypatch.setattr(gw.asyncio, "sleep", _nosleep)
    return stubbed_stream


def _dagster(monkeypatch, *, status, steps=STEPS, payload=None):
    monkeypatch.delenv("IAGENT_ANSWER_PATH", raising=False)

    async def _launch(*a, **k):
        return RUN

    async def _status(rid):
        return {"status": status}

    async def _events(rid):
        return []

    async def _steps(rid):
        return steps

    async def _payload(rid):
        return payload if payload is not None else {"error": "no output"}

    monkeypatch.setattr(gw, "_launch_supervisor_job", _launch)
    monkeypatch.setattr(gw, "_get_run_status", _status)
    monkeypatch.setattr(gw, "_get_run_events", _events)
    monkeypatch.setattr(gw, "_get_step_stats", _steps)
    monkeypatch.setattr(gw, "_get_ui_payload_output", _payload)


def _durable(monkeypatch, *, status, failed_step=None, result=None):
    launched = {}

    def h(req):
        if req.url.path.endswith("/run/send"):
            launched["body"] = json.loads(req.content or b"null")
            return httpx.Response(202, json={})
        snap = {"status": status, "events": [], "steps": [], "result": result}
        if failed_step:
            snap["failed_step"] = failed_step
        # the trace id the snapshot carries IS the one the launch body carried
        snap["trace_id"] = (launched.get("body") or {}).get("trace_id")
        return httpx.Response(200, json=snap)

    da = DurableAnswers("http://r:8080", snapshot_ttl_s=0,
                        client_factory=lambda: _RealAsyncClient(transport=httpx.MockTransport(h)))
    monkeypatch.setattr(gw, "_DURABLE_ANSWERS", da)
    monkeypatch.setenv("IAGENT_ANSWER_PATH", "durable")


def _setup(monkeypatch, path, *, status, failed_step=None, own=None, steps=STEPS):
    if path == "dagster":
        _dagster(monkeypatch, status=status, steps=steps, payload=own)
    else:
        result = None if own is None else own
        _durable(monkeypatch, status=status, failed_step=failed_step, result=result)


async def _drive(trace_id=TRACE):
    events = []
    agen = gw._generate_dagster_stream_inner(_req(), trace_id=trace_id, user_email=ALICE,
                                             caller_token=TOKEN)
    async for ev in agen:
        events.append(ev)
    return "".join(events)


def _parse(blob):
    out, name = [], None
    for line in blob.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:") and name:
            try:
                out.append((name, json.loads(line[5:])))
            except ValueError:
                out.append((name, line[5:].strip()))
            name = None
    return out


def _of(pairs, name):
    return [d for n, d in pairs if n == name]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["dagster", "durable"])
async def test_a_run_that_fails_at_a_named_step_ends_with_a_card_naming_the_step_and_the_trace_id(
    base, monkeypatch, path
):
    _setup(monkeypatch, path, status="FAILURE", failed_step="execute_subtask[0]")
    blob = await _drive()
    pairs = _parse(blob)
    finals = _of(pairs, "final_payload")
    assert len(finals) == 1, blob
    comps = finals[0]["components"]
    assert len(comps) == 1 and comps[0]["archetype"] == "KNOWLEDGE_DOCUMENT"
    assert "execute_subtask[0]" in comps[0]["markdown_content"]
    assert TRACE in comps[0]["markdown_content"]
    errs = _of(pairs, "pipeline_error")
    assert len(errs) == 1, errs
    assert errs[0]["failed_step"] == "execute_subtask[0]"
    assert errs[0]["trace_id"] == TRACE
    assert errs[0]["cause"] == ("dagster_run_failed" if path == "dagster" else "answer_run_failed")
    assert "ui_payload_timeout" not in blob
    assert base["bundles"][-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_the_durable_cause_never_names_dagster(base, monkeypatch):
    _setup(monkeypatch, "durable", status="FAILURE", failed_step="execute_subtask[0]")
    pairs = _parse(await _drive())
    errs = _of(pairs, "pipeline_error")
    assert len(errs) == 1
    assert "dagster" not in json.dumps(errs[0]).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["dagster", "durable"])
async def test_a_failed_run_that_made_its_own_card_delivers_that_card(base, monkeypatch, path):
    own = {"payload": OWN, "referenced_uris": ["u1"]}
    steps = [{"stepKey": "assert_every_engine_answered", "status": "FAILURE", "endTime": 5.0}]
    _setup(monkeypatch, path, status="FAILURE", failed_step="assert_every_engine_answered",
           own=own, steps=steps)
    blob = await _drive()
    pairs = _parse(blob)
    finals = _of(pairs, "final_payload")
    assert finals == [OWN], blob
    errs = _of(pairs, "pipeline_error")
    assert len(errs) == 1
    assert errs[0]["failed_step"] == "assert_every_engine_answered"
    assert errs[0]["trace_id"] == TRACE
    assert "ui_payload_timeout" not in blob


@pytest.mark.asyncio
async def test_absent_values_are_said_absent_never_invented(base, monkeypatch):
    steps = [{"stepKey": "create_task_plan", "status": "SUCCESS", "endTime": 1.0}]
    _setup(monkeypatch, "dagster", status="FAILURE", steps=steps)
    pairs = _parse(await _drive(trace_id=""))
    finals = _of(pairs, "final_payload")
    assert len(finals) == 1
    md = finals[0]["components"][0]["markdown_content"]
    assert "was not recorded" in md and "no trace id" in md
    errs = _of(pairs, "pipeline_error")
    assert len(errs) == 1
    assert "failed_step" not in errs[0] and "trace_id" not in errs[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["dagster", "durable"])
async def test_the_CONTROL_the_same_run_succeeding_delivers_its_answer_and_no_failure_card(
    base, monkeypatch, path
):
    _setup(monkeypatch, path, status="SUCCESS", own={"payload": ANSWER, "referenced_uris": []})
    blob = await _drive()
    pairs = _parse(blob)
    assert _of(pairs, "final_payload") == [ANSWER], blob
    assert _of(pairs, "pipeline_error") == []
    assert "could not be completed" not in blob


def test_failure_card_unit():
    card = gw._failure_card("s`x", "t`y")
    assert len(card["components"]) == 1
    comp = card["components"][0]
    assert comp["archetype"] == "KNOWLEDGE_DOCUMENT"
    assert "`sx`" in comp["markdown_content"] and "`ty`" in comp["markdown_content"]
    assert "s`x" not in comp["markdown_content"] and "t`y" not in comp["markdown_content"]
