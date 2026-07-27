"""pcn mesh:resolveInstance provider — the candidate producer (pure core; the route is a thin wrapper).

engine-o's fan-out POSTs ``{identifier, query}`` to a provider endpoint and expects
``{candidates: [{instance_id, class_uri, label, score}]}`` back; an empty list is a first-class
ABSTAIN (providers must abstain below their floor, never return least-bad matches). This produces
those candidates from the pcn instances in Jena's SUSTAINMENT_INSTANCES graph (doc-tools-written,
deterministic IRIs). Pure — the SPARQL executor is INJECTED, so the matching is unit-tested against
live-shaped rows without a Jena; the route passes an ``execute_sparql``-backed runner.

Matching reuses [[sustainment_instance_match]]: descriptor-strip (notice/part strippable; pcn/pdn NOT) then
``name_score`` against each instance's local name (an MPN or notice-id). Exact MPN/notice-id → 1.0.
"""
from __future__ import annotations

try:  # flatten-aware import, same shape as registry_views / recall_guard in main.py
    from sustainment_instance_match import strip_descriptor_tokens, name_score  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.ontology_service.sustainment_instance_match import strip_descriptor_tokens, name_score

_PCN = "http://internal/sustainment/pcn#"
_COMPONENT_CLASS = _PCN + "Component"

# All pcn instances + their class. Notices are rdf:typed; components are referenced (subjectToNotice)
# but NOT typed by doc-tools, so their class is inferred as pcn:Component. The route runs this through
# engine-o's execute_sparql(domain="SUSTAINMENT"), whose read-union spans SUSTAINMENT + _INSTANCES.
SUSTAINMENT_INSTANCES_QUERY = f"""
SELECT DISTINCT ?s ?type WHERE {{
  {{ ?s a ?type . FILTER(STRSTARTS(STR(?s), "http://internal/sustainment/doc/")) }}
  UNION
  {{ ?s ?p ?o . FILTER(STRSTARTS(STR(?s), "http://internal/components/")) . BIND(<{_COMPONENT_CLASS}> AS ?type) }}
}}
"""


def _local(iri: str) -> str:
    return str(iri).rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def resolve_sustainment_candidates(identifier: str, *, rows: list[dict], floor: float = 0.5) -> list[dict]:
    """Return scored candidates for ``identifier`` from the pcn instance ``rows`` (the fetched
    ``SUSTAINMENT_INSTANCES_QUERY`` result: dicts with ``s`` = instance IRI, ``type`` = class IRI), above
    ``floor``, best first. Empty list = honest abstain — no instance clears the floor, never a
    least-bad match. The async Jena fetch stays in the route; the matching is a pure function of
    (identifier, rows)."""
    ident = (identifier or "").strip()
    stripped = strip_descriptor_tokens(ident)
    candidates: list[dict] = []
    for row in rows or []:
        s = str(row.get("s") or "")
        if not s:
            continue
        local = _local(s)
        score = max(name_score(ident, local), name_score(stripped, local))
        if score >= floor:
            candidates.append({
                "instance_id": s,
                "class_uri": str(row.get("type") or ""),
                "label": local,
                "score": round(score, 3),
            })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates
