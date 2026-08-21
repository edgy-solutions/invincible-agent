"""Engine F's presentation-capability table + canonical IRI lookup.

Extracted to a dep-free module so pure-unit tests can import the
table and the lookup without dragging FastAPI / BAML / uvicorn /
Dagster. The router file (``main.py``) imports from here.

Why the split: the lookup table and the canonicalizer are the
contract that
``tests/routing/test_capability_lookup_canonical.py``
pins against the recurring compact-vs-full IRI hazard. The contract
is pure (URIs in → dict out); putting it next to FastAPI in
``main.py`` made unit tests collect-error on transitive imports of
``uvicorn`` / ``baml_client``. Same shape Engine A applies for its
verb registry (separated from the FastAPI layer for the same
reason).

The capability table itself stays the single source — ``main.py``
re-exports the lookup wrappers under their original underscored
names so the lifespan / render_ui code does not change.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Compact-prefix → full-IRI expansion. Mirrors the seed script's
# ``_MESH``/``_IDP`` discipline (canonical full-IRI form for subject /
# object URIs, compact-form for verbs). Any future namespace prefix
# added to the substrate must be mirrored here so the lookup stays
# canonicalization-safe.
_IRI_PREFIXES_FOR_LOOKUP: Dict[str, str] = {
    "mesh:": "http://invincible-agent/mesh#",
    "idp:": "http://invincible-agent/idp#",
}


def canonical_iri_for_lookup(iri: str) -> str:
    """Expand a compact-form CURIE to its full IRI; passthrough on full.

    Empty input maps to empty string so dict-lookup keys stay stable
    on optional / missing URIs. Unknown prefixes pass through
    verbatim — we won't fabricate an expansion we don't know.
    """
    if not iri:
        return ""
    for prefix, expansion in _IRI_PREFIXES_FOR_LOOKUP.items():
        if iri.startswith(prefix):
            return expansion + iri[len(prefix):]
    return iri


# Engine F's view of "which archetype should this output_uri render
# as." ADR-0017 §6 envisions this as an HTTP call to Engine O's
# /search_predicates; for the moment it's in-process so the
# additional network hop and the failure mode of Engine O being
# unreachable stay out of the render path. The triples ARE published
# to engine-o during lifespan startup (see main.py's lifespan),
# so the future swap is a one-function change.
#
# persona_fit and domain_fit are left empty in this initial table —
# the lookup ranks on subject+predicate match first. Persona-scoped
# competing triples (e.g. mesh:OwnershipFact → KNOWLEDGE_DOCUMENT for
# DATA_STEWARD vs → some-contact-card for OPS_OPERATOR) can be added
# as additional registrations without code changes here.
PRESENTATION_CAPABILITIES: list[Dict[str, Any]] = [
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


# ── `lookup_capability` REMOVED 2026-08-20 (ADR-0017 amendment, the seam) ──────────────
# The render-time lookup lived here and answered "what archetype for this output_uri?" from
# a hand-maintained table. It is replaced by `capability_registry.select_presentation`,
# which answers a better question -- "what archetype can THIS CALLER render that THIS
# PAYLOAD satisfies?" -- against menus the frontends register from their own component
# contracts. Anonymous callers get the DERIVED UNION of those menus, so no path reads a
# hand-maintained table any more.
#
# THE FILE SURVIVES because it has two OTHER jobs, and the acceptance that said "delete
# capabilities.py" had not separated them:
#   * PRESENTATION_CAPABILITIES drives Engine F's OWN startup registration of
#     (output_shape)-[mesh:rendersAs]->(archetype) triples into the mesh graph. That is the
#     presentation-as-predicate registration this ADR is named for -- the BACKEND
#     advertising to the GRAPH -- and it is a different concern from a UI's render menu.
#     Deleting the file would have silently stopped it.
#   * canonical_iri_for_lookup is the compact-vs-full IRI folding, still consumed by
#     main.py.
