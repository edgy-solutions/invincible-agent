"""THE GATEWAY HALF OF THE DIRECT PATH — executed, not merely written.

`_stream_direct_outcome` is the one piece of this feature that had NO test when it was
committed: the dispatch core is sealed six ways, and the generator that turns its outcome
into SSE and fills the artifact bundle had never run. That asymmetry is the dangerous
shape — a NameError or a wrong keyword in there does not degrade the turn, it RAISES inside
the SSE generator and takes the answer with it, for every pick, on the first request after
a roll.

Written before the BFF roll for exactly that reason. It stubs Engine F and asserts the
three things a person reads off the HUD on a fast answer:

    the routing record is present and non-empty
    the decision path names the verb the ask settled
    every stage that started reached a terminal

Run: uv run --frozen pytest tests/routing/test_the_direct_path_stream_actually_runs.py -v
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent import direct_dispatch as dd  # noqa: E402
from iagent_pure.routing_record import graph_trace_record, routing_record  # noqa: E402

_VERB = "mesh:costCategoryBreakdown"
_SUBJ = "http://invincible-agent/cost#CostCategory"
_ENDPOINT = "http://iagent-engine-cost.sandbox.svc:8097/measure/cost_category_breakdown"
_PAYLOAD = {"components": [{"archetype": "CHART_WIDGET", "subject_concept": _SUBJ}]}


def _outcome(kind=dd.ROUTED, engine_response=None):
    predicate = {
        "verb_iri": _VERB, "endpoint": _ENDPOINT, "owner_persona": "COST_ANALYST",
        "output_uri": "http://invincible-agent/cost#CategoryBreakdown",
    }
    common = dict(
        status="matched", subject_uri=_SUBJ, subject_confidence=1.0,
        subject_instance_id="urn:lot:4", subject_instance_label="Lot 4", verb_iri=_VERB,
        verb_confidence=1.0, classify_called=False, candidate_count=1,
        subject_candidates=[], fallback_reason="", eligibility_excluded=[],
        acting_persona="COST_ANALYST", acting_domains=["PRODUCTION_COST"],
        sub_query="where did the money go", predicate=predicate,
    )
    return dd.DirectOutcome(
        kind,
        reason="" if kind == dd.ROUTED else "engine did not answer: RuntimeError: 500",
        routing_mat=dd.materialization(**routing_record(**common)),
        graph_trace_mat=dd.materialization(**graph_trace_record(
            status="matched", subject_uri=_SUBJ, picked_verb_iri=_VERB,
            # THE FULL COMPAT RECORD, as `/find_compatible_verbs` returns it and as
            # `dispatch_pre_resolved` passes it through. A thin `{"verb_iri": ...}` stub
            # produced a one-node trace with no verb leg at all and looked like a code
            # defect; the projector draws the verb only through the OUTPUT node. A fixture
            # thinner than the real record tests a shape the system never produces.
            compatible_verbs=[{
                "verb_iri": _VERB, "verb_local": "costCategoryBreakdown",
                "input_uri": _SUBJ,
                "output_uri": "http://invincible-agent/cost#CategoryBreakdown",
                "endpoint_url": _ENDPOINT, "owner_persona": "COST_ANALYST",
                "domains": ["PRODUCTION_COST"], "arity": "set", "hops": 0,
            }],
        )),
        slots_mat=dd.materialization(
            verb_iri=_VERB, disposition="route", accepted_slots=json.dumps({"lot": 4}),
            refused_slots="[]", slot_resolution="{}", subject_uri=_SUBJ,
            owner_persona="COST_ANALYST",
        ),
        engine_response=engine_response if engine_response is not None else {
            "components": [{"rows": []}], "referenced_uris": ["urn:li:dataset:x"],
            "output_uri": "http://invincible-agent/cost#CategoryBreakdown",
        },
        predicate=predicate,
        accepted_params={"lot": 4},
    )


def _bundle():
    return {
        "id": "urn:li:answerArtifact:test", "question_text": "where did the money go",
        "message_id": "sess-1", "valid_as_of": int(time.time() * 1000) - 1000,
        "status": "pending",
        "produced_by": {"actor_type": "agent", "actor_id": "pending"},
        "produced_for": {"user_id": "u", "is_authenticated": True},
        "resolved_intent": {}, "routing": None, "sources": [], "graph_trace": [],
        "rendered_output": None, "derived_from_artifact_id": "urn:li:answerArtifact:ask",
    }


class _FakeEngineF:
    """Stands in for Engine F's /render_ui. `boom` makes the call fail."""

    def __init__(self, boom=False):
        self.boom, self.seen = boom, {}

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        self.seen = {"url": url, "body": json}
        if self.boom:
            raise RuntimeError("connection refused")
        return self

    def raise_for_status(self):
        return None

    def json(self):
        return _PAYLOAD

    @property
    def headers(self):
        return {"X-Presentation-Path": "archetype-hardened"}


