"""Predicate-registry view-functions (ADR-0009 Step E').

Engine O used to keep persona / domain / intent enumerations as hardcoded
``MASTER_*`` Python dicts. Per ADR-0009 the active personas and domains
are derived from the predicate graph instead — every engine self-declares
its ``owner_persona`` and ``domains`` at registration; doc-tools projects
those onto Neo4j relationship properties (``r.owner_persona``,
``r.domains``); the view-functions here read them.

Intent has no replacement enumeration — it becomes the binary ``mode``
discriminator decided by ExtractIntent (Step F').

Two design points worth flagging:

1. **Graceful fallback.** If Neo4j is unreachable or the graph is empty
   (cold-start, dev environment with no engines registered yet) the
   functions fall back to a small local hardcoded list so the rest of
   Engine O — including the still-living legacy ``/route_and_plan``
   classifier — stays useful while the registration pipeline catches
   up. The fallback is *not* a parallel source of truth; it's a
   safety net so Engine O doesn't return empty enums to BAML.

2. **No persona descriptions on the graph (yet).** UI metadata
   (icons, colors) and BAML prompt descriptions are kept in code as
   presentation / classifier details. The graph carries identity
   (``MECHANIC``), the code carries chrome (``"Wrench"`` icon, "Line
   Mechanic" label). Step F' deletes the BAML prompt descriptions
   when the classifier goes away; the UI metadata stays in code as a
   pure presentation layer detail.
"""

from __future__ import annotations

import asyncio
from typing import Optional


#: UI presentation metadata for known personas. List of *active* personas
#: comes from the graph; this dict is just a lookup table the frontend
#: uses to render persona-specific chrome.
PERSONA_UI_METADATA: dict[str, dict] = {
    "MECHANIC":         {"label": "Line Mechanic", "icon": "Wrench",      "color": "text-amber-500",   "bg": "bg-amber-500/10 border-amber-500/30"},
    "TECH_WRITER":      {"label": "Tech Writer",   "icon": "BookOpen",    "color": "text-blue-400",    "bg": "bg-blue-400/10 border-blue-400/30"},
    "LOGISTICS":        {"label": "Logistics",     "icon": "Truck",       "color": "text-emerald-500", "bg": "bg-emerald-500/10 border-emerald-500/30"},
    "AUDITOR":          {"label": "Auditor",       "icon": "ShieldCheck", "color": "text-red-400",     "bg": "bg-red-400/10 border-red-400/30"},
    "PROCESS_ENGINEER": {"label": "Process Eng",   "icon": "Network",     "color": "text-purple-500",  "bg": "bg-purple-500/10 border-purple-500/30"},
    "DATA_STEWARD":     {"label": "Data Steward",  "icon": "Database",    "color": "text-cyan-400",    "bg": "bg-cyan-400/10 border-cyan-400/30"},
}

DEFAULT_PERSONA_UI = {
    "label": "Persona",
    "icon": "User",
    "color": "text-slate-400",
    "bg": "bg-slate-400/10 border-slate-400/30",
}

#: Legacy prompt descriptions kept only for the still-living BAML classifier
#: at ``/route_and_plan``. Step F' deletes that classifier and these dicts.
LEGACY_PERSONA_PROMPTS: dict[str, str] = {
    "MECHANIC":         "Wrench-turning, physical repairs, safety hazards, hardware component failures.",
    "TECH_WRITER":      "Formatting manuals, procedures, standard Markdown text. DO NOT use XML.",
    "LOGISTICS":        "Supply chain, procurement, lifecycle management, inventory.",
    "AUDITOR":          "Safety compliance, rules, identifying non-compliant nodes.",
    "PROCESS_ENGINEER": "Workflows, sequential steps, and BPMN routing across any discipline.",
    "DATA_STEWARD":     "Databases, dbt models, Postgres schemas, telemetry data pipelines, and metadata.",
}

