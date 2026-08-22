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

import pathlib
import re
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

# DERIVED from cortex-ui's DERIVED_BINDINGS when that repo is a sibling on disk, and falling
# back to a mirrored list when it is not (CI, a clone without the sibling).
#
# WHY DERIVE. Hand-listing found three archetypes and missed four — GroupedReview, ApprovalTask,
# WorkflowObservation and InstancesByProperty had been registered since before the presentation
# arc and declared nowhere, and a hand-kept list finds whichever ones someone remembers. The
# fallback is honest about being a mirror; the derived path is what actually catches drift.
_SIBLING = _ROOT.parent / "cortex-ui" / "src" / "registry" / "assembleCapabilities.ts"

_MIRRORED = [
    "mesh:PeriodSeries", "mesh:ThresholdGrid", "mesh:MatrixGrid", "mesh:DeltaSet",
    "mesh:GroupedReview", "mesh:ApprovalTask", "mesh:WorkflowObservation",
    "mesh:InstancesByProperty", "mesh:ChartWidget", "mesh:KnowledgeDocument",
    "mesh:ProcessTopology", "mesh:AssetStateMetric", "mesh:HazardDeclaration",
]


def _archetype_iris() -> list[str]:
    if _SIBLING.is_file():
        import re
        found = re.findall(r'object_uri:\s*"(mesh:\w+)"', _SIBLING.read_text(encoding="utf-8"))
        if found:
            return sorted(set(found))
    return sorted(set(_MIRRORED))


PLANNING_ARCHETYPE_IRIS = _archetype_iris()


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
    """The SUBJECT end of all twelve planning registrations."""
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


# ─────────────────────────────────────────────────────────────────────────────
# THE OTHER END OF CONTRACT D.
#
# Everything above guards the OUTPUT half — `measures.OUTPUT_URI` and the archetypes. That is
# one end of one triple, and Contract D checks BOTH ends of the verb edge. The input half was
# never guarded, so it was never authored, and the omission was invisible until the registrar
# said so in production:
#
#   422 (Contract D): {"ok": false, "missing": ["http://invincible-agent/idp#Portfolio"]}
#
# Twelve registrations, twelve refusals, an engine reporting healthy the whole time. A seal
# that covers half of a two-ended contract reads exactly like a seal that covers the contract.
# ─────────────────────────────────────────────────────────────────────────────

_PRIME = _ROOT / "setup" / "prime_databases.py"
_INGESTED_PATH = re.compile(r'"path":\s*"(ontologies/[^"]+\.ttl)"')


def _ingested_ttls() -> list[pathlib.Path]:
    """Only the TTLs the prime actually ingests count as "declared".

    A class in a TTL that no prime entry names is not in the graph, so crediting it here
    would let the seal pass while Contract D still refuses. setup/prime_databases.py is the
    registry; reading it means a new ontology file cannot be declared-but-unwired.
    """
    text = _PRIME.read_text(encoding="utf-8")
    return [_ROOT / "setup" / rel for rel in sorted(set(_INGESTED_PATH.findall(text)))]


@pytest.fixture(scope="module")
def domain_graph():
    """Every ingested ontology — input classes may live in any of them."""
    g = rdflib.Graph()
    loaded = 0
    for ttl in _ingested_ttls():
        if ttl.exists():
            g.parse(str(ttl), format="turtle")
            loaded += 1
    assert loaded >= 8, f"only {loaded} ingested TTLs parsed — prime_databases.py shape moved"
    return g


def test_the_domain_ontology_is_inhabited(domain_graph):
    """Positive control for the second graph, same reason as the first."""
    declared = _declared(domain_graph)
    assert "http://invincible-agent/idp#Dataset" in declared, (
        "idp:Dataset missing — idp_extension.ttl did not parse or the namespace moved"
    )


def test_every_engine_p_input_class_is_declared(domain_graph):
    """The INPUT end of every verb edge Engine P registers.

    Measured 2026-08-22 against the sandbox registrar: five distinct input classes
    (Portfolio, Site, Capability, BusinessProcess, Technology) and NONE of them declared,
    so all twelve registrations were refused 422 while the engine served /health normally.
    """
    from agent_fleet.planning_agent import main as _main

    declared = _declared(domain_graph)
    needed = sorted({v["input_uri"] for v in _main.VERBS})
    missing = [uri for uri in needed if uri not in declared]

    assert not missing, (
        f"{len(missing)} of {len(needed)} Engine P input class(es) on the wire but NOT "
        f"declared in any ontology: {missing}.\nContract D refuses the verb edge on its "
        f"INPUT end and the engine stays up, so the only symptom is that nothing routes. "
        f"Declare the class; do not weaken the gate."
    )
