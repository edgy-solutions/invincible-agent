"""/orchestrate leaves exactly ONE `orchestrate_access` line per call: who, through which client
(`azp`), session, the routed verb and the case if the events carried them, when, and how it ended
(completed | closed | error | refused:<status>). Never message text, tokens or payload bodies.

Drives the REAL wrapper and the REAL logger (`iagent.audit.orchestrate`) with caplog; the stream is
a synthetic SSE sequence shaped like the real one (`route_decision` carries `action.iri`).

Run: uv run pytest tests/routing/test_orchestrate_writes_one_audit_line.py -q
"""
from __future__ import annotations

import inspect
import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402
from iagent.auth import User  # noqa: E402

LOGGER = "iagent.audit.orchestrate"
VERB = "mesh:planCapabilityPath"


def _sse(event, obj):
    return f"event: {event}\ndata: {json.dumps(obj)}\n\n"


FULL = [
    _sse("status", {"stage": "routing", "secret_text": "do-not-log-this-message"}),
    ": keepalive\n\n",
    _sse("route_decision", {"action": {"iri": VERB, "label": "x"}, "about": {"uri": "u"}}),
    _sse("case_update", {"case_id": "case-42", "state": "open"}),
    _sse("final_payload", {"payload": "body-must-not-be-logged"}),
]
BARE = [_sse("status", {"stage": "routing"}), _sse("final_payload", {"k": 1})]


async def _gen(chunks, then=None):
    for c in chunks:
        yield c
    if then:
        raise then


def _lines(caplog):
    return [r.getMessage() for r in caplog.records
            if r.name == LOGGER and r.getMessage().startswith("orchestrate_access ")]


def _wrap(gen):
    return gw._audit_orchestrate_wrap(gen, who="alice@example.com", via="cortex-ui", session_id="s-1")


@pytest.fixture()
def arrive(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    return caplog


@pytest.mark.asyncio
async def test_completed_stream_one_line_with_verb_and_case(arrive):
    out = [c async for c in _wrap(_gen(FULL))]
    assert out == FULL  # byte-identical, in order
    (line,) = _lines(arrive)
    for part in ("who=alice@example.com", "via=cortex-ui", "session_id=s-1", f"verb={VERB}",
                 "case=case-42", "outcome=completed", "when="):
        assert part in line, line
    assert "do-not-log-this-message" not in line and "body-must-not-be-logged" not in line


@pytest.mark.asyncio
async def test_no_verb_no_case_is_honest_empty(arrive):
    out = [c async for c in _wrap(_gen(BARE))]
    assert out == BARE
    (line,) = _lines(arrive)
    assert " verb= case= " in line and "outcome=completed" in line, line


@pytest.mark.asyncio
async def test_unknown_verb_is_recorded_empty(arrive):
    chunks = [_sse("route_decision", {"action": {"iri": "UNKNOWN"}})]
    [c async for c in _wrap(_gen(chunks))]
    (line,) = _lines(arrive)
    assert " verb= " in line, line


@pytest.mark.asyncio
async def test_client_close_is_closed(arrive):
    g = _wrap(_gen(FULL))
    first = await g.__anext__()
    assert first == FULL[0]
    await g.aclose()
    (line,) = _lines(arrive)
    assert "outcome=closed" in line, line


@pytest.mark.asyncio
async def test_raising_generator_is_error_and_propagates(arrive):
    seen = []
    with pytest.raises(RuntimeError, match="boom"):
        async for c in _wrap(_gen(FULL[:3], then=RuntimeError("boom"))):
            seen.append(c)
    assert seen == FULL[:3]
    (line,) = _lines(arrive)
    assert "outcome=error" in line and f"verb={VERB}" in line, line


def test_orchestrate_wires_the_wrapper_inside_the_keepalive():
    src = inspect.getsource(gw.orchestrate)
    assert "_audit_orchestrate_wrap(" in src
    assert src.index("_keepalive_wrap(") < src.index("_audit_orchestrate_wrap(") \
        < src.index("generate_dagster_stream(")
    assert "current_user.authz_id" in src and "azp" in src


class _HttpReq:
    headers: dict = {}


@pytest.mark.asyncio
async def test_pre_stream_refusal_logs_refused_status(arrive, monkeypatch):
    monkeypatch.setattr(gw, "generate_dagster_stream", lambda *a, **k: None)
    user = User(id="u1", authz_id="alice@example.com", azp="mcp-client", entitlement_source="none")
    req = gw.InterviewRequest(
        message="x", session_id="s-refused",
        seed_panel={"template_id": "no_such_template", "panel": 0, "bindings": {}},
    )
    with pytest.raises(HTTPException) as ei:
        await gw.orchestrate(req, _HttpReq(), user)
    assert ei.value.status_code == 422
    (line,) = _lines(arrive)
    assert ("who=alice@example.com via=mcp-client session_id=s-refused verb= case= " in line
            and "outcome=refused:422" in line), line
