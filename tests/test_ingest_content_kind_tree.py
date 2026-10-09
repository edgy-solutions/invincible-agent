"""ADR-0041 §8 — the ContentKind tree the ingestion seam's `<kind>` leaf resolves to.

`ingress-user/<kind>/<sha>/` (ADR-0041 §2) and the classifier's suggestion routed through the
EXISTING `manifest.metadata.content_kind` channel (ADR-0021's precedence rule) both name a
`<kind>` string. Per ADR-0019 §6, a URI a pipeline can emit is a phantom unless it resolves to a
declared `:OntologyClass` — same defect class as `tests/test_archetypes_are_declared.py` guards
(an archetype IRI referenced everywhere and declared nowhere). This seal is that check for every
file kind the door accepts (`ingest_status.FILE_KINDS`: PDF, CAD and, from 2026-10-07, XML), in
both directions.

RED BEFORE: on the pre-change `mesh_system.ttl`, none of `mesh:Artifact`, `mesh:PDFArtifact`,
`mesh:CADArtifact` are declared (see the report for the red-before run).
"""
from __future__ import annotations

from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib", reason="ontology parsing needs rdflib")
from rdflib.namespace import OWL, RDF, RDFS  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_TTL = _ROOT / "setup" / "ontologies" / "mesh_system.ttl"
_MESH = rdflib.Namespace("http://invincible-agent/mesh#")


def _graph():
    g = rdflib.Graph()
    g.parse(str(_TTL), format="turtle")
    return g


def _declared_classes(g):
    return {str(s) for s in g.subjects(RDF.type, OWL.Class)}


def test_artifact_root_is_declared():
    declared = _declared_classes(_graph())
    assert str(_MESH.Artifact) in declared, "mesh:Artifact (the ContentKind tree root) is not declared"


def _file_kind_leaves() -> list[str]:
    from src.iagent import ingest_status

    return [f"{k.upper()}Artifact" for k in ingest_status.FILE_KINDS]


def test_every_file_kind_the_door_accepts_is_a_declared_leaf_of_artifact():
    # Derived from the tuple POST /ingest checks, so a fourth file kind reds here until its leaf
    # is declared. A literal list here once read PDF and CAD only.
    g = _graph()
    declared = _declared_classes(g)
    leaves = _file_kind_leaves()
    assert {"PDFArtifact", "CADArtifact", "XMLArtifact"} <= set(leaves), leaves
    for leaf in leaves:
        iri = _MESH[leaf]
        assert str(iri) in declared, f"mesh:{leaf} is not declared"
        assert (iri, RDFS.subClassOf, _MESH.Artifact) in g, (
            f"mesh:{leaf} is declared but is not rdfs:subClassOf mesh:Artifact"
        )


def test_every_leaf_of_artifact_is_a_file_kind_the_door_accepts():
    # The other direction: a leaf the door refuses is a class nothing can arrive as.
    g = _graph()
    leaves = {str(s).rsplit("#", 1)[-1] for s in g.subjects(RDFS.subClassOf, _MESH.Artifact)}
    assert leaves == set(_file_kind_leaves()), (sorted(leaves), _file_kind_leaves())


def test_artifact_is_not_confused_with_the_decision_artifact():
    # mesh:DecisionArtifact already exists (a disposition record this engine WRITES) and is a
    # different concept from mesh:Artifact (a document a USER drops, ADR-0041 §8). Collapsing
    # the two IRIs would make a promotion's citation of a decision artifact read as
    # self-reference against the dropped document it is ABOUT.
    g = _graph()
    assert _MESH.Artifact != _MESH.DecisionArtifact
    assert (_MESH.DecisionArtifact, RDFS.subClassOf, _MESH.Artifact) not in g
    assert (_MESH.Artifact, RDFS.subClassOf, _MESH.DecisionArtifact) not in g