async def _drain(outcome, bundle, *, boom=False, monkeypatch=None):
    import iagent.gateway as gw
    fake = _FakeEngineF(boom=boom)
    monkeypatch.setattr(gw.httpx, "AsyncClient", fake)
    events = []
    async for ev in gw._stream_direct_outcome(
        outcome=outcome, bundle=bundle, session_id="sess-1",
        frontend_id="cortex-ui-desktop", user_persona="COST_ANALYST",
    ):
        events.append(ev)
    return events, fake


def _parsed(events):
    """[(event_name, payload_dict), ...] from raw SSE frames."""
    out = []
    for raw in events:
        name = raw.split("event: ", 1)[1].split("\n", 1)[0]
        data = raw.split("data: ", 1)[1].rstrip("\n")
        out.append((name, json.loads(data)))
    return out


def _stages(parsed):
    return [(p["kind"], p["status"]) for n, p in parsed if n == "pipeline_stage"]


# ── it runs at all ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_routed_stream_RUNS_end_to_end(monkeypatch):
    """THE SMOKE TEST, and the reason this file exists. A NameError in this generator does
    not degrade the turn — it raises inside the SSE stream and takes the answer with it, for
    every pick, on the first request after a roll."""
    bundle = _bundle()
    events, fake = await _drain(_outcome(), bundle, monkeypatch=monkeypatch)
    names = [n for n, _ in _parsed(events)]
    assert "route_decision" in names and "graph_trace" in names
    assert "final_payload" in names
    assert fake.seen["url"].endswith("/render_ui")


@pytest.mark.asyncio
async def test_the_abstain_stream_RUNS_and_keeps_the_routing_record(monkeypatch):
    """The verb was right and the engine did not answer. The routing record is emitted
    FIRST, so the decision path still renders and a reader can see WHICH engine was asked —
    the whole difference between this and a blank failure."""
    bundle = _bundle()
    events, fake = await _drain(_outcome(dd.ABSTAIN), bundle, monkeypatch=monkeypatch)
    names = [n for n, _ in _parsed(events)]
    assert "route_decision" in names, "an abstain rendered with no decision path"
    assert "pipeline_error" in names
    assert "final_payload" not in names
    assert bundle["status"] == "failed"
    assert not fake.seen, "Engine F was called for a turn with no answer to render"


# ── the three things a person reads off the HUD ─────────────────────────────

@pytest.mark.asyncio
async def test_the_routing_record_reaches_the_BUNDLE_not_only_the_stream(monkeypatch):
    """The stream is delivery; the bundle is the artifact. A record emitted to one and not
    the other renders today and is absent when the canvas is reopened."""
    bundle = _bundle()
    await _drain(_outcome(), bundle, monkeypatch=monkeypatch)
    assert bundle["routing"], "the artifact carries no routing record"
    assert (bundle["routing"].get("about") or {}).get("uri") == _SUBJ
    assert bundle["graph_trace"], "the artifact carries no decision path"
    assert bundle["status"] == "complete"
    assert bundle["rendered_output"] == _PAYLOAD


@pytest.mark.asyncio
async def test_the_decision_path_names_the_verb_THE_ASK_SETTLED(monkeypatch):
    """Not a verb re-derived here — the one carried from the ask and re-confirmed against
    the compat walk. If these ever differ, the card is describing a different question."""
    bundle = _bundle()
    events, _ = await _drain(_outcome(), bundle, monkeypatch=monkeypatch)
    trace = next(p for n, p in _parsed(events) if n == "graph_trace")
    assert trace["nodes"], "the decision path is empty"
    # THE VERB REACHES THE PANEL ONLY THROUGH THE OUTPUT NODE'S `via_verb`, which is worth
    # asserting explicitly rather than by searching the blob: a verb registered with no
    # `output_uri` loses its leg silently and the path renders as a lone subject with no
    # error anywhere. Found by a fixture that omitted `output_uri`.
    via = [n.get("via_verb") for n in trace["nodes"] if n.get("via_verb")]
    assert via == [_VERB], (
        f"the decision path does not name the verb the ask settled: {trace['nodes']}"
    )


