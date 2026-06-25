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

_PRESENTATION_CAPABILITIES = [
    # Engine A's six specific verbs (ADR-0017 §1).
    {
        "subject_uri": "mesh:OwnershipFact",
        "object_uri": "mesh:KnowledgeDocument",
        "archetype": "KNOWLEDGE_DOCUMENT",
        "expected_fields": ["asset_name", "owner_identity", "owner_team", "owner_since"],
        "description": "Renders mesh:OwnershipFact as a KNOWLEDGE_DOCUMENT panel",
    },
    {
        "subject_uri": "mesh:LineageTopology",
        "object_uri": "mesh:ProcessTopology",
        "archetype": "PROCESS_TOPOLOGY",
        "expected_fields": ["root_asset", "upstream_chain", "downstream_chain", "topology_depth"],
        "description": "Renders mesh:LineageTopology as a PROCESS_TOPOLOGY diagram",
    },
    {
        "subject_uri": "mesh:ImpactSet",
        "object_uri": "mesh:KnowledgeDocument",
        "archetype": "KNOWLEDGE_DOCUMENT",
        "expected_fields": ["root_asset", "impacted_assets", "impact_count"],
        "description": "Renders mesh:ImpactSet as a KNOWLEDGE_DOCUMENT table",
    },
    {
        "subject_uri": "mesh:SchemaDescription",
        "object_uri": "mesh:KnowledgeDocument",
        "archetype": "KNOWLEDGE_DOCUMENT",
        "expected_fields": ["asset_name", "columns"],
        "description": "Renders mesh:SchemaDescription as a KNOWLEDGE_DOCUMENT column table",
    },
    {
        "subject_uri": "mesh:FreshnessReport",
        "object_uri": "mesh:AssetStateMetric",
        "archetype": "ASSET_STATE_METRIC",
        "expected_fields": ["asset_name", "last_updated", "sla_status", "staleness_hours"],
        "description": "Renders mesh:FreshnessReport as an ASSET_STATE_METRIC widget",
    },
    {
        # PII-flavored default. Persona-scoped triples (compliance vs
        # general tag listing) are a follow-up.
        "subject_uri": "mesh:TagFilterResult",
        "object_uri": "mesh:HazardDeclaration",
        "archetype": "HAZARD_DECLARATION",
        "expected_fields": ["tag", "matched_assets", "secondary_condition"],
        "description": "Renders mesh:TagFilterResult as a HAZARD_DECLARATION (PII-flavored default)",
    },
    {
        "subject_uri": "mesh:AssetProfile",
        "object_uri": "mesh:KnowledgeDocument",
        "archetype": "KNOWLEDGE_DOCUMENT",
        "expected_fields": ["asset_name", "owner", "tags", "domain", "description", "last_updated"],
        "description": "Renders mesh:AssetProfile as a KNOWLEDGE_DOCUMENT profile card",
    },
    {
        # Catalog enumeration (mesh:enumerateCatalog verb). Renders as
        # KNOWLEDGE_DOCUMENT so the deterministic-document path composes
        # markdown from summary_text + a fenced JSON block of the
        # `tables` list — the right shape for a flat catalog listing.
        # WITHOUT this entry the router fell back to mesh:traceLineage
        # which forces output_uri=mesh:LineageTopology and routes to
        # PROCESS_TOPOLOGY (BPMN canvas). See ADR-0017 §1 and the run
        # 5fee663d post-mortem.
        "subject_uri": "mesh:CatalogListing",
        "object_uri": "mesh:KnowledgeDocument",
        "archetype": "KNOWLEDGE_DOCUMENT",
        "expected_fields": ["scope", "tables", "asset_count"],
        "description": "Renders mesh:CatalogListing as a KNOWLEDGE_DOCUMENT flat enumeration",
    },
    # Engine DA — DatasetAnalysisReport renders as a chart.
    {
        "subject_uri": "mesh:DatasetAnalysisReport",
        "object_uri": "mesh:ChartWidget",
        "archetype": "CHART_WIDGET",
        "expected_fields": ["dataset_id", "metrics", "viz_type"],
        "description": "Renders mesh:DatasetAnalysisReport as a CHART_WIDGET",
    },
    # Engine W — KnowledgeRetrievalResponse renders as a document.
    {
        "subject_uri": "mesh:KnowledgeRetrievalResponse",
        "object_uri": "mesh:KnowledgeDocument",
        "archetype": "KNOWLEDGE_DOCUMENT",
        "expected_fields": ["query", "documents", "scores"],
        "description": "Renders mesh:KnowledgeRetrievalResponse as a KNOWLEDGE_DOCUMENT",
    },
]


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


