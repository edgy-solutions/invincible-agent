"""Substrate invariants — standing guards promoted from tonight's one-shot checks.

These are the permanent regression gates for the substrate that backs ADR-0019
routing. Each test guards a failure mode that's been observed live in this
project — phantom classes (the predicate-graph wipe), pseudo-class typings (the
mesh:GraphQuery Contract D violation), subject mis-resolution (the manuals →
mesh:GraphQuery before the mro_extension landed), nondeterministic routing
(TEST-1234 sampling flake before temperature 0).

The other agent's argument for promoting these to standing guards: every
failure mode has happened once, will happen again under registration churn, and
end-to-end matrix tests can't tell you *which* layer broke. These run at the
substrate layer directly so a regression names its own cause.

Run requires Neo4j credentials. Defaults are sandbox values; CI sets via env.

  pytest tests/routing/test_substrate_invariants.py
"""
from __future__ import annotations

import os
import pytest

try:
    from neo4j import GraphDatabase
except ImportError:
    pytest.skip("neo4j driver not installed", allow_module_level=True)


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j"))
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "changeme-neo4j-sandbox")


# Pseudo-classes (plumbing concepts the resolver can never land on).
#
# The first three were killed on 2026-06-10. The catalog ones below are
# pre-existing debt surfaced while killing the first batch — every idp /
# catalog verb in the seed_sandbox_predicates.py registration types its
# input against a `mesh:Catalog*Query` pseudo-class. That whole set has to
# move to real idp:* subjects (idp:Dataset, idp:Table, idp:Dashboard) when
# idp Layer 1 lands — currently GMS-blocked.
#
# This list is the union of what *is* typed against a pseudo-class today.
# We split it into FIXED (must stay clean — any re-introduction is a
# regression) and KNOWN_DEBT (will be cleaned when their domain's Layer 1
# ontology lands). The FIXED set's invariant is enforced strictly. The
# KNOWN_DEBT set is tracked by a separate informational test so future fixes
# DON'T silently expand the debt.
PSEUDO_FIXED = frozenset({
    "mesh:GraphQuery",       # was input_uri for mesh:queryKnowledgeGraph
    "mesh:KnowledgeQuery",   # was input_uri for mesh:retrieveKnowledge
    "mesh:Request",          # never had verbs typed against it
})

PSEUDO_KNOWN_DEBT = frozenset({
    "mesh:CatalogAssetQuery",      # 7 verbs: assessImpact, checkFreshness,
                                   # describeAsset, filterByTag, findSchema,
                                   # lookupOwnership, traceLineage
    "mesh:CatalogScopeQuery",      # 1 verb: enumerateCatalog
    "mesh:DatasetAnalysisRequest", # 1 verb: analyzeDataset
    "mesh:AgentTask",              # 1 verb: analyzeWithCodeAgent
})

PSEUDO_CLASSES = PSEUDO_FIXED | PSEUDO_KNOWN_DEBT


@pytest.fixture(scope="module")
def driver():
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        drv.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j unreachable at {NEO4J_URI}: {e}")
    yield drv
    drv.close()


def test_no_verb_inputs_against_fixed_pseudo_class(driver):
    """Contract D regression guard: the pseudo-classes killed on 2026-06-10
    must stay killed. If any future registration types its input back against
    these, this test fails — the build that introduced it is the regression.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH ()-[r]->() WHERE r.iri IS NOT NULL
            AND r._input_uri IN $pseudo
            RETURN r.iri AS verb, r._input_uri AS input_uri
            """,
            pseudo=list(PSEUDO_FIXED),
        )
        violations = [(rec["verb"], rec["input_uri"]) for rec in result]
    assert not violations, (
        f"Verbs typed against FIXED pseudo-classes: {violations}. "
        f"These were fixed on 2026-06-10 and must not return."
    )


def test_no_verb_outputs_against_pseudo_class(driver):
    """Symmetric: outputs must be real response classes. We check against the
    FULL pseudo-class set because no verb has ever legitimately had a
    pseudo-class output — pseudo-classes are query-side plumbing only.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH ()-[r]->() WHERE r.iri IS NOT NULL
            AND r._output_uri IN $pseudo
            RETURN r.iri AS verb, r._output_uri AS output_uri
            """,
            pseudo=list(PSEUDO_CLASSES),
        )
        violations = [(rec["verb"], rec["output_uri"]) for rec in result]
    assert not violations, f"Verbs producing pseudo-class outputs: {violations}"


