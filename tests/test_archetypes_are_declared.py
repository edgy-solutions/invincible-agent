"""Every archetype a presentation registers must be DECLARED in the ontology.

THE DEFECT THIS PREVENTS, measured 2026-08-21: ADR-0017 registers presentation
capabilities as (subject_uri, mesh:rendersAs, object_uri) where the object is an archetype
IRI. Those IRIs were referenced across the ADR, the capability table, and every registration
Engine F emits at startup -- and DECLARED NOWHERE. Contract D (ADR-0019) requires both triple
endpoints to pre-exist as :OntologyClass nodes and refuses to auto-MERGE them, so every
presentation registration was rejected on its object end. Correctly: the gate was right and
the declaration was missing.

Same species as mesh:DispositionReview -- a URI named by a registration and declared by
nothing. Green in every conversation, impossible in every fresh substrate, and invisible until
someone tried to use the path. THIS TEST IS THE GUARD THAT CASE DID NOT HAVE.

It reads the CAPABILITY TABLE, not a hand-kept list, so adding a capability with an
undeclared archetype fails here rather than at registration time in a cluster.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_archetypes_are_declared.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

rdflib = pytest.importorskip("rdflib", reason="ontology parsing needs rdflib")
from rdflib.namespace import OWL, RDF, RDFS  # noqa: E402

from agent_fleet.presentation_agent.capabilities import (  # noqa: E402
    PRESENTATION_CAPABILITIES,
)

_TTL = _ROOT / "setup" / "ontologies" / "mesh_system.ttl"
_MESH = rdflib.Namespace("http://invincible-agent/mesh#")


def _graph():
    g = rdflib.Graph()
    g.parse(str(_TTL), format="turtle")
    return g


def _declared_classes(g):
    return {str(s) for s in g.subjects(RDF.type, OWL.Class)}


def _expand(compact: str) -> str:
    """mesh:ChartWidget -> the full IRI. The registration writes compact form; the ontology
    declares full — the compact-vs-full hazard, at the declaration boundary."""
    return compact.replace("mesh:", str(_MESH), 1) if compact.startswith("mesh:") else compact


def test_every_registered_ARCHETYPE_is_declared():
    """The object end of every rendersAs triple. This is the one that was failing."""
    g = _graph()
    declared = _declared_classes(g)
    missing = sorted(
        {c["object_uri"] for c in PRESENTATION_CAPABILITIES if _expand(c["object_uri"]) not in declared}
    )
    assert not missing, (
        f"{len(missing)} archetype(s) registered but NOT declared in mesh_system.ttl: {missing}.\n"
        f"Contract D will reject the presentation on its object end, and the rejection will "
        f"read as 'incomplete' rather than 'undeclared'. Declare the class; do not weaken "
        f"the gate."
    )


def test_every_registered_SUBJECT_shape_is_declared():
    """The other end. These were already fine, and pinning them keeps the pair honest --
    a future output shape can go undeclared exactly as easily."""
    g = _graph()
    declared = _declared_classes(g)
    missing = sorted(
        {c["subject_uri"] for c in PRESENTATION_CAPABILITIES if _expand(c["subject_uri"]) not in declared}
    )
    assert not missing, f"output shape(s) registered but not declared: {missing}"


def test_archetypes_hang_off_their_OWN_parent_not_Response():
    """An archetype is not a payload. mesh:DatasetAnalysisReport is a thing an engine
    PRODUCES; mesh:ChartWidget is a way a client can DRAW it. Forcing archetypes under
    mesh:Response would make the graph say a rendering kind is an engine output."""
    g = _graph()
    archetypes = {str(s) for s in g.subjects(RDFS.subClassOf, _MESH.Archetype)}
    assert archetypes, "no classes declared under mesh:Archetype"
    for c in PRESENTATION_CAPABILITIES:
        obj = _expand(c["object_uri"])
        assert obj in archetypes, f"{c['object_uri']} is declared but not under mesh:Archetype"
        assert (rdflib.URIRef(obj), RDFS.subClassOf, _MESH.Response) not in g, (
            f"{c['object_uri']} is subclassed under mesh:Response — an archetype is a "
            f"TREATMENT, not a payload"
        )


def test_the_universal_archetype_is_declared():
    """KNOWLEDGE_DOCUMENT is the fallback slice 4 routes an unsatisfiable payload to. If its
    class is missing, the ONE archetype that must always be available is the one that cannot
    register."""
    assert _expand("mesh:KnowledgeDocument") in _declared_classes(_graph())
