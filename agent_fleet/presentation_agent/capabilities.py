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

import re
from typing import Any, Dict, Optional


# Compact-prefix → full-IRI expansion. Mirrors the seed script's
# ``_MESH``/``_IDP`` discipline (canonical full-IRI form for subject /
# object URIs, compact-form for verbs). Any future namespace prefix
# added to the substrate must be mirrored here so the lookup stays
# canonicalization-safe.
_IRI_PREFIXES_FOR_LOOKUP: Dict[str, str] = {
    "mesh:": "http://invincible-agent/mesh#",
    "idp:": "http://invincible-agent/idp#",
    # fin: (Engine F finance, ADR-0045). REQUIRED, and its absence fails SILENTLY: an
    # unknown prefix passes through verbatim BY DESIGN, so `fin:BurnRateSeries` would never
    # match the full IRI a payload carries and the archetype lookup would simply miss — a
    # card falling through to KNOWLEDGE_DOCUMENT with "No content available", which is
    # indistinguishable from having no binding at all.
    "fin:": "http://invincible-agent/fin#",
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


def capability_slug(subject_uri: str) -> str:
    """Turn a capability subject URI into a URN-safe slug for registration names.

    Strips ANY compact prefix, not just ``mesh:``. The slug lands INSIDE a DataHub URN --
    ``urn:li:mlModel:(urn:li:dataPlatform:mesh,presentation_<archetype>_for_<slug>,PROD)``
    -- where a colon is a URN DELIMITER. A prefix left in place is not untidy, it puts a
    structural character inside a URN component.

    This read ``.replace("mesh:", "")`` while every capability was a ``mesh:`` one, so the
    literal was indistinguishable from a general rule until Engine F (ADR-0045) registered
    the first ``fin:`` subjects and all six names came out as
    ``presentation_period_series_for_fin:burnrateseries``.

    IT LIVES HERE, NOT IN main.py, AND THAT IS THE ACTUAL REPAIR. main.py imports
    baml_client, so it cannot be imported outside the container and nothing under tests/
    could reach this function to assert on it. A `mesh:`-only literal in an untestable
    module is a bug with nowhere to write its own regression test; beside the table it
    names, it is one line of import away from covered.

    ⛔ BOTH SPELLINGS, AND NEITHER PREDECESSOR HANDLED BOTH. The presentation agent sends the
    COMPACT form (``fin:BurnRateSeries``); the gateway receives whatever a frontend declares and
    can see the FULL IRI. The first version here stripped a compact prefix and turned a full IRI
    into ``//invincible-agent/fin#burnrateseries``; the gateway's own copy did ``rsplit("#")``,
    correct on a full IRI and a NO-OP on a compact one — which is exactly how a colon reached a
    URN component. Two implementations, each correct on the input its author happened to have
    and each silently wrong on the other's. Fragment first, then any compact prefix.
    """
    local = subject_uri.rsplit("#", 1)[-1] if "#" in subject_uri else subject_uri
    return re.sub(r"^[a-z][a-z0-9]*:", "", local).lower()

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

    # ── ENGINE F (FINANCE) — ADR-0045. Added 2026-09-01. ────────────────────────────────
    #
    # THERE ARE TWO MENUS AND THIS IS ONLY ONE OF THEM. Measured on the live substrate
    # 2026-09-01, rendersAs rows by frontend_id:
    #
    #     cortex-ui-desktop     23 rows   <- what the card selector reads for cortex
    #     __system_default__    10 rows   <- THIS TABLE, written by this agent's startup
    #
    # This one is the UNIVERSAL FALLBACK: what an unknown client gets. cortex's menu is
    # written by the browser POST to /register_frontend_capabilities, which the gateway
    # converts into real graph registrations. So these six rows are NECESSARY AND NOT
    # SUFFICIENT for a finance card in cortex, and adding them here while believing they
    # fixed cortex would have been a fix aimed one menu to the left.
    #
    # ⛔ AN EARLIER COMMENT HERE SAID THAT ENDPOINT `only LOGS`, citing its own docstring
    # ("Stage 2 will plumb this into the SPO predicate graph"). THE DOCSTRING IS STALE and
    # the claim was wrong. What actually happened: 23 of 29 rows landed and the six fin:
    # ones were refused by Contract D, because the subject was emitted COMPACT — `fin:` was
    # missing from the prefix map above and an unknown prefix passes through verbatim. The
    # response was still `200 OK, accepted: 29, rejected: []`, because `rejected` counts
    # ADMISSION refusals and the graph failures never reach the response body.
    #
    # So the surviving lesson is sharper than the one that was written here first:
    # ACCEPTANCE AND MATERIALISATION ARE DIFFERENT CLAIMS, and the field named `rejected`
    # reports only one of the two ways a capability can be refused.
    #
    # Until these rows existed, every finance answer routed correctly, produced its output,
    # and rendered as "Knowledge Document — No content available".
    {
        "subject_uri": "fin:BurnRateSeries",
        "object_uri": "mesh:MultiSeries",
        "archetype": "MULTI_SERIES",
        "expected_fields": ["rows", "series", "value_label", "scope_label"],
        "description": "Renders fin:BurnRateSeries as a MULTI_SERIES — spend and the phased plan as two declared USD series over periods, with no cap",
    },
    {
        "subject_uri": "fin:FundingStatusGrid",
        "object_uri": "mesh:ShortfallGrid",
        "archetype": "SHORTFALL_GRID",
        "expected_fields": ["subject_id", "subject_name", "period", "required",
                            "committed", "secured", "shortfall", "state"],
        "description": "Renders fin:FundingStatusGrid as a SHORTFALL_GRID — authorized/obligated/expended per line per period",
    },
    {
        "subject_uri": "fin:PerformanceIndexSeries",
        "object_uri": "mesh:MultiSeries",
        "archetype": "MULTI_SERIES",
        "expected_fields": ["rows", "series", "value_label", "scope_label"],
        "description": "Renders fin:PerformanceIndexSeries as a MULTI_SERIES — CPI and SPI as two DIMENSIONLESS declared series; neither declares a unit, which is the assertion, not an omission",
    },
    {
        "subject_uri": "fin:VarianceDecomposition",
        "object_uri": "mesh:VarianceTree",
        "archetype": "VARIANCE_TREE",
        "expected_fields": ["level", "entity_id", "entity_name", "variance",
                            "share_of_root", "stop_reason", "contributors"],
        "description": "Renders fin:VarianceDecomposition as a VARIANCE_TREE — the only RECURSIVE payload here; `contributors` nests and `stop_reason` says why each branch ended",
    },
    {
        "subject_uri": "fin:VarianceDriverRanking",
        "object_uri": "mesh:ContributionRanking",
        "archetype": "CONTRIBUTION_RANKING",
        "expected_fields": ["rank", "entity_id", "entity_name", "contribution",
                            "share_of_total", "favourable", "value_unit"],
        "description": "Renders fin:VarianceDriverRanking as a CONTRIBUTION_RANKING — ordered contributors whose signed magnitudes sum to the variance they explain",
    },
    {
        "subject_uri": "fin:EstimateAtCompletion",
        "object_uri": "mesh:ForecastMeasure",
        "archetype": "FORECAST_MEASURE",
        "expected_fields": ["eac", "method", "formula", "vac", "etc", "bac",
                            "cpi", "spi", "value_unit"],
        "description": "Renders fin:EstimateAtCompletion as a FORECAST_MEASURE — the figure WITH its method and formula; a forecast drawn without its method re-creates the ambiguity the mandatory-method refusal just made the asker resolve",
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
