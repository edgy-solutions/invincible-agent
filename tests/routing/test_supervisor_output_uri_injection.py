"""Pin the supervisor's output_uri injection — layer 4 of the
2026-06-25 chart-empty arc.

This is the lowest-trigger-frequency of the five tests written
alongside this work (the supervisor's injection logic is rarely
edited), but the contract is load-bearing: it's the bridge between
the routing decision (which knows the matched predicate's
output_uri) and the rendering dispatcher (which reads it from the
engine's response). Without injection, Engine F falls through to
legacy DesignUI; the normalizer never runs; the chart renders
empty.

The test pins four cases that together form the full contract:
inject when missing, never overwrite when present, no-op when the
predicate has nothing to give, no-op on non-dict responses. The
"engine echo wins" case is the one most likely to regress
accidentally — someone tightening the injection ("just always
inject from the predicate, it's authoritative") would silently
defeat ADR-0017's cheap-drift-detection mechanism, where Engine A's
echoed value is supposed to be comparable against the declared
value in audit. So this test isn't just a chart-empty regression
guard; it's the guard that injection respects the engine's voice
when the engine has one.
"""
from __future__ import annotations

from iagent_pure.predicate_routing import (
    inject_predicate_output_uri as _inject_predicate_output_uri,
)


_PREDICATE_OUTPUT_URI = "http://invincible-agent/mesh#DatasetAnalysisReport"
_ENGINE_ECHOED_URI = "http://invincible-agent/mesh#OwnershipFact"


def test_injects_when_engine_response_lacks_output_uri():
    """Engine DA/W/E don't echo output_uri. The supervisor's
    injection is what makes /render_ui's archetype dispatch fire.
    Without this, the c4b3ff7a chart-empty regression returns."""
    engine_response = {"status": "success", "data": "..."}
    predicate = {"verb_iri": "mesh:analyzeDataset", "output_uri": _PREDICATE_OUTPUT_URI}

    _inject_predicate_output_uri(engine_response, predicate)

    assert engine_response["output_uri"] == _PREDICATE_OUTPUT_URI


def test_engine_echo_wins_when_response_already_has_output_uri():
    """Engine A's smolagent IS prompted to echo output_uri in
    final_answer() — that's ADR-0017's cheap drift detection. If the
    supervisor overwrites it, the comparison "echoed vs declared"
    becomes vacuous and a misbehaving smolagent goes undetected.
    The injection MUST be no-op when the response already carries
    output_uri, regardless of whether the echo matches the
    predicate's declared value."""
    engine_response = {
        "status": "success",
        "data": "...",
        "output_uri": _ENGINE_ECHOED_URI,
    }
    predicate = {"verb_iri": "mesh:describeAsset", "output_uri": _PREDICATE_OUTPUT_URI}

    _inject_predicate_output_uri(engine_response, predicate)

    assert engine_response["output_uri"] == _ENGINE_ECHOED_URI, (
        "Engine echo was overwritten — ADR-0017 drift detection broken. "
        "The injection must NOT override what the engine already returned, "
        "even when the predicate has a different declared value."
    )


def test_no_op_when_predicate_has_no_output_uri():
    """Some predicates don't have output_uri (e.g., the engine-A
    generic fallback). Injection must not add a None or empty
    string, or downstream archetype lookup would try to canonicalize
    that and produce noisy logs at best."""
    engine_response = {"status": "success", "data": "..."}
    predicate = {"verb_iri": "mesh:something"}

    _inject_predicate_output_uri(engine_response, predicate)

    assert "output_uri" not in engine_response

    # Same with an explicit None/empty.
    engine_response_b = {"status": "success", "data": "..."}
    predicate_b = {"verb_iri": "mesh:something", "output_uri": ""}

    _inject_predicate_output_uri(engine_response_b, predicate_b)

    assert "output_uri" not in engine_response_b


def test_no_op_on_non_dict_response():
    """When a routing infra failure produces a non-dict (e.g., the
    engine returned a list, or _routing_unavailable was wrapped
    unexpectedly), injection must safely no-op rather than throw.
    The supervisor returns the engine_response verbatim either way;
    the test just confirms we don't crash on the weird-shape path."""
    predicate = {"verb_iri": "mesh:analyzeDataset", "output_uri": _PREDICATE_OUTPUT_URI}

    # Each should be safe — no exception.
    _inject_predicate_output_uri(None, predicate)
    _inject_predicate_output_uri([], predicate)
    _inject_predicate_output_uri("just a string", predicate)
    _inject_predicate_output_uri(42, predicate)
