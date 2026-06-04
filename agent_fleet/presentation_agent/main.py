import json
import logging
from contextlib import asynccontextmanager
from enum import Enum
from typing import Dict, Any, Optional, Union, List
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn

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

    if isinstance(raw_data, dict):
        summary_text = (
            raw_data.get("summary")
            or raw_data.get("summary_text")
            or ""
        )
        structured = raw_data.get("structured_data")
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


@app.post("/render_ui")
async def render_ui(request: RenderRequest) -> Any:
    # 1. Stringify raw data safely
    if isinstance(request.raw_data, (dict, list)):
        str_raw_data = json.dumps(request.raw_data)
    else:
        str_raw_data = str(request.raw_data)

    # 2. Resolve persona — user_persona drives UI archetype selection.
    effective_persona = (request.user_persona or request.persona or "MECHANIC").upper()

    # 3. ADR-0017: predicate-graph lookup. When the upstream agent
    # declared an output_uri (Engine A post-ADR-0017, Engine DA, Engine
    # W), look up the registered presentation capability for that shape
    # and render deterministically. Otherwise fall through to the
    # legacy BAML DesignUI path so callers that haven't migrated still
    # work.
    if request.output_uri:
        cap = _lookup_capability(request.output_uri)
        if cap:
            archetype = cap["archetype"]
            logger.info(
                "render_ui: output_uri=%s matched capability archetype=%s",
                request.output_uri, archetype,
            )
            if archetype == "KNOWLEDGE_DOCUMENT":
                return _render_document_deterministic(
                    request.raw_data,
                    effective_persona,
                    subject_concept=request.output_uri,
                )
            # Non-document archetypes still go through BAML for now
            # because their pydantic shapes (TopologyUI nodes/edges,
            # HazardUI severity+hazards, MetricUI metrics, ChartUI
            # chart_data+sql_query, DigitalTwinUI) carry structured
            # subfields that BAML knows how to extract from raw data.
            # We pin the archetype choice via the persona string so the
            # BAML LLM no longer chooses freely — it just fills in.
            constrained_persona = (
                f"{effective_persona}::REQUIRED_ARCHETYPE={archetype}"
            )
            baml_response = await b.DesignUI(str_raw_data, constrained_persona)
            return baml_response.model_dump()
        logger.info(
            "render_ui: output_uri=%s did not match any capability; "
            "falling back to legacy BAML DesignUI",
            request.output_uri,
        )

    # 4. Legacy path: BAML LLM decides archetype.
    baml_response = await b.DesignUI(str_raw_data, effective_persona)

    return baml_response.model_dump()

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "engine": "F"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8087))
    uvicorn.run(app, host="0.0.0.0", port=port)
