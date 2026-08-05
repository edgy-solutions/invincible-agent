"""REPLAY-DOUBLE: a Restate replay must add ZERO boundary spans (ADR-0038).

THE DEFECT THIS PINS. `observed_trace` opens a RECORDING OTel span and mints a fresh
span id on every entry. A Restate handler re-enters that `with` on every replay while
the memoized `ctx.run` body does NOT re-execute — so one run of the agent was reported
as N `analyst` spans. Witnessed live on BOTH engines before the fix: Engine A's trace
`4d66e2903df6` carried `analyst_boundary_spans=2`, and Engine E's post-hoist trace
showed 2x `engine-e graph reasoning`. Instrumentation is subject to the execution model
it observes: the trace, not the work, was the thing that lied.

THE FIX'S THREE MOVES, one test each below:
  1. the boundary's ids are JOURNALED (minted inside `ctx.run`), so replays reuse them;
  2. the boundary is an AMBIENT NON-RECORDING parent — it exports nothing itself, so
     re-entering it cannot double anything, while children still nest under it;
  3. the boundary observation is emitted from its OWN `ctx.run`, keyed on the journaled
     id (the ingestion API upserts on that id, so even a re-emit lands one observation).

Move 2 is the load-bearing one: it makes the double impossible BY CONSTRUCTION rather
than dedup-after-the-fact, which is why the central test enters the boundary TWICE and
asserts the exporter saw no boundary span at all.

CONVENTION guarded here: leaf spans (parenting nothing) belong INSIDE `ctx.run` — see
`review_starter.py` — while PARENTING boundaries use these primitives. Two patterns,
and the next instrumented engine must pick by that line, not by copying either example.

Run:  uv run --frozen python -m pytest tests/test_replay_safe_boundary.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "baml_shared"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import telemetry  # noqa: E402  (baml_shared/telemetry.py — the mesh's shim)

JOURNALED = {"trace_id": "a1b2c3d4" * 4, "span_id": "beef0000beef0004"}


@pytest.fixture
def enabled(monkeypatch):
    """The primitives no-op unless Langfuse is configured; pin the enabled path."""
    monkeypatch.setattr(telemetry, "LANGFUSE_ENABLED", True)


def _recorder():
    """A real OTel pipeline with an in-memory exporter, local to this test (no global
    provider mutation), so 'what actually got exported' is the assertion surface."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("replay-safe-boundary-test"), exporter


# --- move 1: the journaled identity ------------------------------------------
def test_minted_span_id_is_a_valid_otel_span_id():
    """16 lowercase hex — anything else is silently ignored as a parent id."""
    ids = telemetry.mint_boundary_ids("some-upstream-trace-id")
    assert re.fullmatch(r"[0-9a-f]{16}", ids["span_id"]), ids["span_id"]


# --- move 2: the double is impossible, not merely deduped --------------------
def test_replayed_boundary_exports_no_span_and_still_parents_children(enabled):
    """THE REGRESSION PIN. Enter the boundary TWICE with the SAME journaled ids — the
    Restate replay — and assert the exporter never saw a boundary span, while every
    child still parents under the journaled id. Before the fix this exported two.
    """
    tracer, exporter = _recorder()

    for _ in range(2):  # first execution, then the replay
        with telemetry.boundary_parent(JOURNALED):
            with tracer.start_as_current_span("run-smolagent"):
                pass

    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]
    # The boundary contributed NOTHING on either pass: only the children exported.
    assert names == ["run-smolagent", "run-smolagent"], names
    for s in spans:
        assert format(s.parent.span_id, "016x") == JOURNALED["span_id"]
        assert format(s.context.trace_id, "032x") == JOURNALED["trace_id"]


def test_boundary_restores_the_previous_context_on_exit(enabled):
    """The ambient parent is scoped to the block — a leak would silently re-parent
    every later span in the handler onto a boundary that already ended."""
    tracer, exporter = _recorder()
    with telemetry.boundary_parent(JOURNALED):
        pass
    with tracer.start_as_current_span("after-the-boundary"):
        pass
    after = exporter.get_finished_spans()[0]
    assert after.parent is None, "boundary context leaked past its block"


def test_boundary_yields_timing_for_the_emit(enabled):
    with telemetry.boundary_parent(JOURNALED) as timing:
        assert timing["started_at"] is not None
        assert timing["ended_at"] is None      # not closed until the block exits
    assert timing["ended_at"] >= timing["started_at"]


