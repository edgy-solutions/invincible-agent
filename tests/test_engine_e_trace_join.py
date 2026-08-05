"""CROSS-SERVICE CONTRACT: the analyst→Engine-E trace join rides on one field name.

THE GAP THIS PINS (ADR-0038). Engine E is a Restate service; its durable handler reads
the request BODY, never HTTP headers. So a trace id has to reach E *as body data* or E's
`observed_trace` seeds on nothing and every knowledge-graph leg tells its story in a
separate Langfuse trace — enriched, but an orphan. E has TWO callers and the fix only
holds if BOTH put the id where the handler looks, under the SAME name:

  1. the supervisor's DIRECT specialist dispatch (a graph question that routes cleanly to
     the predicate provider) — puts `trace_id` in the dispatch body;
  2. the analyst's discovery tool (the generalist-fallback leg) — sends it as the
     X-Trace-Id HEADER, which E's /query_graph proxy translates into the body.

Three seams, one field name (`trace_id`). Rename it on any one of them and the join
silently breaks back into orphaned traces with nothing raised — the stringly-typed
contract fork the mesh's contract inventory exists to catch. This test asserts all three
seams name the field identically, so a rename fails HERE instead of in the telemetry.

These are source-text assertions (like test_review_payload_passthrough's
`test_forwarded_body_carries_them_not_just_the_model`) because importing the engines pulls
Restate / smolagents / neo4j / dagster, which aren't available in this env — and the claim
is about the WIRING, which the source is the authority on.

Run:  uv run --frozen python -m pytest tests/test_engine_e_trace_join.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _slice(src: str, start_marker: str, end_marker: str = "\ndef ") -> str:
    """The function body a claim is about — scoped to the def, not a byte window, so an
    added comment between the code and the assertion target can't make the test lie."""
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def test_supervisor_direct_leg_carries_trace_id_in_the_body():
    """PRODUCER, direct leg. The supervisor's specialist dispatch — the path a cleanly
    routed graph question takes, bypassing Engine A and its header-setting discovery tool
    — must put the id in the BODY under `trace_id`, because that is all Engine E's durable
    handler can read."""
    src = (_ROOT / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
    # Scope to execute_subtask (the specialist dispatch) — NOT a bare "payload = {",
    # which would match _call_engine_a_fallback's payload first and test the wrong leg.
    body = _slice(src, "def execute_subtask(", "\ndef ")
    assert '"trace_id": config.trace_id' in body, (
        "the supervisor's specialist dispatch dropped `trace_id` from the body — the "
        "direct-routing leg of the E join orphans again, silently (ADR-0038)."
    )


def test_engine_e_proxy_threads_header_or_body_into_the_body():
    """TRANSLATOR. E's /query_graph proxy is the seam where the analyst's X-Trace-Id
    HEADER becomes body data (Restate can't see headers). It must set `payload["trace_id"]`
    and must PREFER an id already in the body (the supervisor leg) over the header."""
    src = (_ROOT / "agent_fleet" / "neo4j_expert" / "main.py").read_text(encoding="utf-8")
    proxy = _slice(src, "async def query_graph_proxy(", "\n@app.")
    assert 'payload["trace_id"]' in proxy, "E's proxy no longer threads trace_id into the body"
    assert 'request.headers.get("X-Trace-Id")' in proxy, (
        "E's proxy stopped adopting the X-Trace-Id header — the analyst (discovery-tool) "
        "leg, which sends the id as a header, orphans again."
    )
    assert 'payload.get("trace_id")' in proxy, (
        "E's proxy no longer PREFERS a body-supplied id — a supervisor-threaded trace_id "
        "would be clobbered by the header/uuid fallback."
    )


def test_engine_e_handler_consumes_the_same_body_field():
    """CONSUMER. The durable handler seeds observed_trace AND flips its join:pending-proxy
    tag off exactly `request.get("trace_id")`. If the producer/proxy write one name and the
    handler reads another, the join is dead on both counts. Same field, or nothing joins."""
    src = (_ROOT / "agent_fleet" / "neo4j_expert" / "service.py").read_text(encoding="utf-8")
    assert 'trace_id=request.get("trace_id")' in src, (
        "Engine E's observed_trace no longer seeds on request.get('trace_id') — it can no "
        "longer join the caller's trace even when the id arrives."
    )
    # The tag must key off the SAME read, so a threaded id both joins the trace and heals
    # the pending-proxy marker in one move (no 'joined but still tagged pending' state).
    assert 'if not request.get("trace_id")' in src, (
        "the join:pending-proxy tag no longer keys off request.get('trace_id') — it can "
        "drift out of sync with the actual join state (a healed gap still crying wolf)."
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
