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
import uuid
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
# ``ctx.run`` body does NOT re-execute — so one execution of the work shows up as N
# boundary spans and the trace becomes the surface that lies (a cost reader sees
# doubled LLM spans and doubles the bill).
#
# WHY HERE AND NOT IN THE LEAF: the hazard is a property of the EXECUTION MODEL, not
# of the emitter. provenance-telemetry is shared with doc-tools and cortex-*, neither
# of which is a Restate service. PLACEMENT MARKER: promote these three primitives into
# the leaf only if a non-mesh consumer acquires a replaying execution model.
#
# KNOWN FUTURE ADOPTER — Engine D (agent_fleet/data_analyst/main.py). D is a Restate
# handler that runs its agent work OUTSIDE any ctx.run, so replay re-executes the work
# for real and its boundary span count stays honest by accident: the doubling is absent
# only because the waste is genuine. Whoever gives D the durability it should have — by
# wrapping that work in ctx.run — INHERITS this hazard at the same moment, and D's
# current code is the reference they will copy, which will not show them. That fix must
# land on these primitives, not on `observed_trace`.
#
# Shape probed live against Langfuse cloud (SDK 4.14.2) on 2026-08-05:
#   * a caller-supplied 16-hex observation id is accepted and stored verbatim;
#   * the SAME observation id ingested TWICE collapses to ONE observation (upsert,
#     last write wins) — a re-emit is idempotent, not a duplicate;
#   * a child emitted BEFORE its parent exists still parents correctly (order-free);
#   * a NON-RECORDING ambient parent is adopted by unmodified ``observe_span`` /
#     ``traced`` instrumentation, and exports nothing for itself.
# Hence: journal the ids inside ctx.run, make them the ambient parent (which emits
# nothing, so replays cannot double), and emit the boundary observation itself from
# inside a ctx.run as well.
#
# CONVENTION — which pattern applies when:
#   * a LEAF span (parents nothing) goes INSIDE ``ctx.run`` — see review_starter.py,
#     journaled once, never re-emitted;
#   * a PARENTING BOUNDARY uses these primitives — journaled ids, non-recording
#     ambient parent, boundary emitted from its own ``ctx.run``.

def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt: Optional[datetime.datetime]) -> Optional[str]:
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def mint_boundary_ids(trace_seed: Optional[str] = None) -> dict:
    """Mint the boundary's identity: ``{"trace_id": 32-hex, "span_id": 16-hex}``.

    **Call inside ``ctx.run``** — that is what makes the pair JOURNALED, so Restate
    hands back the identical ids on every replay. ``trace_seed`` is the upstream id
    (X-Trace-Id / the request's ``trace_id``) so the mesh join still holds; with no
    seed a random trace id is minted once and then replayed from the journal.
    """
    ids = {"trace_id": None, "span_id": secrets.token_hex(8)}  # 16 lowercase hex
    if LANGFUSE_ENABLED:
        try:
            from langfuse import get_client
            ids["trace_id"] = get_client().create_trace_id(
                seed=str(trace_seed) if trace_seed else None
            )
        except Exception:  # noqa: BLE001 — telemetry never breaks the work
            pass
    return ids


@contextmanager
def boundary_parent(ids: dict):
    """Make the journaled ``(trace_id, span_id)`` the AMBIENT OTel parent — emitting
    NOTHING for the boundary itself.

    Everything opened inside nests under it through the ordinary OTel context, so
    existing ``observe_span``/``traced`` instrumentation needs no change. Because the
    span is non-recording, re-entering this block on a Restate replay exports nothing
    at all: the replay-double cannot occur by construction, not by later dedup.

    Yields a timing dict to hand to :func:`emit_boundary`.
    """
    timing: dict = {"started_at": _utcnow(), "ended_at": None}
    detach = None
    if LANGFUSE_ENABLED and ids.get("trace_id") and ids.get("span_id"):
        try:
            from opentelemetry import context as _octx, trace as _otr
            from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
            _tok = _octx.attach(_otr.set_span_in_context(NonRecordingSpan(SpanContext(
                trace_id=int(ids["trace_id"], 16),
                span_id=int(ids["span_id"], 16),
                is_remote=True,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            ))))
            detach = lambda: _octx.detach(_tok)  # noqa: E731
        except Exception:  # noqa: BLE001 — untraced beats broken
            detach = None
    try:
        yield timing
    finally:
        timing["ended_at"] = _utcnow()
        if detach is not None:
            try:
                detach()
            except Exception:  # noqa: BLE001
                pass


def emit_boundary(mapping, values: dict, *, ids: dict, name: str,
                  timing: dict) -> Optional[str]:
    """Emit the boundary observation itself, keyed on the JOURNALED span id.

    Returns the emitted span id so the ``ctx.run`` journal entry carries something
    legible (and serializable) rather than a bare ``None``.

    **Call inside ``ctx.run``** so it happens exactly once. Belt-and-suspenders: the
    ingestion API upserts on observation id, so even a re-emit lands one observation.

    Also emits the trace-level fields (``trace-create``). ``set_trace_standard`` writes
    those as attributes on the active RECORDING span; the boundary is deliberately
    non-recording now, so the trace body is their carrier instead. SCORES are not sent
    here — unchanged from ``set_trace_standard``, they are emitted from the response.

    If the handler dies between the work and this call the boundary never lands and the
    children show as roots on the right trace — a missing parent, never a phantom one.
    """
    if not LANGFUSE_ENABLED or not ids.get("trace_id") or not ids.get("span_id"):
        return None
    try:
        from langfuse import get_client
        content_bearing = set(getattr(mapping, "content_bearing", ()) or ())

        def project(field):
            v = values.get(field)
            if v is None:
                return None
            return redact(v) if field in content_bearing else v

        trace_body: dict = {"id": ids["trace_id"], "name": name}
        _slot_key = {"user_id": "userId", "session_id": "sessionId",
                     "release": "release", "version": "version"}
        for slot, field in (getattr(mapping, "slots", {}) or {}).items():
            if slot == "trace_id":
                continue
            key, val = _slot_key.get(slot), project(field)
            if key and val is not None:
                trace_body[key] = str(val)
        tags = [str(project(f)) for f in (getattr(mapping, "tags", ()) or ())
                if values.get(f) is not None]
        if tags:
            trace_body["tags"] = tags
        md = {f: project(f) for f in (getattr(mapping, "metadata", ()) or ())
              if values.get(f) is not None}
        if md:
            trace_body["metadata"] = md
        env = os.getenv("DEPLOY_ENV")
        if env:
            trace_body["environment"] = env

        stamp = _iso(_utcnow())
        span_body = {"id": ids["span_id"], "traceId": ids["trace_id"], "name": name,
                     "startTime": _iso(timing.get("started_at")),
                     "endTime": _iso(timing.get("ended_at")) or stamp}
        if env:
            span_body["environment"] = env

        get_client().api.ingestion.batch(batch=[
            {"id": str(uuid.uuid4()), "type": "trace-create",
             "timestamp": stamp, "body": trace_body},
            {"id": str(uuid.uuid4()), "type": "span-create",
             "timestamp": stamp, "body": span_body},
        ])
        return ids["span_id"]
    except Exception:  # noqa: BLE001 — the witness channel never breaks the work
        return None


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