LEGACY_DOMAIN_PROMPTS: dict[str, str] = {
    "MAINTENANCE":     "Wrench-turning, physical repairs, safety hazards, component failures.",
    "MANUFACTURING":   "Assembly, building, factory instructions, or production steps.",
    "SUSTAINMENT":     "Supply chain, logistics, procurement, lifecycle management, inventory.",
    "DATA_ENGINEERING": "dbt models, Postgres, React, Kafka, data pipelines, software architecture.",
    "UNKNOWN":         "Use if the query is unrelated to the above domains.",
}

LEGACY_INTENT_PROMPTS: dict[str, str] = {
    "DIAGNOSTIC_AND_REPAIR":      "User is troubleshooting a breakdown or failure (physical or software).",
    "STRUCTURAL_QUERY":           "User is asking to find, view, or understand existing assets / schemas.",
    "KNOWLEDGE_RETRIEVAL":        "User wants to read, summarize, or learn about policies / definitions / SOPs.",
    "PROCESS_CREATION":           "User wants to build, design, write, or publish a NEW workflow / process / product.",
    "SYSTEM_META_AND_REJECTION":  "User is asking what the system can do, or asking an out-of-scope question.",
}

#: Cypher: distinct ``owner_persona`` values across every predicate edge in the
#: registry. doc-tools' aitool_linker projects ``mesh_owner_persona`` →
#: ``r.owner_persona`` on every relationship.
PERSONA_REGISTRY_CYPHER = """
MATCH ()-[r]->()
WHERE r.owner_persona IS NOT NULL AND r.owner_persona <> ''
RETURN DISTINCT r.owner_persona AS persona
ORDER BY persona
"""

#: Cypher: distinct domain scopes across every predicate edge. doc-tools'
#: aitool_linker projects ``mesh_domains`` → ``r.domains`` (JSON-decoded list).
DOMAIN_REGISTRY_CYPHER = """
MATCH ()-[r]->()
WHERE r.domains IS NOT NULL AND size(r.domains) > 0
UNWIND r.domains AS domain
RETURN DISTINCT domain
ORDER BY domain
"""


async def fetch_active_personas(driver) -> list[str]:
    """Return distinct answerer-personas across all registered predicates.

    ``driver`` is the Neo4j Python driver instance held by Engine O's
    module state (``_NEO4J_DRIVER``). Falls back to the UI-metadata keys
    when the driver is ``None`` or the query raises / returns empty.
    """
    if driver is None:
        return list(PERSONA_UI_METADATA.keys())

    def _run() -> list[str]:
        with driver.session() as session:
            result = session.run(PERSONA_REGISTRY_CYPHER)
            return [str(record["persona"]) for record in result]

    try:
        rows = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        # Defensive: any driver error falls back to the local list. The
        # service stays useful in a Neo4j outage.
        print(f"[registry_views] fetch_active_personas fell back: {exc}")
        return list(PERSONA_UI_METADATA.keys())

    return rows or list(PERSONA_UI_METADATA.keys())


async def fetch_active_domains(driver) -> list[str]:
    """Return distinct domain scopes across all registered predicates."""
    if driver is None:
        return list(LEGACY_DOMAIN_PROMPTS.keys())

    def _run() -> list[str]:
        with driver.session() as session:
            result = session.run(DOMAIN_REGISTRY_CYPHER)
            return [str(record["domain"]) for record in result]

    try:
        rows = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        print(f"[registry_views] fetch_active_domains fell back: {exc}")
        return list(LEGACY_DOMAIN_PROMPTS.keys())

    return rows or list(LEGACY_DOMAIN_PROMPTS.keys())


async def get_baml_persona_string(driver) -> str:
    """Legacy persona-prompt formatter for BAML — deletion-pending alongside
    ``/route_and_plan`` and ``/plan``'s ``DecomposeQuery`` (Step F')."""
    personas = await fetch_active_personas(driver)
    return "\n".join(
        f"- {p}: {LEGACY_PERSONA_PROMPTS.get(p, 'Persona-specific specialist.')}"
        for p in personas
    )


async def get_baml_domain_string(driver) -> str:
    """Legacy domain-prompt formatter — same deletion-pending status."""
    domains = await fetch_active_domains(driver)
    return "\n".join(
        f"- {d}: {LEGACY_DOMAIN_PROMPTS.get(d, 'Domain scope.')}"
        for d in domains
    )
