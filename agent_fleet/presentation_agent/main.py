import json
import logging
from contextlib import asynccontextmanager
from enum import Enum
from typing import Dict, Any, Optional, Tuple, Union, List
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
import uvicorn

# ADR-0017 follow-up: presentation-path labels emitted on
# X-Presentation-Path response header and recorded by cortex-bff /
# the ADR-0015 audit table when it lands. Keep these strings stable —
# they are the values an alert/canary would match on.
PRESENTATION_PATH_DETERMINISTIC = "deterministic-document"
PRESENTATION_PATH_ARCHETYPE_HARDENED = "archetype-hardened"
PRESENTATION_PATH_FALLBACK_DESIGNUI = "fallback-designui"
PRESENTATION_PATH_FALLBACK_NO_OUTPUT_URI = "fallback-no-output-uri"
# A DECLARED non-answer, rendered on purpose (2026-08-15). Deliberately a DIFFERENT path from
# the CHART_WIDGET honest fallback, which INFERS a non-answer from an empty payload. Both end
# in a document, so collapsing them would be tempting and would destroy the one measurement
# that matters here: this path firing means the engine DECLARED it could not ground, while the
# fallback firing means nobody declared anything and the shape had to be guessed at. If the
# inference path keeps firing after the engines declare, something upstream is still silent.
PRESENTATION_PATH_DECLARED_UNGROUNDED = "declared-ungrounded"

# Statuses that mean "no answer was produced, and the producer SAYS SO". Rendered deliberately
# rather than inferred from an empty payload.
#
# `ungrounded` and `engine_unreachable` are kept DISTINCT upstream even though both land here,
# because they are different facts about the world: one is a working system honestly declining,
# the other is an outage. The renderer treats them alike TODAY — both produce a document
# explaining what happened — and the vocabulary is preserved so a consumer that should treat
# them differently (an alert, a retry, a status page) can, without re-deriving the difference
# from prose. Flattening at the boundary would be the one-field-for-two-outcomes defect that
# caused this work, committed a second time.
#
# NOT included: `access_denied`, which has its own richer path (request-access affordance), and
# `error`, which is an agent-loop fault rather than a declared non-answer.
DECLARED_NON_ANSWER_STATUSES = frozenset({"ungrounded", "engine_unreachable"})

from baml_client import b

# Initialize runtime BAML configuration logic
try:
    from llm_utils import init_baml_client
    b = init_baml_client(b)
except ImportError:
    try:
        from agent_fleet.llm_utils import init_baml_client
        b = init_baml_client(b)
    except ImportError:
        pass

# Mesh-registration helper — Engine F advertises its presentation
# capabilities as (output_uri, mesh:rendersAs, archetype) triples in
# the predicate graph (ADR-0017 §5). The Dockerfile flattens the
# fleet directory differently in image vs dev, so try both paths.
try:
    from utils.mesh_registration import register_presentation_to_mesh
except ImportError:
    from agent_fleet.utils.mesh_registration import register_presentation_to_mesh

# Give THIS module's logger its own stdout handler so its INFO records survive
# uvicorn's logging reconfiguration at startup. A bare logging.basicConfig here
# emits nothing under uvicorn: uvicorn replaces the root handler basicConfig
# installs, so every logger.info was dropped — including the ADR-0030
# edgeless-topology degrade line, leaving only uvicorn's own access logs. A
# handler attached to the NAMED "presentation_agent" logger (with propagate off
# so it doesn't also hit uvicorn's root) is untouched by that reconfig and
# always emits.
logger = logging.getLogger("presentation_agent")
if not logger.handlers:
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(_log_handler)
logger.setLevel(logging.INFO)
logger.propagate = False

# ---------------------------------------------------------------------------
# Presentation capability table (ADR-0017 §5)
# ---------------------------------------------------------------------------
# Each entry advertises a (subject, mesh:rendersAs, object) triple for
# the predicate graph, plus the BAML archetype enum string and the
# fields Engine F expects to find in structured_data when populating
# the archetype.
#
# persona_fit and domain_fit are left empty in this initial table —
# the lookup ranks on subject+predicate match first. Persona-scoped
# competing triples (e.g. mesh:OwnershipFact → KNOWLEDGE_DOCUMENT for
# DATA_STEWARD vs → some-contact-card for OPS_OPERATOR) can be added
# as additional registrations without code changes here.

# Capability table + lookup helpers extracted to capabilities.py (dep-
# free) so pure-unit tests can pin them without dragging the FastAPI /
# BAML / uvicorn import chain. Re-exported under the legacy underscore
# names so the lifespan / render_ui code below does not change.
#
# Three import shapes, same as utils.mesh_registration above: the
# container's Dockerfile flattens agent_fleet/presentation_agent/
# into /app/ and runs main.py as a flat script (no package context),
# so the FIRST fallback must be the flat ``capabilities`` import; dev
# checkout uses the agent_fleet.* path.
try:
    from capabilities import (  # type: ignore[no-redef]
        PRESENTATION_CAPABILITIES as _PRESENTATION_CAPABILITIES,
    )
except ImportError:
    from agent_fleet.presentation_agent.capabilities import (
        PRESENTATION_CAPABILITIES as _PRESENTATION_CAPABILITIES,
    )