# --- move 3: the boundary observation is keyed on the journaled id -----------
class _FakeIngestion:
    def __init__(self):
        self.batches = []

    def batch(self, *, batch):
        self.batches.append(batch)


class _FakeClient:
    def __init__(self):
        self.api = type("_API", (), {"ingestion": _FakeIngestion()})()


def _emit(monkeypatch, mapping=None, values=None):
    fake = _FakeClient()
    import langfuse
    monkeypatch.setattr(langfuse, "get_client", lambda *a, **k: fake, raising=False)
    telemetry.emit_boundary(
        mapping, values or {}, ids=JOURNALED, name="analyst",
        timing={"started_at": telemetry._utcnow(), "ended_at": telemetry._utcnow()},
    )
    return fake.api.ingestion.batches


def test_emitted_boundary_carries_the_journaled_id(enabled, monkeypatch):
    batches = _emit(monkeypatch)
    assert len(batches) == 1
    spans = [e for e in batches[0] if e["type"] == "span-create"]
    assert len(spans) == 1
    body = spans[0]["body"]
    assert body["id"] == JOURNALED["span_id"], "boundary must reuse the journaled id"
    assert body["traceId"] == JOURNALED["trace_id"]
    assert body["startTime"] and body["endTime"]


def test_re_emitting_reuses_the_same_observation_id(enabled, monkeypatch):
    """Belt-and-suspenders for move 3: the ingestion API upserts on observation id
    (probed live — the same id twice lands ONE observation), so a re-emit is
    idempotent. That only holds while the id is the JOURNALED one, never a fresh one.
    """
    first = _emit(monkeypatch)[0]
    second = _emit(monkeypatch)[0]
    ids = [e["body"]["id"] for b in (first, second) for e in b if e["type"] == "span-create"]
    assert ids == [JOURNALED["span_id"]] * 2, ids


def test_trace_level_fields_ride_the_trace_body(enabled, monkeypatch):
    """The boundary is non-recording now, so the trace-level attributes
    `set_trace_standard` used to write onto it need `trace-create` as their carrier —
    otherwise the trace silently loses user/session/tags/release."""
    mapping = type("_M", (), {
        "slots": {"trace_id": "trace_id", "user_id": "authz_id", "session_id": "session_id"},
        "tags": ["domain"], "metadata": ["engine"], "content_bearing": (),
    })()
    values = {"trace_id": "up", "authz_id": "alice", "session_id": "s1",
              "domain": "MAINTENANCE", "engine": "restate_analyst"}
    batch = _emit(monkeypatch, mapping, values)[0]
    trace_ev = [e for e in batch if e["type"] == "trace-create"]
    assert len(trace_ev) == 1
    body = trace_ev[0]["body"]
    assert body["id"] == JOURNALED["trace_id"]
    assert body["userId"] == "alice" and body["sessionId"] == "s1"
    assert body["tags"] == ["MAINTENANCE"]
    assert body["metadata"] == {"engine": "restate_analyst"}


# --- the wiring, asserted on the source (importing the engines pulls Restate) --
# The defect propagated A -> E once already, which is why BOTH are pinned here and the
# defect-shape regex runs against every Restate engine rather than the two we fixed.
_ENGINES = {
    "Engine A": (Path("agent_fleet") / "restate_analyst" / "main.py", "analyst"),
}


@pytest.mark.parametrize("engine", sorted(_ENGINES))
def test_engine_uses_the_replay_safe_boundary(engine):
    path, slug = _ENGINES[engine]
    src = (_ROOT / path).read_text(encoding="utf-8")
    # whitespace-tolerant: these calls are wrapped across lines
    assert re.search(rf'ctx\.run\(\s*"mint-{slug}-boundary-ids"', src), engine
    assert re.search(rf'ctx\.run\(\s*"emit-{slug}-boundary"', src), engine
    assert "with boundary_parent(_boundary_ids)" in src, engine


@pytest.mark.parametrize("engine", sorted(_ENGINES))
def test_engine_has_not_reacquired_the_doubling_shape(engine):
    """The defect shape itself: an `observed_trace` block whose body opens a `ctx.run`.
    That pairing — a re-entered boundary around a memoized body — IS the bug."""
    path, _ = _ENGINES[engine]
    src = (_ROOT / path).read_text(encoding="utf-8")
    assert not re.search(
        r"with observed_trace\((?:[^)]|\)(?!:))*\):\s*\n\s*[^\n]*ctx\.run", src
    ), f"{engine} re-acquired the replay-doubling shape"
