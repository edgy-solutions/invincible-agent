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
import datetime
import functools  # noqa: F401 — kept: services may import it transitively via this module
import secrets
from contextlib import contextmanager
from typing import Any, Callable, Optional

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
        emit_misses,
        flush,
        mint_boundary_ids,
        boundary_parent,
        emit_boundary,
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

    def emit_misses():  # type: ignore[misc]
        # None = "this process has no telemetry leaf, so it emits nothing and cannot
        # miss" -- distinct from 0, which means a live leaf that has lost nothing.
        return None

    def flush():  # type: ignore[misc]
        return None

    def mint_boundary_ids(trace_seed=None):  # type: ignore[misc]
        return {"trace_id": None, "span_id": secrets.token_hex(8)}

    @contextmanager
    def boundary_parent(ids, *, mapping=None, values=None):  # type: ignore[misc]
        timing = {"started_at": datetime.datetime.now(datetime.timezone.utc),
                  "ended_at": None}
        try:
            yield timing
        finally:
            timing["ended_at"] = datetime.datetime.now(datetime.timezone.utc)

    def emit_boundary(mapping, values, *, ids, name, timing):  # type: ignore[misc]
        return None


# --- The mesh mapping (doc-tools ships its own; this is iagent's vocabulary) ---
_MAPPING_PATH = os.path.join(os.path.dirname(__file__), "telemetry-mapping.yaml")
try:
    MAPPING = load_mapping(_MAPPING_PATH) if _LEAF_AVAILABLE else None
except Exception:  # a malformed/absent mapping -> API stays live, emits nothing
    MAPPING = load_mapping({}) if _LEAF_AVAILABLE else None


def build_trace_values(*, trace_id=None, authz_id=None, session_id=None, engine=None,
                       verb=None, domain=None, subject_class=None, resolved_via=None,
                       chart_version=None, join_status=None) -> dict:
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
        # Legibility of a KNOWN join gap in the data itself (not just a handoff doc): a
        # restate engine whose trace id doesn't yet reach it tags itself so a reader sees the
        # orphan is by-limitation, not by-accident. None on the joined path -> no tag.
        "join_status": join_status,
    }


# --- Restate-replay-safe entry boundary (ADR-0038) ---------------------------
# ``observed_trace`` opens a RECORDING OTel span and mints a fresh span id on every
# entry. A Restate handler RE-ENTERS the ``with`` on every replay while the memoized
# ``ctx.run`` body does NOT re-execute -- so one execution of the work shows up as N
# boundary spans and the trace becomes the surface that lies (a cost reader sees
# doubled LLM spans and doubles the bill).
#
# The primitives (``mint_boundary_ids``, ``boundary_parent``, ``emit_boundary``) now
# live in the leaf, provenance-telemetry >= 0.2.0, and are re-exported here. The
# boundary span is exported by the leaf over OTLP; this shim no longer talks to the
# Langfuse ingestion API.
#
# WHAT CHANGED ON LANGFUSE v4 (Cloud is v4-only from 2026-11-16): the 2026-08-05 probe
# that found "the SAME observation id ingested TWICE collapses to ONE observation
# (upsert)" described the LEGACY ingestion API, and no longer holds. On v4 a second
# export of the same span id is a DUPLICATE. So ``emit_boundary`` must run exactly
# once, inside the journaled step; there is no dedup behind it.
#
# The replay-double is still ruled out by construction: ``boundary_parent`` makes the
# journaled ids a NON-RECORDING ambient parent (adopted by unmodified ``observe_span``
# / ``traced`` instrumentation, exporting nothing for itself), so re-entering it on a
# replay exports nothing. Passing ``mapping=`` and ``values=`` to ``boundary_parent``
# also propagates user / session / tags / metadata to the children, which is what v4
# filters on.
#
# Without the leaf installed, the stubs below emit nothing: ids carry no trace id,
# ``boundary_parent`` only times the block, ``emit_boundary`` returns None.
#
# KNOWN FUTURE ADOPTER -- Engine D (agent_fleet/data_analyst/main.py). D is a Restate
# handler that runs its agent work OUTSIDE any ctx.run, so replay re-executes the work
# for real and its boundary span count stays honest by accident: the doubling is absent
# only because the waste is genuine. Whoever gives D the durability it should have -- by
# wrapping that work in ctx.run -- INHERITS this hazard at the same moment, and D's
# current code is the reference they will copy, which will not show them.
#
# CONVENTION — which pattern applies when:
#   * a LEAF span (parents nothing) goes INSIDE ``ctx.run`` — see review_starter.py,
#     journaled once, never re-emitted;
#   * a PARENTING BOUNDARY uses these primitives — journaled ids, non-recording
#     ambient parent, boundary emitted from its own ``ctx.run``.

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