def _capability_slug(subject_uri: str) -> str:
    """Turn a subject URI into a URN-safe slug for registration names."""
    return subject_uri.replace("mesh:", "").lower()


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    logger.info("Engine F: registering presentation capabilities (ADR-0017).")
    for cap in _PRESENTATION_CAPABILITIES:
        try:
            register_presentation_to_mesh(
                name=f"presentation_{cap['archetype'].lower()}_for_{_capability_slug(cap['subject_uri'])}",
                description=cap["description"],
                subject_uri=cap["subject_uri"],
                object_uri=cap["object_uri"],
                archetype=cap["archetype"],
                expected_fields=cap["expected_fields"],
            )
        except Exception as e:  # noqa: BLE001  -- ADR-0006: never crash on registration
            logger.warning(
                "Failed to register presentation capability %s: %s. "
                "/render_ui will fall back to legacy BAML DesignUI for "
                "this shape until the next successful registration cycle.",
                cap["subject_uri"], e,
            )
    yield
    logger.info("Engine F: shutting down.")


# Telemetry (ADR-0038): join Engine F's work to the caller's trace. telemetry.py is at /app
# in the fleet image; guarded so the engine runs identically when the shim/leaf is absent.
try:
    from telemetry import observed_trace, MAPPING, build_trace_values
except Exception:  # pragma: no cover — telemetry never load-bearing
    from contextlib import contextmanager as _cm

    @_cm
    def observed_trace(*_a, **_k):
        yield

    def build_trace_values(**_k):
        return {}

    MAPPING = None

from fastapi import Depends
# TRANSPORT AUTH (OBSERVE). One implementation, from the mesh membership package: validate
# whatever arrives, log the caller posture per request, REFUSE NOTHING until
# REQUIRE_TRANSPORT_AUTH flips. The announcement is the pre-positioned string the contract
# phase's fresh-deploy test asserts against — an engine that takes the dependency but loses
# the announcement has a real posture the gauge cannot read.
from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth
_announce_transport_auth(component="engine-f")
app = FastAPI(
    **_docs_kwargs(),  # /docs,/redoc,/openapi.json OFF in deployment (Starlette-bypass class)
    dependencies=[Depends(_transport_auth("engine-f"))], title="Engine F - Presentation Agent", lifespan=lifespan)


@app.middleware("http")
async def _telemetry_join(request: Request, call_next):
    # ADR-0038: join this engine to the CALLER's trace (X-Trace-Id from discovery.py) so every
    # endpoint nests under it. Fail-soft; no-op without a trace id / when disabled.
    tid = request.headers.get("X-Trace-Id")
    if not tid:
        return await call_next(request)
    with observed_trace(MAPPING, build_trace_values(
        trace_id=tid, engine="presentation_agent", verb=request.url.path,
    ), name="engine-f " + request.url.path):
        return await call_next(request)

class RenderRequest(BaseModel):
    raw_data: Union[Dict[str, Any], List[Dict[str, Any]], str]
    # Per ADR-0009 persona split: UI archetype is a *user-side* concern
    # ("what chrome should I render for this caller?"), distinct from the
    # *answerer* persona that lives on each subtask's response. We accept
    # both fields and prefer user_persona; fall back to legacy `persona`
    # for callers that haven't migrated.
    user_persona: Optional[str] = None
    persona: Optional[str] = None
    # ADR-0017: cortex-bff forwards the agent's declared output_uri so
    # Engine F can do a deterministic predicate-graph lookup instead of
    # asking the BAML LLM to classify the data shape. When this is
    # missing or no capability triple matches, fall back to legacy
    # BAML.DesignUI.
    output_uri: Optional[str] = None
    domain: Optional[str] = None
    # ADR-0017 amendment: which frontend will render this. Present -> select from THAT
    # client's registered menu. Absent -> the global capability table, i.e. today's
    # behaviour, so unidentified callers do not regress while the callers migrate.
    frontend_id: Optional[str] = None


# Canonicalizer + lookup live in capabilities.py — see the import at
# the top of this file. Re-exported under the legacy underscore names.
try:
    from capabilities import (  # type: ignore[no-redef]
        canonical_iri_for_lookup as _canonical_iri_for_lookup,
    )
except ImportError:
    from agent_fleet.presentation_agent.capabilities import (
        canonical_iri_for_lookup as _canonical_iri_for_lookup,
    )


def _extract_agent_response(raw_data: Any) -> Optional[Dict[str, Any]]:
    """Extract the agent's response dict from the shape cortex-bff sends.

    cortex-bff's supervisor wraps each subtask's result in
    ``{persona, user_persona, answerer_persona, predicate_verb_iri,
    sub_query, expert_response}`` and passes the LIST of those wrappers
    as ``raw_data``. The agent's actual response (summary,
    structured_data, output_uri, etc.) is inside ``expert_response``
    of the first entry whose output_uri matches.

    Test callers (e.g. ``trigger_presentation_agent``) pass a plain
    dict instead. Handle both: if raw_data is already the response
    shape (has ``summary`` or ``structured_data`` keys), use it
    directly.
    """
    if isinstance(raw_data, list) and raw_data:
        first = raw_data[0]
        if isinstance(first, dict):
            expert = first.get("expert_response")
            if isinstance(expert, dict):
                return expert
            # Bare dict at the top level (legacy/test shape).
            if "summary" in first or "structured_data" in first:
                return first
    if isinstance(raw_data, dict):
        if "expert_response" in raw_data:
            expert = raw_data["expert_response"]
            return expert if isinstance(expert, dict) else None
        return raw_data
    return None