def _lookup_capability(output_uri: str) -> Optional[Dict[str, Any]]:
    """In-memory predicate lookup over Engine F's own capability table.

    ADR-0017 §6 envisions this as an HTTP call to Engine O's
    /search_predicates with subject=output_uri and
    predicate=mesh:rendersAs. The capability triples are already
    advertised (see lifespan above) so that endpoint will see them.
    For tonight's rollout we look up the same data in-process —
    same registry, same matches, no network hop. The TODO is to
    replace this body with the HTTP call once Engine O grows a
    presentation-aware lookup endpoint; consumers of /render_ui
    don't change.
    """
    for cap in _PRESENTATION_CAPABILITIES:
        if cap["subject_uri"] == output_uri:
            return cap
    return None


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
def _normalize_chart_data_to_recharts(raw_data: Any) -> Optional[str]:
    """Coerce an arbitrary chart payload into the exact shape
    ``cortex-ui/src/components/mesh/ChartWidget.tsx`` reads:
    a JSON-stringified array of ``{"name": str, "value": number}``
    objects.

    Why this lives here rather than in the BAML prompt: the widget
    hardcodes ``dataKey="name"`` and ``dataKey="value"`` on its
    Recharts ``<XAxis>`` and ``<Bar>``. That's the real contract —
    only the React component knows the required keys. Asking the
    LLM (RenderAsChart's prompt) to rename keys to ``name``/``value``
    works *probably* but leaves shape-conformance to a model that can
    hallucinate field names on weird inputs and silently empty the
    chart. The §1 principle the project has converged on
    everywhere else applies: **LLMs produce data, deterministic
    steps conform shape.** Chart-data shape is a deterministic
    transform; it does not need an LLM.

    Accepts the three shapes Engine DA's smolagent typically returns:

    * dict-of-counts/measures: ``{"US-East": 3, "US-West": 2, ...}``
      → category=key, measure=value.
    * list-of-records with named fields:
      ``[{"region": "US-East", "count": 3}, ...]``
      → first non-numeric field is category, first numeric field is
      measure.
    * already-normalized ``[{"name": "...", "value": ...}, ...]``
      → returned unchanged.

    Returns the JSON-stringified array on success, ``None`` when the
    payload doesn't look like chart data (the caller falls back to
    letting BAML do its best, preserving the prior behavior for
    unrecognized shapes).
    """
    import numbers
    import re

    payload: Any = raw_data
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            # Sometimes DA's smolagent returns Python-repr (single
            # quotes) rather than JSON — try a quick coerce so we
            # don't fall through to the LLM for a recoverable input.
            try:
                # Only attempt the coerce if the string really looks
                # like a Python dict/list literal — never eval arbitrary
                # text.
                if re.match(r"^\s*[\[{].*[\]}]\s*$", payload, re.S):
                    payload = json.loads(payload.replace("'", '"'))
                else:
                    return None
            except Exception:
                return None

    # Shape 1: dict-of-counts/measures.
    if isinstance(payload, dict):
        rows = [
            {"name": str(k), "value": v}
            for k, v in payload.items()
            if isinstance(v, numbers.Number) and not isinstance(v, bool)
        ]
        if rows:
            return json.dumps(rows)
        return None

    if not isinstance(payload, list) or not payload:
        return None

    # Shape 3 first: already-normalized.
    if all(
        isinstance(r, dict) and "name" in r and "value" in r
        for r in payload
    ):
        return json.dumps([{"name": str(r["name"]), "value": r["value"]} for r in payload])

    # Shape 2: list of records with named fields. Pick category =
    # first non-numeric field, measure = first numeric field. This is
    # deterministic on the row schema, independent of the LLM's
    # choice of field names.
    if not all(isinstance(r, dict) for r in payload):
        return None

    first = payload[0]
    category_key = next(
        (k for k, v in first.items()
         if not isinstance(v, numbers.Number) or isinstance(v, bool)),
        None,
    )
    measure_key = next(
        (k for k, v in first.items()
         if isinstance(v, numbers.Number) and not isinstance(v, bool)),
        None,
    )
    if category_key is None or measure_key is None:
        return None
    return json.dumps(
        [
            {"name": str(r[category_key]), "value": r[measure_key]}
            for r in payload
            if category_key in r and measure_key in r
        ]
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
    if archetype == "CHART_WIDGET":
        normalized = _normalize_chart_data_to_recharts(
            raw_data if raw_data is not None else str_raw_data
        )
        if normalized is not None:
            component["chart_data"] = normalized

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