@pytest.mark.asyncio
async def test_handler_provider_is_FILLED_not_Unknown_engine(monkeypatch):
    """`handler_provider` empty makes the HUD render 'Unknown engine' beside a perfectly
    good endpoint. The shared builder derives it from the endpoint host when no provider is
    registered, and this asserts the value SURVIVES the projection into the artifact — the
    hop where a field that exists can still fail to arrive."""
    bundle = _bundle()
    await _drain(_outcome(), bundle, monkeypatch=monkeypatch)
    handled = bundle["routing"].get("handled_by") or {}
    assert handled, "the routing record names no handler"
    assert "iagent-engine-cost" in json.dumps(handled), (
        f"handler_provider did not reach the artifact: {handled}"
    )


@pytest.mark.asyncio
async def test_every_stage_that_starts_reaches_a_terminal(monkeypatch):
    """The same contract the dispatch core is held to, asserted on the GATEWAY's stages —
    which are emitted by different code and can strand a spinner just as well."""
    for kind, boom in ((dd.ROUTED, False), (dd.ROUTED, True), (dd.ABSTAIN, False)):
        bundle = _bundle()
        events, _ = await _drain(_outcome(kind), bundle, boom=boom, monkeypatch=monkeypatch)
        state: dict = {}
        for k, s in _stages(_parsed(events)):
            state[k] = s
        unterminated = [k for k, v in state.items() if v == "started"]
        assert not unterminated, f"{kind} boom={boom}: {unterminated} never finished"


@pytest.mark.asyncio
async def test_a_render_failure_FAILS_the_bundle_rather_than_completing_it(monkeypatch):
    """Engine F unreachable is not an answer. `status` must not reach 'complete', because
    the dispatch site refuses to write a bundle still marked 'pending' and would otherwise
    persist a complete artifact with no rendered output."""
    bundle = _bundle()
    events, _ = await _drain(_outcome(), bundle, boom=True, monkeypatch=monkeypatch)
    names = [n for n, _ in _parsed(events)]
    assert "pipeline_error" in names and "final_payload" not in names
    assert bundle["status"] == "failed"
    assert bundle["rendered_output"] is None


# ── what Engine F is actually asked ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_engine_f_gets_the_SAME_request_shape_the_run_builds(monkeypatch):
    """Engine F selects an archetype from `output_uri` and a chrome from `persona`, and
    reads the payload out of `raw_data`. A single-element list that omits `route_status` is
    the one shape neither the projector nor Engine F was ever tested on."""
    bundle = _bundle()
    _, fake = await _drain(_outcome(), bundle, monkeypatch=monkeypatch)
    body = fake.seen["body"]
    assert body["frontend_id"] == "cortex-ui-desktop"
    assert body["user_persona"] == "COST_ANALYST" and body["persona"] == "COST_ANALYST"
    assert body["output_uri"] == "http://invincible-agent/cost#CategoryBreakdown"
    assert len(body["raw_data"]) == 1
    row = body["raw_data"][0]
    assert row["route_status"] == "matched"
    assert row["predicate_verb_iri"] == _VERB
    # THE ENGINE'S OWN BODY, VERBATIM. Written first as
    # `row[...] is _outcome().engine_response or row[...]`, which is truthy whenever the
    # left side is non-empty and asserted nothing at all — `is` against a freshly built
    # object can never hold, so the `or` was carrying the whole test.
    assert row["expert_response"]["components"] == [{"rows": []}]


@pytest.mark.asyncio
async def test_the_engines_referenced_uris_reach_the_bindings_HUD(monkeypatch):
    bundle = _bundle()
    events, _ = await _drain(_outcome(), bundle, monkeypatch=monkeypatch)
    ctx = [p for n, p in _parsed(events) if n == "context_update"]
    assert ctx and ctx[0]["data"] == ["urn:li:dataset:x"]
