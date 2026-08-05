"""baml_shared telemetry — re-export shim over the provenance-telemetry leaf (ADR-0038).

The mesh's services import ``from telemetry import safe_observe, ...`` (baml_shared is
put on sys.path at startup). This shim keeps those imports working while routing the
real work to the standalone **provenance-telemetry** leaf — the same leaf doc-tools
uses — so the three repos share ONE emitter and ONE mapping shape.

REMOVAL MARKER: delete this shim once ALL THREE repos (iagent, doc-tools, cortex-*)
import ``provenance_telemetry`` directly. Until then the aliases at the bottom preserve
the old surface (safe_observe / safe_update_observation / get_langgraph_callbacks /
configure_litellm) through the expand/contract migration.

Fail-soft: when the leaf is not installed in a service's venv OR Langfuse is disabled,
every primitive is a no-op — the mesh runs identically with no telemetry dependency
(the witness-channel axiom: the observing channel must never break the observed work).
"""
import os
import functools  # noqa: F401 — kept: services may import it transitively via this module
from contextlib import contextmanager
from typing import Any, Callable

LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"))

# --- The leaf: the real implementation (optional per service venv) ------------
try:
    from provenance_telemetry import (  # noqa: F401
        traced,
        set_trace_standard,
        observed_trace,
        observe_span,
        litellm_metadata,
        redact,
        load_mapping,
    )

    _LEAF_AVAILABLE = True
except Exception:  # leaf not installed here -> pure no-ops, old surface still works
    _LEAF_AVAILABLE = False

    def traced(name=None, as_type=None):  # type: ignore[misc]
        def _deco(fn):
            return fn
        return _deco

    def set_trace_standard(*_a, **_k):  # type: ignore[misc]
        return None

    @contextmanager
    def observed_trace(*_a, **_k):  # type: ignore[misc]
        yield

    @contextmanager
    def observe_span(operation, **_attrs):  # type: ignore[misc]
        yield {"name": operation, "attributes": {}}

    def litellm_metadata(operation, **_k):  # type: ignore[misc]
        return {}

    def redact(value):  # type: ignore[misc]
        return value

    def load_mapping(_source):  # type: ignore[misc]
        return None


# --- The mesh mapping (doc-tools ships its own; this is iagent's vocabulary) ---
_MAPPING_PATH = os.path.join(os.path.dirname(__file__), "telemetry-mapping.yaml")
try:
    MAPPING = load_mapping(_MAPPING_PATH) if _LEAF_AVAILABLE else None
except Exception:  # a malformed/absent mapping -> API stays live, emits nothing
    MAPPING = load_mapping({}) if _LEAF_AVAILABLE else None


def build_trace_values(*, trace_id=None, authz_id=None, session_id=None, engine=None,
                       verb=None, domain=None, subject_class=None, resolved_via=None,
                       chart_version=None) -> dict:
    """The flat provenance dict projected onto a mesh trace at the entry boundary.

    SINGLE SOURCE OF TRUTH for which fields the mesh carries — the CI truth-check pins
    the mapping to these keys, so a dangling mapping entry or an unmapped field fails
    CI. build_sha/environment come from the deploy env (as in doc-tools). SCORES are
    NOT set here: they are emitted from the response (confidence/coherence) downstream.
    """
    return {
        "trace_id": trace_id,
        "authz_id": authz_id,
        "session_id": session_id,
        "build_sha": os.getenv("LANGFUSE_RELEASE"),   # deployed git SHA (trace release)
        "environment": os.getenv("DEPLOY_ENV"),       # sandbox|work|prod (trace tag)
        "engine": engine,                              # which mesh engine (A/D/E/O/W)
        "verb": verb,                                  # the routed verb IRI
        "domain": domain,
        "subject_class": subject_class,                # what the query resolved to
        "resolved_via": resolved_via,                  # the resolution rung (vector/graph/phonebook)
        "chart_version": chart_version or os.getenv("CHART_VERSION"),
    }


# --- Backward-compat surface: the mesh's existing `from telemetry import ...` ---
def safe_observe(**kwargs) -> Callable:
    """DEPRECATED alias for ``traced`` — kept so the mesh's existing decorators keep
    working during the migration (see REMOVAL MARKER). Passes through when disabled."""
    return traced(**kwargs)


def safe_update_observation(input_data: Any = None, output_data: Any = None):
    if LANGFUSE_ENABLED:
        try:
            from langfuse import get_client   # v4: update the current OTel span
            get_client().update_current_span(input=input_data, output=output_data)
        except Exception:  # noqa: BLE001 — telemetry never breaks the work
            pass


def get_langgraph_callbacks() -> list:
    if LANGFUSE_ENABLED:
        try:
            from langfuse.langchain import CallbackHandler   # v4 moved it here from langfuse.callback
            return [CallbackHandler()]
        except Exception:  # noqa: BLE001
            pass
    return []


def configure_litellm():
    """Configure LiteLLM's Langfuse success/failure callbacks if enabled."""
    if LANGFUSE_ENABLED:
        os.environ["LITELLM_SUCCESS_CALLBACKS"] = "langfuse"
        os.environ["LITELLM_FAILURE_CALLBACKS"] = "langfuse"


# Auto-configure LiteLLM on import (unchanged from the pre-leaf shim).
configure_litellm()