def _render_document_deterministic(
    raw_data: Any,
    persona: str,
    subject_concept: Optional[str],
) -> Dict[str, Any]:
    """Hand-construct a DashboardUI with a single DocumentUI.

    Skips BAML entirely when the chosen archetype is KNOWLEDGE_DOCUMENT
    (5 of 9 capabilities). markdown_content is composed from the
    agent's summary text plus a fenced JSON block of the structured
    data, so all the answer content is preserved regardless of shape.
    The LLM's choice of archetype is gone — the predicate lookup is
    the choice.
    """
    summary_text = ""
    structured: Any = None

    agent_response = _extract_agent_response(raw_data)
    if agent_response is not None:
        summary_text = (
            agent_response.get("summary")
            or agent_response.get("summary_text")
            or ""
        )
        structured = agent_response.get("structured_data")
        if isinstance(structured, str):
            try:
                structured = json.loads(structured)
            except (ValueError, TypeError):
                pass

    parts: List[str] = []
    if summary_text:
        parts.append(str(summary_text))
    if structured is not None:
        parts.append("```json\n" + json.dumps(structured, indent=2) + "\n```")
    markdown_content = "\n\n".join(parts) if parts else "No content available."

    return {
        "components": [
            {
                "archetype": "KNOWLEDGE_DOCUMENT",
                "source_persona": persona,
                "subject_concept": subject_concept,
                "markdown_content": markdown_content,
            }
        ]
    }


def _degrade_edgeless_topology_to_document(
    raw_data: Any, persona: str
) -> Optional[Dict[str, Any]]:
    """ADR-0030 rule 2: a deterministic ``LineageTopology`` is EDGELESS BY
    DESIGN and must render as a document, not a graph.

    The deterministic traceLineage branch (Engine A, ADR-0030 / D4) computes
    the selected upstream set in code and writes the summary FROM it, then
    emits a ``LineageTopology`` whose ``structured_data`` carries an explicit
    ``outcome`` discriminant and (because a platform filter crosses
    intermediate hops) usually no edges. Forcing that through
    ``RenderAsTopology`` is the ORIGINAL bug: the renderer is asked to draw a
    graph from data with no edges, so the model INVENTS edges and the
    oversized prompt times out (a list is not a graph).

    Key on the DISCRIMINANT, never on "edges happens to be empty" — a genuine
    but sparse graph would also be edgeless. When ``outcome`` is present the
    answer already decided its own honest shape (list / none / couldnt_locate
    / ambiguous / unrecognized_platform / lineage_error), all of which read
    correctly as the already-written summary. When it is absent, this is a
    real topology graph and belongs to ``RenderAsTopology`` — return None.
    """
    resp = _extract_agent_response(raw_data)
    if not isinstance(resp, dict):
        return None
    sd = resp.get("structured_data")
    if isinstance(sd, str):
        try:
            sd = json.loads(sd)
        except (ValueError, TypeError):
            sd = None
    summary = resp.get("summary") or resp.get("summary_text") or ""
    doc = _edgeless_lineage_document(sd, summary, persona)
    if doc is not None:
        logger.info(
            "render_ui: edgeless LineageTopology outcome=%s matched=%s -> "
            "KNOWLEDGE_DOCUMENT (ADR-0030 rule 2; renderer bypassed, no "
            "invented edges, no graph-of-a-list timeout).",
            (sd or {}).get("outcome"), (sd or {}).get("match_count"),
        )
    return doc


# ADR-0017 follow-up: archetype-hardened renderers. Each maps a BAML
# archetype enum string to the matching RenderAs* function that
# RETURNS the specific archetype class (not the union). The LLM has
# no way to pick a different shape — the return type is constrained.
# DIGITAL_TWIN_3D is intentionally absent because it's not in the
# current capability table; if it lands, add RenderAsDigitalTwin
# alongside.
# SLICE 2c: chart_normalizer.py is GONE. Its coercion was dead compensation for a widget
# behaviour that no longer exists; its renderable/not decision is now contract validation;
# and its honest-text extractor -- correct code in the wrong file -- moved to
# honest_fallback.py. Flatten-aware imports, same shape as before.
try:
    from capability_registry import select_presentation as _select_presentation  # type: ignore[no-redef]
    from capability_validator import validate_chart_payload as _validate_chart_payload  # type: ignore[no-redef]
    from honest_fallback import honest_text_from_response as _honest_text_from_response  # type: ignore[no-redef]
except ImportError:
    from agent_fleet.presentation_agent.capability_registry import (
        select_presentation as _select_presentation,
    )
    from agent_fleet.presentation_agent.capability_validator import (
        validate_chart_payload as _validate_chart_payload,
    )
    from agent_fleet.presentation_agent.honest_fallback import (
        honest_text_from_response as _honest_text_from_response,
    )


