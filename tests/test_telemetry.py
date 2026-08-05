import os
import sys
import pytest
import importlib
from pathlib import Path

# Add baml_shared to Python path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_BAML_SHARED_PATH = _REPO_ROOT / "baml_shared"
if str(_BAML_SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(_BAML_SHARED_PATH))

import telemetry

def test_safe_observe_no_langfuse(monkeypatch):
    """Test that safe_observe acts as a pass-through when Langfuse is disabled."""
    # Ensure langfuse is disabled
    monkeypatch.setattr(telemetry, "LANGFUSE_ENABLED", False)
    
    @telemetry.safe_observe(name="test_func")
    def dummy_func(x, y):
        return x + y
        
    assert dummy_func(2, 3) == 5

def test_safe_update_observation_no_langfuse(monkeypatch):
    """Test that safe_update_observation does not crash when Langfuse is disabled."""
    monkeypatch.setattr(telemetry, "LANGFUSE_ENABLED", False)
    # Should not raise any exception
    telemetry.safe_update_observation(input_data="test", output_data="result")

def test_get_langgraph_callbacks_no_langfuse(monkeypatch):
    """Test that get_langgraph_callbacks returns an empty list when Langfuse is disabled."""
    monkeypatch.setattr(telemetry, "LANGFUSE_ENABLED", False)
    callbacks = telemetry.get_langgraph_callbacks()
    assert callbacks == []

def test_configure_litellm_no_langfuse(monkeypatch):
    """Test that configure_litellm does not set env vars when Langfuse is disabled."""
    monkeypatch.setattr(telemetry, "LANGFUSE_ENABLED", False)
    monkeypatch.delenv("LITELLM_SUCCESS_CALLBACKS", raising=False)
    monkeypatch.delenv("LITELLM_FAILURE_CALLBACKS", raising=False)
    
    telemetry.configure_litellm()

    assert "LITELLM_SUCCESS_CALLBACKS" not in os.environ
    assert "LITELLM_FAILURE_CALLBACKS" not in os.environ


# --- Leaf shim (ADR-0038): the provenance-telemetry primitives are re-exported -----

def test_leaf_primitives_are_exported():
    """The shim exposes the leaf's surface so services can migrate off safe_* onto it."""
    for name in ("traced", "set_trace_standard", "observe_span", "litellm_metadata",
                 "redact", "build_trace_values"):
        assert hasattr(telemetry, name), f"telemetry.{name} missing from the shim"


def test_traced_and_set_trace_standard_are_no_op_when_disabled(monkeypatch):
    """With Langfuse off (and/or the leaf absent) the new primitives never raise and
    never change behaviour — the witness-channel axiom."""
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)

    @telemetry.traced(name="unit")
    def work(x):
        return x * 2
    assert work(21) == 42

    # A missing mapping / disabled emit must be a silent no-op, not an exception.
    telemetry.set_trace_standard(telemetry.MAPPING, telemetry.build_trace_values(
        trace_id="t", authz_id="svc:x", engine="restate_analyst"))


def test_mesh_mapping_truth_check():
    """Truth tier: the mesh mapping names ONLY fields build_trace_values produces.
    The leaf validates the mapping's shape; this pins its field names to the code."""
    pytest.importorskip("provenance_telemetry")
    from provenance_telemetry import load_mapping

    m = load_mapping(str(_BAML_SHARED_PATH / "telemetry-mapping.yaml"))
    provided = set(telemetry.build_trace_values(
        trace_id="t", authz_id="svc:review-starter", session_id="s",
        engine="restate_analyst", verb="mesh:answerQuestion", domain="SUSTAINMENT",
        subject_class="pcn:ChangeNotice", resolved_via="graph", chart_version="0.3.26"))
    mapped = set(m.slots.values()) | set(m.tags) | set(m.metadata) | set(m.scores)
    assert not (mapped - provided), f"mapping names fields with no provider: {sorted(mapped - provided)}"
    assert not (provided - mapped), f"build_trace_values emits unmapped fields: {sorted(provided - mapped)}"
