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

logger = logging.getLogger("presentation_agent")

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


app = FastAPI(title="Engine F - Presentation Agent", lifespan=lifespan)

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


# Canonicalizer + lookup live in capabilities.py — see the import at
# the top of this file. Re-exported under the legacy underscore names.
try:
    from capabilities import (  # type: ignore[no-redef]
        canonical_iri_for_lookup as _canonical_iri_for_lookup,
        lookup_capability as _lookup_capability,
    )
except ImportError:
    from agent_fleet.presentation_agent.capabilities import (
        canonical_iri_for_lookup as _canonical_iri_for_lookup,
        lookup_capability as _lookup_capability,
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


# ADR-0017 follow-up: archetype-hardened renderers. Each maps a BAML
# archetype enum string to the matching RenderAs* function that
# RETURNS the specific archetype class (not the union). The LLM has
# no way to pick a different shape — the return type is constrained.
# DIGITAL_TWIN_3D is intentionally absent because it's not in the
# current capability table; if it lands, add RenderAsDigitalTwin
# alongside.
# Chart-data normalizer extracted to chart_normalizer.py (dep-free)
# so pure-unit tests can pin all five input shapes without dragging
# the FastAPI / BAML / uvicorn import chain.
try:
    from chart_normalizer import (  # type: ignore[no-redef]
        chart_data_is_empty as _chart_data_is_empty,
        honest_text_from_response as _honest_text_from_response,
        normalize_chart_data_to_recharts as _normalize_chart_data_to_recharts,
    )
except ImportError:
    from agent_fleet.presentation_agent.chart_normalizer import (
        chart_data_is_empty as _chart_data_is_empty,
        honest_text_from_response as _honest_text_from_response,
        normalize_chart_data_to_recharts as _normalize_chart_data_to_recharts,
    )


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
        if isinstance(baml_chart_data, str):
            normalized = _normalize_chart_data_to_recharts(baml_chart_data)
            if normalized is not None:
                component["chart_data"] = normalized

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
        if _chart_data_is_empty(component.get("chart_data")):
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

    # 3. ADR-0017: predicate-graph lookup. When the upstream agent
    # declared an output_uri (Engine A post-ADR-0017, Engine DA,
    # Engine W), look up the registered presentation capability and
    # dispatch deterministically.
    if request.output_uri:
        cap = _lookup_capability(request.output_uri)
        if cap:
            archetype = cap["archetype"]
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