def _render_declared_ungrounded(
    agent_response: Dict[str, Any],
    persona: str,
    subject_concept: Optional[str],
) -> Dict[str, Any]:
    """Render a run whose producer DECLARED it could not answer — a state, not a failure.

    Three things this deliberately does NOT do:

    * **It does not re-derive the explanation.** The engine's own prose is usually the better
      sentence ("I couldn't locate a URN for the publog p_cage dataset"), so it renders
      verbatim and the typed `message` is a prefix, not a replacement. Same
      synthesis-is-theater rule the honest fallback already follows.
    * **It does not call BAML.** There is nothing to shape. An LLM asked to present a
      non-answer will improvise one, which is the failure this whole item is about.
    * **It does not pretend to be an error.** An ungrounded run is a correct, honest outcome
      of a working system; the user needs to know the answer is not backed by data, not that
      something broke. (`engine_unreachable` IS a fault, and says so in its own message.)

    The `reason` is surfaced because the cases have different user actions: an unresolved URN
    may mean the asset is absent or the phrasing was ambiguous (rephrasing helps); a resolved
    URN whose query never completed is an infrastructure problem (rephrasing does not).
    """
    engine_text = _honest_text_from_response(agent_response) or ""
    typed_message = agent_response.get("message") or "This question could not be grounded to data."
    reason = agent_response.get("reason") or ""

    parts: List[str] = [f"**{typed_message}**"]
    # Only append the engine's own words when they add something beyond the typed line.
    if engine_text and engine_text.strip() != str(typed_message).strip():
        parts.append(str(engine_text))
    if reason == "query_never_succeeded":
        parts.append(
            "_The dataset was identified but no query completed against it, so this is a "
            "data-access problem rather than a phrasing one._"
        )
    elif reason == "no_urn_resolved":
        parts.append(
            "_No dataset was matched for this question — it may not be in the catalog, or "
            "the question may need to name the asset more specifically._"
        )

    return {
        "components": [
            {
                "archetype": "KNOWLEDGE_DOCUMENT",
                "source_persona": persona,
                "subject_concept": subject_concept,
                "markdown_content": "\n\n".join(parts),
            }
        ]
    }


# ADR-0030 rule 2: the edgeless-LineageTopology → document decision, kept in a
# dep-free sibling so it unit-tests without the FastAPI/BAML chain (same split
# as chart_normalizer above). Flatten-aware import.
try:
    from topology_degrade import (  # type: ignore[no-redef]
        edgeless_lineage_document as _edgeless_lineage_document,
    )
except ImportError:
    from agent_fleet.presentation_agent.topology_degrade import (
        edgeless_lineage_document as _edgeless_lineage_document,
    )



# ── PLANNING ARCHETYPES: DETERMINISTIC HARDENED RENDERERS (ADR-0042) ─────────
#
# These five archetypes are projected, NOT generated. The rows arrive from
# Engine P already typed against a declared output_uri, and every cortex-ui
# contract for them explicitly forbids interpretation ("NOT re-derive
# risk_flag", "NOT infer grouping from the ids", "NOT treat '(none)' as missing
# data"). A model in this path has nothing to decide and one thing to get wrong.
#
# MEASURED, 2026-08-24, which is why this is deterministic rather than a fifth
# RenderAs* call: the DesignUI fallback rendered plan_schedule's 14 rows as
# "CHART DATA NOT RENDERABLE - no numeric column" on one request and drew them
# cleanly on the next. Same measure, same rows, opposite outcomes, because the
# chart shape was being guessed per request. A beat that worked in rehearsal can
# fail in the room, with no change anywhere -- a nondeterministic component on
# the demo's critical path, in a project that pre-registers every other number.
#
# The precedent for a model-free hardened arm is in-repo: ADR-0030 rule 2
# intercepts an edgeless LineageTopology BEFORE RenderAsTopology and returns
# (component, handled=True) with no BAML call, because the model could only
# invent edges the payload already answered. Same argument, wider blast radius.
#
# Free consequences, both measured today: the DesignUI call cost 31-59s per card
# (~14% of a 280s question), and it sent portfolio funding figures to whatever
# `client MainAgent` resolved to -- a fallback chain whose FIRST entry is
# OpenRouter. Projection deletes both.
#: output_uri -> (archetype, payload key, extra passthrough fields)
_PLANNING_ARCHETYPES: Dict[str, tuple] = {
    # `milestones` joined the passthrough on 2026-08-25, when mesh:ContributionSequence
    # bound to this archetype. WITHOUT IT the projector silently drops the markers and the
    # capability path renders as a plain schedule — the bars are all correct and the ANSWER
    # ("does this land before the plateau date?") is simply absent, which is the hardest
    # shape of failure to notice because nothing looks broken.
    "INTERVAL_TIMELINE": ("rows", ("group_kind", "scope_label", "milestones")),
    "PERIOD_SERIES": ("rows", ("scope_label", "value_unit")),
    "THRESHOLD_GRID": ("rows", ("value_label", "scope_label")),
    "MATRIX_GRID": ("rows", ("level_label", "scope_label", "as_of")),
    "DELTA_SET": ("effects", ("scope_label", "baseline_label", "headline")),
    # CANVAS_SEED is the odd one and deliberately so: its payload is a list of
    # ARTIFACT IDS (strings), not a list of row objects. cortex's recogniser —
    # canvasSeedFromArtifact in src/lib/canvasSeedFromAnswer.ts — declares the
    # shape and is the single edit point if it ever changes:
    #
    #     { archetype: "CANVAS_SEED", canvas_type?: string, name?: string,
    #       artifact_ids: string[] }
    #
    # ORDER IS THE DECLARATION. Position 0 lands in the full-width anchor and
    # the client never sorts, so the projection must not reorder or dedupe.
    #
    # BOTH OPTIONAL FIELDS ARE CARRIED AND NEITHER ARRIVES TODAY — a carrier, not an
    # assertion. `name` has a real reader but no producer fact (the phrase path has no
    # spoken name, and defaulting one here would invent it). `canvas_type` is the
    # reverse: declared in cortex's contract but read by nothing, so emitting it would
    # be a producer-side write with no consumer. Listing them here costs nothing and
    # asserts nothing; passthrough carries only what a producer actually wrote.
    "CANVAS_SEED": ("artifact_ids", ("canvas_type", "name")),
    # Landed by Lane 1 the same night as this build (SHORTFALL_GRID — "funding
    # gap needs three quantities, not two"). It is the binding for
    # mesh:FundingGapSet, whose absence made "where is funding short by
    # initiative" fall through to KNOWLEDGE_DOCUMENT and answer
    # "No content available." Picked up here because the arm is mechanical
    # once the contract exists.
    "SHORTFALL_GRID": ("rows", ("value_label", "value_unit", "scope_label")),
}