def test_pseudo_class_debt_matches_known_set(driver):
    """Informational guard: the set of verbs typed against KNOWN-DEBT
    pseudo-classes must match the set we have on record. This catches two
    kinds of drift:

    1. A new verb is added that types against an existing pseudo-class —
       silently expanding the debt. This test fails so the registration
       can be re-typed or the debt explicitly grown via PR review.
    2. An existing debt verb gets fixed (moved off the pseudo-class) —
       this test fails so the FIXED set is updated and the debt list
       shrinks.

    Either failure mode means an entry in this file needs updating.
    """
    expected_debt = {
        ("mesh:CatalogAssetQuery", "mesh:assessImpact"),
        ("mesh:CatalogAssetQuery", "mesh:checkFreshness"),
        ("mesh:CatalogAssetQuery", "mesh:describeAsset"),
        ("mesh:CatalogAssetQuery", "mesh:filterByTag"),
        ("mesh:CatalogAssetQuery", "mesh:findSchema"),
        ("mesh:CatalogAssetQuery", "mesh:lookupOwnership"),
        ("mesh:CatalogAssetQuery", "mesh:traceLineage"),
        ("mesh:CatalogScopeQuery", "mesh:enumerateCatalog"),
        ("mesh:DatasetAnalysisRequest", "mesh:analyzeDataset"),
        ("mesh:AgentTask", "mesh:analyzeWithCodeAgent"),
    }
    with driver.session() as session:
        result = session.run(
            """
            MATCH ()-[r]->() WHERE r.iri IS NOT NULL
            AND r._input_uri IN $pseudo
            RETURN DISTINCT r._input_uri AS input_uri, r.iri AS verb
            """,
            pseudo=list(PSEUDO_KNOWN_DEBT),
        )
        actual = {(rec["input_uri"], rec["verb"]) for rec in result}
    added = actual - expected_debt
    removed = expected_debt - actual
    assert not (added or removed), (
        f"Pseudo-class debt drift detected.\n"
        f"  New debt added (re-type these verbs or accept the debt): {added}\n"
        f"  Debt resolved (move from KNOWN_DEBT to FIXED): {removed}"
    )


def test_no_phantom_input_classes(driver):
    """Contract D: every verb's declared _input_uri must resolve to a real
    :OntologyClass node in the substrate. A verb pointing at a URI with no
    matching node is a phantom — the compat-walk can never find it, the
    resolver can never match it, and the registration silently no-ops.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH ()-[r]->() WHERE r.iri IS NOT NULL AND r._input_uri IS NOT NULL
            WITH r._input_uri AS uri, collect(r.iri) AS verbs
            WHERE NOT EXISTS { MATCH (:OntologyClass {uri: uri}) }
            RETURN uri, verbs
            """,
        )
        phantoms = [(rec["uri"], rec["verbs"]) for rec in result]
    assert not phantoms, (
        f"Verbs typed against non-existent OntologyClass URIs: {phantoms}. "
        f"Run the canonical ontology ingest before registering verbs."
    )


def test_no_phantom_output_classes(driver):
    """Symmetric to inputs."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH ()-[r]->() WHERE r.iri IS NOT NULL AND r._output_uri IS NOT NULL
            WITH r._output_uri AS uri, collect(r.iri) AS verbs
            WHERE NOT EXISTS { MATCH (:OntologyClass {uri: uri}) }
            RETURN uri, verbs
            """,
        )
        phantoms = [(rec["uri"], rec["verbs"]) for rec in result]
    assert not phantoms, f"Verbs producing non-existent OntologyClass outputs: {phantoms}"


# Canonical full-IRI form for the migrated subjects. Compact prefixes
# (mro:, mesh:) are NOT canonical — they were the band-aid form of the
# pre-canonical hand-seed. ADR-0019 § canonical-URI invariant: the substrate
# stores rdflib-extracted full IRIs (resolvable, namespace-correct, what
# the backbone ontologies use). The compact 27 remaining nodes are tracked
# debt to be migrated when their domain's Layer 1 ontology lands.
MRO_NS = "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/"
MESH_NS = "http://invincible-agent/mesh#"

