"""CROSS-SERVICE CONTRACT: the direct specialist leg joins on a HEADER NAME (ADR-0038).

THE GAP THIS PINS. The supervisor's DIRECT specialist dispatch (a question that routes
cleanly to its predicate provider, bypassing Engine A) already carried `trace_id` in the
request BODY — added for Engine E, which is a Restate service whose durable handler reads
the body and never sees HTTP headers. But Engines W, O and F join in FastAPI middleware
that reads the `X-Trace-Id` HEADER, and that POST sent no headers at all. The id was on
the wire in a form none of the three reads, so every direct-leg call to W/O/F orphaned:
no error, no red, just a separate Langfuse trace per engine.

TWO JOIN MECHANISMS FOR ONE CONCERN — deliberate, and the reason this file exists:
  * HTTP engines (W/O/F)      -> the X-Trace-Id HEADER, read in middleware;
  * Restate engines (E, D)    -> the `trace_id` BODY FIELD, read by the durable handler.
Engine E's /query_graph proxy translates the first into the second. A new engine's author
must pick by WHICH KIND OF SERVICE IT IS, not by whichever example they read first — that
is exactly how the replay-double propagated from A to E.

WHY A CONTRACT TEST AND NOT A UNIT TEST: the failure mode is a silent RENAME. Change the
key in `_telemetry_headers` and nothing raises — the engines just fall back to minting
their own ids. Three consumers read this string from three separate repositories of
truth, so the string gets pinned at the producer AND asserted present at each consumer.

Source-text assertions for the consumers because importing the engines pulls FastAPI +
weaviate + neo4j, which aren't available in this env — and the claim is about the WIRING,
which the source is the authority on (same rationale as test_engine_e_trace_join.py).

Run:  uv run --frozen python -m pytest tests/test_specialist_dispatch_trace_headers.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HEADER = "X-Trace-Id"
SESSION_HEADER = "X-Session-Id"

_SUPERVISOR = _ROOT / "src" / "iagent" / "defs" / "dynamic_supervisor.py"

# The three HTTP consumers that join on the header, each in its own service.
_HEADER_CONSUMERS = {
    "Engine W": Path("agent_fleet") / "weaviate_expert" / "main.py",
    "Engine O": Path("agent_fleet") / "ontology_service" / "main.py",
    "Engine F": Path("agent_fleet") / "presentation_agent" / "main.py",
}


def _src(path: Path) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")


# --- the producer -------------------------------------------------------------
def test_supervisor_mints_the_trace_headers_in_one_place():
    """Single source for the header names — a rename must break HERE, once."""
    src = _src(_SUPERVISOR)
    assert "def _telemetry_headers(" in src
    assert f'"{HEADER}"' in src, f"{HEADER} is the name W/O/F read"
    assert f'"{SESSION_HEADER}"' in src


def test_specialist_dispatch_sends_the_headers():
    """THE REGRESSION PIN. The direct specialist POST must carry the telemetry headers.
    Before this seam was closed it passed `json=` and `timeout=` only, and W/O/F orphaned.
    """
    src = _src(_SUPERVISOR)
    # the specialist dispatch is the POST to the routed `endpoint`
    m = re.search(r"requests\.post\(\s*endpoint,(?P<args>.*?)\)\s*\n\s*response\.raise_for_status",
                  src, re.S)
    assert m, "specialist dispatch POST not found — did the call shape change?"
    args = m.group("args")
    assert "headers=" in args, "specialist dispatch sends no headers — W/O/F cannot join"
    assert "_telemetry_headers(config)" in args, "headers must come from the single source"


def test_engine_a_leg_uses_the_same_source():
    """Both outbound legs share one definition, so they cannot drift apart."""
    src = _src(_SUPERVISOR)
    assert src.count("_telemetry_headers(config)") >= 2


# --- the consumers ------------------------------------------------------------
@pytest.mark.parametrize("engine", sorted(_HEADER_CONSUMERS))
def test_http_engine_reads_the_header_the_supervisor_sends(engine):
    src = _src(_HEADER_CONSUMERS[engine])
    assert f'headers.get("{HEADER}")' in src, (
        f"{engine} does not read {HEADER} — the supervisor's direct leg would orphan"
    )


def test_restate_engine_e_still_joins_on_the_body_not_the_header():
    """The OTHER mechanism, asserted so nobody 'unifies' the two and breaks E.
    E is a Restate service: its durable handler reads the body; headers never reach it."""
    src = _src(Path("agent_fleet") / "neo4j_expert" / "service.py")
    assert 'request.get("trace_id")' in src, "Engine E joins on the BODY field"
    supervisor = _src(_SUPERVISOR)
    assert '"trace_id": config.trace_id or ""' in supervisor, (
        "the specialist payload must keep carrying the body field for Restate engines"
    )