def _project_planning_archetype(
    archetype: str,
    raw_data: Any,
    persona: str,
    subject_concept: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Project Engine P rows into a planning archetype's declared shape.

    Returns None when the payload carries no rows -- the caller then degrades,
    because an EMPTY planning card is a refusal, not an answer (the
    IntervalTimeline contract says so explicitly: "A schedule with no rows is a
    refusal, not an empty answer -- a plan with nothing in it is a broken scope
    filter").

    Rows pass through VERBATIM. Every field the contract declares beyond `rows`
    is carried only if the producer supplied it; nothing is defaulted, inferred
    or invented, because each of those is a named prohibition in the contracts.
    """
    spec = _PLANNING_ARCHETYPES.get(archetype)
    if spec is None:
        return None
    payload_key, passthrough = spec

    resp = _extract_agent_response(raw_data) or {}
    # LOOK FOR THE ARCHETYPE'S OWN KEY FIRST. Measure verbs answer under
    # `structured_data`; an ORCHESTRATION answers under its own name — the seed
    # returns {"artifact_ids": [...]} at the top level, and looking only for
    # structured_data would read that as an empty answer and degrade a
    # perfectly good seed into "nothing to draw".
    rows = resp.get(payload_key)
    if rows is None:
        rows = resp.get("structured_data")
    if rows is None:
        rows = resp.get("rows")
    if isinstance(rows, dict):
        # Some producers wrap rows beside their framing fields.
        for k in (payload_key, "rows", "structured_data"):
            if isinstance(rows.get(k), list):
                resp = {**resp, **rows}
                rows = rows[k]
                break
    if not isinstance(rows, list) or not rows:
        return None

    # ROWS GO OVER AS AN ARRAY, NOT A JSON STRING.
    #
    # Every planning contract declares `encoding: "array", parsesTo:
    # "array-of-objects"`. CHART_WIDGET is the ONE EXCEPTION — its contract says
    # of chart_data: "NOT an array. A STRING containing JSON that parses to an
    # array of objects... the single most surprising fact in the whole
    # contract." That warning exists precisely so nobody generalises from it.
    #
    # The first version of this arm did generalise from it, and shipped
    # json.dumps(rows). The component then hit `!Array.isArray(rows)` in
    # validateIntervalTimeline and drew its contract refusal — "nothing to draw
    # / no scheduled work in scope" — over fourteen perfectly good rows. The
    # component was right and the payload was wrong: a schedule with no rows IS
    # a refusal, and a JSON string is, to that check, no rows.
    component: Dict[str, Any] = {
        "archetype": archetype,
        "source_persona": persona,
        "subject_concept": subject_concept,
        payload_key: rows,
    }
    for field in passthrough:
        val = resp.get(field)
        if val is None and isinstance(rows[0], dict):
            # `group_kind` rides the ROWS for the timeline (the verb stamps it
            # per row); the contract says it is stated, never inferred, so we
            # only lift a value the producer actually wrote.
            val = rows[0].get(field)
        if val is not None:
            component[field] = val

    # THE FRESHNESS PAIR, CARRIED FOR EVERY ARCHETYPE — deliberately not a per-archetype
    # passthrough entry. `state_ref`/`state_version` are properties of the EVALUATION, not of
    # any one card's shape, so putting them in the per-archetype lists would mean remembering
    # to add them five times and forgetting once. That is the exact mistake this morning's
    # producer seal was written to stop, twelve hours ago.
    #
    # `SemanticInterpreter.tsx` has been reading `comp.state_version` and handing it to six
    # components this whole time. It was `undefined` for every planning card, because the
    # producer emitted it on the envelope and this function never carried it across. Same
    # seam that swallowed the axis keys today.
    #
    # `is not None`, NEVER a truthiness test. Baseline's version is legitimately `0`, and
    # `if val:` would drop it — every baseline card would report no version at all while
    # scenario cards worked, which reads as "the feature is broken for some cards" rather
    # than as the one-character bug it is.
    for field in ("state_ref", "state_version"):
        val = resp.get(field)
        if val is not None:
            component[field] = val

    return component


async def _render_archetype_hardened(
    archetype: str,
    str_raw_data: str,
    persona: str,
    raw_data: Any = None,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Dispatch to the right RenderAs* BAML function for the chosen
    archetype. Returns (components_dict, handled). handled=False means
    no hardened function exists for this archetype and the caller
    should fall back to legacy DesignUI.

    For CHART_WIDGET, the chart_data field is conformed
    deterministically AFTER the BAML call (overrides whatever keys the
    LLM produced with the widget's required ``{name, value}`` shape).
    The LLM is still responsible for chart_type inference and
    sql_query pass-through — what it can't be trusted to do reliably
    is rename keys to match a hardcoded React contract.
    """
    # A renderer FAILURE takes the same path as a renderer ABSENCE:
    # `handled=False` -> the caller degrades to legacy DesignUI.
    #
    # WHY THIS TRY/EXCEPT EXISTS. "hardened" in this function's name means
    # SHAPE-hardened (the CHART_WIDGET key conformance below), not
    # FAILURE-hardened. Without this guard any exception from the BAML
    # call propagates out of /render_ui as a 500, the supervisor's
    # generate_ui_payload does raise_for_status(), the Dagster step FAILS,
    # and the user gets a BLANK CARD -- even though the answer was already
    # fully computed by the specialist. Observed live (work 2026-07-20): a
    # lineage answer was retrieved correctly, then RenderAsTopology hit a
    # 60s LLM timeout (408 from the gateway) and destroyed the completed
    # answer on the way out.
    #
    # The presentation layer is COSMETIC. It must never be able to lose a
    # computed answer. Degrading to a plainer rendering is always better
    # than returning nothing, so every failure mode here -- timeout,
    # gateway 5xx, parse/validation error -- degrades instead of raising.
    #
    # Deliberately NOT retried here: the archetype renderers are large
    # structured generations, so a retry doubles worst-case latency before
    # the user sees anything, and the fallback is both faster and
    # guaranteed to produce output. A repeated warning here is the signal
    # that the renderer's timeout budget is too tight for this archetype.
    # ADR-0030 rule 2: intercept a deterministic (edgeless) LineageTopology
    # BEFORE the graph renderer runs. Keyed on the outcome discriminant, this
    # never reaches RenderAsTopology — so the model can't invent edges from an
    # edgeless payload and the oversized-prompt timeout can't fire. A genuine
    # graph (no discriminant, or real edges) falls through to the renderer.
    if archetype == "PROCESS_TOPOLOGY":
        degraded = _degrade_edgeless_topology_to_document(raw_data, persona)
        if degraded is not None:
            return degraded, True

    # PLANNING ARCHETYPES ARE PROJECTED, NOT GENERATED. Before any model call:
    # these five have structured rows and contracts that forbid interpretation,
    # so a deterministic projection is both correct and the only way the card
    # renders the same way twice. See _project_planning_archetype.
    if archetype in _PLANNING_ARCHETYPES:
        projected = _project_planning_archetype(
            archetype, raw_data, persona, subject_concept=None,
        )
        if projected is not None:
            # WRAP IT. Every other return from this function hands back
            # {"components": [...]} — the DashboardUI envelope the projection
            # writer and the client both read. Returning the bare component
            # here shipped `{rows, archetype, group_kind, ...}` into
            # rendered_output, so `rendered_output?.components` was undefined,
            # `components` became [], `hasRendered` went false, and StageCard
            # drew its honest empty summary over a payload that was completely
            # correct. The selector had chosen INTERVAL_TIMELINE, the rows were
            # verbatim and intact — the ENVELOPE was lost, not the content.
            # Caught 2026-08-25 by comparing a working artifact's top-level
            # keys (`components`) against a failing one's (`rows, archetype,
            # group_kind, ...`).
            return {"components": [projected]}, True
        logger.warning(
            "render_ui: %s carried no rows; degrading. An empty planning card "
            "is a refusal, not an answer.", archetype,
        )
        return None, False

    try:
        if archetype == "PROCESS_TOPOLOGY":
            ui = await b.RenderAsTopology(str_raw_data, persona)
        elif archetype == "HAZARD_DECLARATION":
            ui = await b.RenderAsHazard(str_raw_data, persona)
        elif archetype == "ASSET_STATE_METRIC":
            ui = await b.RenderAsMetric(str_raw_data, persona)
        elif archetype == "CHART_WIDGET":
            ui = await b.RenderAsChart(str_raw_data, persona)
        else:
            return None, False
    except Exception as exc:  # noqa: BLE001 - cosmetic layer, never fatal
        logger.warning(
            "render_ui: hardened renderer for archetype=%s FAILED "
            "(%s: %s). Degrading to legacy DesignUI so the already-computed "
            "answer still reaches the user. If this repeats for the same "
            "archetype, the renderer's LLM timeout budget is too tight for "
            "the payload size -- raise it rather than letting every such "
            "query fall back.",
            archetype, type(exc).__name__, exc,
        )
        return None, False

    component = ui.model_dump()

    # Deterministic shape conformance for CHART_WIDGET. The widget's
    # required keys (``name`` / ``value``) are hardcoded in
    # ChartWidget.tsx's dataKey props; this normalization lives at
    # the source-of-truth boundary the LLM cannot drift from.
    #
    # We normalize the BAML-emitted ``chart_data`` (which the LLM
    # already extracted from the wrapped supervisor payload into a
    # list of records) — NOT the raw_data the caller passed in. The
    # raw_data may be the supervisor's full ``results`` list (one
    # entry per subtask, ``expert_response`` nested), and the
    # normalizer can't find chart-shaped data inside that wrapper.
    # The LLM does the extraction; we conform the keys.
    if archetype == "CHART_WIDGET":
        baml_chart_data = component.get("chart_data")
        # UNRENDERABLE IS NOT THE SAME AS EMPTY, and only one of them had a branch.
        # `chart_data_is_empty` catches `[]` — the query returned nothing. It does NOT
        # catch a payload with rows the widget cannot draw: CAGE codes are identifiers,
        # so `[{"name":"cage","value":"00000"}]` is non-empty AND has no measure. The
        # normalizer declines it (returns None), the empty-check says "not empty", no
        # fallback fires, and a CORRECT ANSWER sitting in the payload is discarded while
        # the UI shows "CHART DATA NOT RENDERABLE". Witnessed at work 2026-08-15: the
        # data path worked end to end and the presentation layer threw the values away.
        #
        # So both conditions route to the same honest degradation below — the rule this
        # system runs on everywhere else, which was simply missing a branch.
        # SLICE 2c: VALIDATE against the component's published contract; never COERCE.
        # The normalizer reshaped chart_data into {name, value} because the widget was
        # believed to hardcode those dataKeys. It infers them, so the coercion was
        # information-destroying -- multi-series and scatter payloads were flattened
        # before they arrived, and nothing failed, which is why it went unnoticed.
        # The question is no longer "can I reshape this?" (whose "no" discarded payloads
        # the COMPONENT could draw -- witnessed at work 2026-08-15) but "does this satisfy
        # the contract the component published?". chart_data is passed through untouched.
        chart_unrenderable = False
        _refusal = _validate_chart_payload(
            baml_chart_data, component.get("chart_type")
        )
        if _refusal is not None:
            chart_unrenderable = True
            logger.info(
                "render_ui: CHART_WIDGET payload does not satisfy the contract "
                "(%s) -> honest fallback rather than an undrawable widget",
                _refusal,
            )

        # HONEST FALLBACK (structural, not inference). When the chart came back
        # with NO renderable rows (the query produced nothing, or the SQL errored
        # and the agent recovered) AND the agent already wrote an honest text
        # answer, render THAT text as a KNOWLEDGE_DOCUMENT — so the honesty the
        # pipeline already computed reaches the user, instead of an empty widget
        # that reads as a malfunction ("CHART DATA NOT RENDERABLE"). Keyed on the
        # payload's SHAPE (empty chart_data + a present final_answer/summary),
        # never an LLM "does this look like a refusal". _render_document_
        # deterministic carries the agent's `summary` VERBATIM and drops the
        # failed sql_query — so the failure-path payload is coherent (it doesn't
        # ship a failed query as if it had executed).
        # "no rows" is now one of the contract's refusal reasons, so the separate
        # empty-check is subsumed by the validation above.
        if chart_unrenderable:
            honest_text = _honest_text_from_response(_extract_agent_response(raw_data))
            if honest_text:
                logger.info(
                    "render_ui: CHART_WIDGET empty + agent text present -> "
                    "KNOWLEDGE_DOCUMENT honest fallback (subject=%s)",
                    component.get("subject_concept"),
                )
                return (
                    {
                        "components": [
                            {
                                "archetype": "KNOWLEDGE_DOCUMENT",
                                "source_persona": persona,
                                "subject_concept": component.get("subject_concept"),
                                # DA's final_answer VERBATIM (synthesis-is-theater —
                                # the honest text exists; render it, don't re-derive).
                                # No sql_query -> the failure-path payload is coherent.
                                "markdown_content": honest_text,
                            }
                        ]
                    },
                    True,
                )

    return {"components": [component]}, True


@app.post("/render_ui")
async def render_ui(request: RenderRequest, response: Response) -> Any:
    """Render the agent's response into a UI shape.

    Three paths, chosen deterministically by the predicate-graph
    capability table (see ADR-0017) and the agent's declared
    output_uri:

    - **deterministic-document**: KNOWLEDGE_DOCUMENT capabilities.
      Hand-constructed; no LLM at all.
    - **archetype-hardened**: PROCESS_TOPOLOGY / HAZARD_DECLARATION /
      ASSET_STATE_METRIC / CHART_WIDGET capabilities. Dispatched to
      the matching RenderAs* BAML function whose return type is the
      specific archetype class — the LLM populates fields but cannot
      pick a different shape.
    - **fallback-designui** / **fallback-no-output-uri**: legacy
      DesignUI runs free archetype choice. This is the path that
      ADR-0017 is replacing; alerting on its hit-rate is the point of
      the X-Presentation-Path header below.

    Every response carries an `X-Presentation-Path` header naming
    which of the four paths served the request, so cortex-bff (or
    the ADR-0015 audit table when it lands) can record it and a
    canary can alert when fallback-* exceeds threshold.
    """
    # 1. Stringify raw data safely.
    if isinstance(request.raw_data, (dict, list)):
        str_raw_data = json.dumps(request.raw_data)
    else:
        str_raw_data = str(request.raw_data)

    # 2. Resolve persona — user_persona drives UI archetype selection.
    effective_persona = (request.user_persona or request.persona or "MECHANIC").upper()

    # 2b. A DECLARED NON-ANSWER IS RENDERED ON PURPOSE, BEFORE ANY ARCHETYPE QUESTION.
    #
    # Upstream of the capability lookup deliberately: "which shape should this answer take" is
    # the wrong question about a run that produced no answer. Previously an ungrounded run
    # arrived wearing `status: "success"`, matched CHART_WIDGET on its `output_uri`, produced no
    # rows (correctly), and reached a document only by FALLBACK — so the honest outcome was
    # reconstructed from an empty payload three layers after the engine already knew it.
    #
    # Now the producer says so and this reads it. The inference path below is retained as a
    # safety net for producers that have not adopted the vocabulary, but it is no longer the
    # mechanism.
    _declared = _extract_agent_response(request.raw_data)
    if isinstance(_declared, dict) and _declared.get("status") in DECLARED_NON_ANSWER_STATUSES:
        response.headers["X-Presentation-Path"] = PRESENTATION_PATH_DECLARED_UNGROUNDED
        logger.info(
            "render_ui: producer DECLARED a non-answer (status=%s reason=%s) -> rendered "
            "deliberately, no archetype selected",
            _declared.get("status"), _declared.get("reason") or "unspecified",
        )
        return _render_declared_ungrounded(_declared, effective_persona, request.output_uri)

    # 3. ADR-0017: predicate-graph lookup. When the upstream agent
    # declared an output_uri (Engine A post-ADR-0017, Engine DA,
    # Engine W), look up the registered presentation capability and
    # dispatch deterministically.
    if request.output_uri:
        # ── THE SEAM: select from the CALLER'S registered menu when it names itself ─────
        # An identified frontend gets menu-scoped selection (filter by output_uri, keep
        # only what the payload satisfies, rank by the published affinities). An
        # unidentified one keeps the global table -- today's behaviour -- so nothing
        # regresses while callers migrate. Wiring this with frontend_id=None instead would
        # resolve EVERY caller to the labelled default menu and turn every answer into a
        # KNOWLEDGE_DOCUMENT: a regression that looks like completion.
        # THE REGISTRY IS THE SINGLE SOURCE FOR EVERY PATH. An identified caller selects
        # from its own menu; an anonymous one selects from the DERIVED UNION of registered
        # menus (labelled `default-menu`). capabilities.py -- the hand-maintained backend
        # copy that used to serve this fallback -- is deleted: every row it held is now
        # derived from a component contract on the UI side, so keeping it meant the
        # fallback drifted the day a contract changed with nothing pinning them equal.
        cap = None
        if True:
            _agent_resp = _extract_agent_response(request.raw_data) or {}
            _sel_payload = {
                "chart_data": _agent_resp.get("data"),
                "chart_type": None,
            }
            cap, _sel_prov = _select_presentation(
                request.frontend_id, request.output_uri, _sel_payload,
                persona=effective_persona, domain=request.domain,
            )
            logger.info(
                "render_ui: menu-scoped selection frontend_id=%s source=%s basis=%s -> %s",
                request.frontend_id,
                _sel_prov.get("presentation_source"),
                _sel_prov.get("selection_basis"),
                (cap or {}).get("archetype") or _sel_prov.get("reason"),
            )
            if cap is None:
                # The caller's menu cannot draw this. Honest text beats a widget it never
                # advertised -- and the provenance above says WHICH refusal produced it.
                response.headers["X-Presentation-Path"] = PRESENTATION_PATH_DETERMINISTIC
                return _render_document_deterministic(
                    request.raw_data, effective_persona,
                    subject_concept=request.output_uri,
                )
        if cap:
            archetype = cap["archetype"]
            # ── SLICE 4: THE DATA GETS A VOTE ─────────────────────────────────────────
            # `output_uri` is a candidate FILTER, not a verdict. Chosen from the output
            # type alone, every analyzeDataset result became a CHART_WIDGET -- including a
            # list of CAGE codes, which are IDENTIFIERS and can never be plotted. The
            # honest-degradation half shipped 2026-08-15, so the viewer saw the text; the
            # system still CHOSE WRONG and then recovered. This is the half that stops the
            # wrong choice being made.
            #
            # Checked against the payload ALREADY IN HAND (the agent's rows), before the
            # BAML render -- which is the whole point, since the previous code decided the
            # shape and only then produced data to put in it.
            if archetype == "CHART_WIDGET":
                _agent_resp = _extract_agent_response(request.raw_data) or {}
                _rows = _agent_resp.get("data")
                _refusal = _validate_chart_payload(_rows, None, cap.get("contract"))
                if _refusal is not None:
                    logger.info(
                        "render_ui: output_uri=%s maps to CHART_WIDGET but the payload "
                        "does not satisfy its contract (%s) -> KNOWLEDGE_DOCUMENT. The "
                        "data decides the shape; output_uri is a hint.",
                        request.output_uri, _refusal,
                    )
                    response.headers["X-Presentation-Path"] = PRESENTATION_PATH_DETERMINISTIC
                    return _render_document_deterministic(
                        request.raw_data,
                        effective_persona,
                        subject_concept=request.output_uri,
                    )
            logger.info(
                "render_ui: output_uri=%s matched capability archetype=%s",
                request.output_uri, archetype,
            )
            if archetype == "KNOWLEDGE_DOCUMENT":
                response.headers["X-Presentation-Path"] = PRESENTATION_PATH_DETERMINISTIC
                return _render_document_deterministic(
                    request.raw_data,
                    effective_persona,
                    subject_concept=request.output_uri,
                )
            hardened, handled = await _render_archetype_hardened(
                archetype, str_raw_data, effective_persona,
                raw_data=request.raw_data,
            )
            if handled:
                response.headers["X-Presentation-Path"] = PRESENTATION_PATH_ARCHETYPE_HARDENED
                return hardened
            logger.warning(
                "render_ui: no hardened renderer for archetype=%s; "
                "falling back to legacy DesignUI. Add RenderAs<X> to "
                "contracts.baml + _render_archetype_hardened dispatch.",
                archetype,
            )
        else:
            logger.info(
                "render_ui: output_uri=%s did not match any capability; "
                "falling back to legacy BAML DesignUI",
                request.output_uri,
            )
        response.headers["X-Presentation-Path"] = PRESENTATION_PATH_FALLBACK_DESIGNUI
        baml_response = await b.DesignUI(str_raw_data, effective_persona)
        return baml_response.model_dump()

    # 4. No output_uri at all. Legacy callers; LLM decides archetype.
    response.headers["X-Presentation-Path"] = PRESENTATION_PATH_FALLBACK_NO_OUTPUT_URI
    baml_response = await b.DesignUI(str_raw_data, effective_persona)
    return baml_response.model_dump()

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "engine": "F"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8087))
    uvicorn.run(app, host="0.0.0.0", port=port)