WORK_INSTRUCTION = MRO_NS + "WorkInstruction"
TECHNICAL_MANUAL = MRO_NS + "TechnicalManual"
GRAPH_EXPERT_RESPONSE = MESH_NS + "GraphExpertResponse"
KNOWLEDGE_RETRIEVAL_RESPONSE = MESH_NS + "KnowledgeRetrievalResponse"


def test_known_subjects_exist(driver):
    """The subjects the routing matrix depends on must be in the substrate
    at their canonical full-IRI form (not the compact band-aid form).

    Catches the failure mode where the ontology ingest succeeded but the
    Weaviate sync lost the records, OR where a regression re-introduces
    the compact form for these specific subjects.
    """
    required = [
        WORK_INSTRUCTION,
        TECHNICAL_MANUAL,
        # idp:Dataset / Table / Dashboard come in once the idp extension lands.
    ]
    with driver.session() as session:
        result = session.run(
            """
            UNWIND $uris AS uri
            WITH uri WHERE NOT EXISTS { MATCH (:OntologyClass {uri: uri}) }
            RETURN collect(uri) AS missing
            """,
            uris=required,
        ).single()
        missing = result["missing"] if result else required
    assert not missing, (
        f"Required OntologyClass nodes missing: {missing}. "
        f"Step 1 (ontology ingest) didn't land — check ingest_ontology_job."
    )


def test_no_compact_form_for_migrated_subjects(driver):
    """The 4 nodes migrated on 2026-06-10 (compact → full IRI) must stay
    full-IRI. If the compact form reappears, something re-introduced the
    band-aid — most likely a manual MERGE or an unfixed seed script.

    This is the per-node version of the identity-duplication guard scoped
    to just the nodes we migrated tonight. Once more of the substrate is
    migrated, expand this set.
    """
    migrated_compact = [
        "mro:WorkInstruction",
        "mro:TechnicalManual",
        "mesh:GraphExpertResponse",
        "mesh:KnowledgeRetrievalResponse",
    ]
    with driver.session() as session:
        result = session.run(
            """
            UNWIND $uris AS uri
            MATCH (c:OntologyClass {uri: uri})
            RETURN collect(uri) AS present
            """,
            uris=migrated_compact,
        ).single()
        present = result["present"] if result else []
    assert not present, (
        f"Compact-form OntologyClass nodes reappeared for migrated subjects: {present}. "
        f"These were migrated to their full-IRI canonical form on 2026-06-10 "
        f"and must not return. Likely cause: a seed script or manual MERGE "
        f"using the band-aid compact form."
    )


def test_known_verbs_typed_correctly(driver):
    """Every known verb is typed against the expected real subject class
    at canonical (full IRI) form.

    Catches the failure mode where a re-registration through the gateway
    accidentally reverts to a pseudo-class typing OR to the compact form.
    """
    expected = {
        "mesh:queryKnowledgeGraph": (WORK_INSTRUCTION, GRAPH_EXPERT_RESPONSE),
        "mesh:retrieveKnowledge": (TECHNICAL_MANUAL, KNOWLEDGE_RETRIEVAL_RESPONSE),
    }
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s)-[r]->(o) WHERE r.iri IN $verbs
            RETURN r.iri AS verb, s.uri AS input_uri, o.uri AS output_uri,
                   r._input_uri AS recorded_input
            """,
            verbs=list(expected),
        )
        actual = {
            rec["verb"]: (rec["input_uri"], rec["output_uri"], rec["recorded_input"])
            for rec in result
        }
    for verb, (want_in, want_out) in expected.items():
        got = actual.get(verb)
        assert got is not None, f"Verb {verb} not found in substrate"
        got_in, got_out, recorded_in = got
        assert got_in == want_in, f"{verb} input edge: want {want_in}, got {got_in}"
        assert got_out == want_out, f"{verb} output edge: want {want_out}, got {got_out}"
        assert recorded_in == want_in, (
            f"{verb} _input_uri property: want {want_in}, got {recorded_in} "
            f"(edge endpoint and recorded _input_uri must agree)"
        )
