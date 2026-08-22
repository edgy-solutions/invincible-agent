"""Every class Engine P puts on the wire must be DECLARED in the ontology.

WHY A SECOND SEAL AND NOT AN EXTENSION OF THE FIRST. `tests/test_archetypes_are_declared.py`
reads `PRESENTATION_CAPABILITIES` — the BACKEND capability table in
`agent_fleet/presentation_agent/capabilities.py`. That table is the one being retired: every
row it holds is now derived on the cortex-ui side, and its only surviving consumer was the
anonymous fallback, which `union_menu()` replaced.

So the existing seal's subject population is EMPTYING. It is correct today and it will pass
over nothing tomorrow, and a guard that passes over nothing is indistinguishable from a guard
that passes — the phantom-scope shape (`legacy-dns-guard-phantom-scope`). Nothing in it can
see Engine P's ten output types or the archetypes cortex-ui registers, and both ends of a
planning `rendersAs` triple come from exactly those two places.

WHAT CONTRACT D DOES WITH AN UNDECLARED END, and why this matters more than it looks: ADR-0019
requires both triple endpoints to pre-exist as `:OntologyClass` nodes and deliberately refuses
to auto-MERGE them. Measured 2026-08-21, the rejection reads as **"incomplete" rather than
"undeclared"** — so the symptom points away from the cause, and the cost is an afternoon.

THE CROSS-REPO LIMIT, STATED PLAINLY. The archetype constants below MIRROR cortex-ui's
`DERIVED_BINDINGS` rows; they are not imported, because that menu crosses at RUNTIME via
`/register_frontend_capabilities` and a compile-time import would invent a coupling the
architecture does not have. That means this file can go stale against cortex-ui. It cannot
go stale against the ONTOLOGY, which is what it is actually guarding, and a mirror that drifts
fails loudly here rather than silently in a cluster.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

rdflib = pytest.importorskip("rdflib", reason="ontology parsing needs rdflib")
from rdflib.namespace import OWL, RDF, RDFS  # noqa: E402

from agent_fleet.planning_agent import measures  # noqa: E402

_TTL = _ROOT / "setup" / "ontologies" / "mesh_system.ttl"
_MESH = rdflib.Namespace("http://invincible-agent/mesh#")

# Mirrors cortex-ui's DERIVED_BINDINGS. See the module docstring on why this is a mirror.
PLANNING_ARCHETYPE_IRIS = ["mesh:PeriodSeries", "mesh:ThresholdGrid", "mesh:MatrixGrid"]


def _graph():
    g = rdflib.Graph()
    g.parse(str(_TTL), format="turtle")
    return g


def _declared(g) -> set[str]:
    return {str(s) for s in g.subjects(RDF.type, OWL.Class)}


def _expand(iri: str) -> str:
    return iri.replace("mesh:", str(_MESH), 1) if iri.startswith("mesh:") else iri


@pytest.fixture(scope="module")
def graph():
    return _graph()


def test_the_ontology_is_inhabited(graph):
    """Positive control. A TTL that failed to parse, or a namespace that moved, would make
    every assertion below pass vacuously — guard-gone-quiet, applied to this file's subject."""
    declared = _declared(graph)
    assert len(declared) > 20, f"only {len(declared)} owl:Class found — the parse or namespace moved"
    assert str(_MESH) + "Archetype" in declared, "mesh:Archetype missing — the parent is gone"
    assert str(_MESH) + "Response" in declared, "mesh:Response missing — the parent is gone"


def test_every_engine_p_output_type_is_declared(graph):
    """The SUBJECT end of all ten planning registrations."""
    declared = _declared(graph)
    missing = sorted(uri for uri in measures.OUTPUT_URI.values() if uri not in declared)
    assert not missing, (
        f"{len(missing)} Engine P output type(s) on the wire but NOT declared in "
        f"mesh_system.ttl: {missing}.\nContract D rejects the registration on its SUBJECT end, "
        f"and the rejection reads as 'incomplete' rather than 'undeclared'. Declare the class; "
        f"do not weaken the gate."
    )


def test_every_planning_archetype_is_declared(graph):
    """The OBJECT end. Mirrors cortex-ui's bindings — see the docstring's cross-repo note."""
    declared = _declared(graph)
    missing = sorted(a for a in PLANNING_ARCHETYPE_IRIS if _expand(a) not in declared)
    assert not missing, (
        f"{len(missing)} planning archetype(s) registered by cortex-ui but NOT declared: "
        f"{missing}. Contract D rejects on the OBJECT end."
    )


def test_planning_archetypes_hang_off_mesh_Archetype_not_mesh_Response(graph):
    """The distinction the ontology comment calls load-bearing: an output type is a thing an
    engine PRODUCES; an archetype is a way a client can DRAW it. One is the payload, the other
    is the treatment. Filing an archetype under Response would make it eligible as a verb's
    output, which is a category error the graph would then happily serve."""
    for a in PLANNING_ARCHETYPE_IRIS:
        parents = {str(o) for o in graph.objects(rdflib.URIRef(_expand(a)), RDFS.subClassOf)}
        assert str(_MESH) + "Archetype" in parents, f"{a} is not a mesh:Archetype (parents: {parents})"
        assert str(_MESH) + "Response" not in parents, f"{a} is filed as a Response — category error"


def test_engine_p_output_types_hang_off_mesh_Response(graph):
    """The mirror of the above. An output type filed under Archetype would be offerable as a
    RENDERING KIND, and a client could register that it 'renders' a payload shape."""
    for uri in measures.OUTPUT_URI.values():
        parents = {str(o) for o in graph.objects(rdflib.URIRef(uri), RDFS.subClassOf)}
        assert str(_MESH) + "Response" in parents, f"{uri} is not a mesh:Response (parents: {parents})"
        assert str(_MESH) + "Archetype" not in parents, f"{uri} is filed as an Archetype — category error"


def test_every_declared_planning_class_carries_a_comment(graph):
    """A class with no rdfs:comment is a name with no meaning, and the next reader has to
    reconstruct the decision from the registration that uses it. The ontology's own idiom —
    every class around these carries one."""
    naked = []
    for iri in list(measures.OUTPUT_URI.values()) + [_expand(a) for a in PLANNING_ARCHETYPE_IRIS]:
        if not list(graph.objects(rdflib.URIRef(iri), RDFS.comment)):
            naked.append(iri)
    assert not naked, f"declared with no rdfs:comment: {naked}"
