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
    "mesh:GraphQuery",             # was input_uri for mesh:queryKnowledgeGraph (mro migration, 2026-06-10)
    "mesh:KnowledgeQuery",         # was input_uri for mesh:retrieveKnowledge (mro migration, 2026-06-10)
    "mesh:Request",                # never had verbs typed against it
    # The 3 below were FIXED on 2026-06-11 via Phase 5 catalog migration —
    # the 9 catalog verbs all moved to idp:Dataset as input.
    "mesh:CatalogAssetQuery",      # was input_uri for 7 catalog-asset verbs
    "mesh:CatalogScopeQuery",      # was input_uri for mesh:enumerateCatalog
    "mesh:DatasetAnalysisRequest", # was input_uri for mesh:analyzeDataset
    # FIXED on 2026-06-11 same evening as Phase 5 close-out:
    # mesh_system.ttl ingested at canonical domain=MESH so the full-IRI
    # mesh:AgentTask exists; analyzeWithCodeAgent re-typed against it.
    # System verbs are not exempt from canonical reproducibility — they
    # satisfy the contract by typing against canonical mesh:* classes
    # that come from a canonical TTL source. Contract D debt: 0.
    "mesh:AgentTask",              # was input_uri for analyzeWithCodeAgent
})

# Contract D debt: 0. KNOWN_DEBT stays empty until a future verb gets
# registered against a non-canonical input shape — at which point this
# guard fails loudly and the drift-detection forces the decision to
# either type against a real ontology class or accept the debt
# explicitly by adding it here.
PSEUDO_KNOWN_DEBT: frozenset[str] = frozenset()

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
    # Contract D debt cleared 2026-06-11 same evening as Phase 5:
    # analyzeWithCodeAgent re-typed against full-IRI mesh:AgentTask
    # once mesh_system.ttl was canonically ingested at domain=MESH.
    expected_debt: set[tuple[str, str]] = set()
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
IDP_NS = "http://invincible-agent/idp#"

WORK_INSTRUCTION = MRO_NS + "WorkInstruction"
TECHNICAL_MANUAL = MRO_NS + "TechnicalManual"
GRAPH_EXPERT_RESPONSE = MESH_NS + "GraphExpertResponse"
KNOWLEDGE_RETRIEVAL_RESPONSE = MESH_NS + "KnowledgeRetrievalResponse"
IDP_DATASET = IDP_NS + "Dataset"
IDP_TABLE = IDP_NS + "Table"
MESH_AGENT_TASK = MESH_NS + "AgentTask"
INSTANCE_IDENTIFIER = "mesh:InstanceIdentifier"
PROCEDURE_STEP = "mro:ProcedureStep"


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


def test_mesh_resolve_instance_has_one_edge_per_provider(driver):
    """Every registered mesh:resolveInstance provider MUST exist as its
    OWN Neo4j edge — N providers must produce N edges, NOT collapse
    into one with last-write-wins.

    The doc-tools a44b9fb fix changed the apoc.merge.relationship
    match-key from ``{iri: verb_iri}`` to ``(verb_iri, _tool_urn)``
    precisely to make this true. This guard catches a regression on
    the doc-tools side that re-introduces the collision shape.

    Pre-fix bug: Engine E's registration silently overwrote Engine D's
    Neo4j edge for mesh:resolveInstance — both shared the same
    (input_uri, verb_iri, output_uri) triple and collapsed into one
    edge whose endpoint_url, provider, and timeout_s belonged to
    whichever had rolled last. Engine O's discovery saw exactly one
    provider, and the gate-6 generality acceptance test failed
    silently until the match-key landed in a44b9fb.

    Provider #3 (DMC phone book, queued in the docs phase) is the next
    occasion this shape recurs. This test turns red BEFORE that ships.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH ()-[r]->()
            WHERE r.iri = 'mesh:resolveInstance'
              AND r.endpoint_url IS NOT NULL
            RETURN coalesce(r.provider, '<unset>') AS provider,
                   r.endpoint_url AS endpoint_url,
                   r.timeout_s AS timeout_s,
                   r._tool_urn AS tool_urn
            ORDER BY provider
            """
        )
        rows = [dict(r) for r in result]

    assert rows, (
        "No mesh:resolveInstance edges found in Neo4j. Either the "
        "registration pipeline is broken (engines can't register) or "
        "the test is running against an empty fixture cluster — in "
        "either case the routing layer has no phone books and the "
        "Recipe v2 architecture is non-functional. Check the gateway "
        "logs for 'Registered urn:...resolveInstance' entries and the "
        "doc-tools sensor for 'Synced predicate edge: ... resolveInstance'."
    )

    # Each provider value MUST be distinct. If two registrations share
    # a provider AND collapse into one edge, that's the multi-provider
    # collision shape returning under a new shape.
    providers = [row["provider"] for row in rows]
    assert len(providers) == len(set(providers)), (
        f"\n  Duplicate provider in mesh:resolveInstance edges:\n"
        f"  Providers seen: {providers}\n"
        f"  Edges:\n" + "\n".join(f"    - {r}" for r in rows) + "\n"
        f"\n  Two distinct registrations resolved to the same provider "
        f"value AND were materialized as separate edges — the registry "
        f"and the materializer disagree on who is who. Pre-a44b9fb the "
        f"shape was 'two registrations collapse to one edge'; this "
        f"shape is 'two edges share a provider'. Either way the "
        f"discovery layer cannot distinguish them, and provenance "
        f"breaks: traces will report a randomly-chosen one of the two "
        f"as the answering provider."
    )

    # Each edge MUST have a non-null, non-empty provider value. The
    # allowlist-drift bug class (doc-tools 540fbd5) silently dropped
    # mesh_provider for hours when the gateway started emitting it but
    # the sensor's hardcoded passthrough list hadn't been updated. This
    # check pins that the property survives the materialization step.
    unset_provider = [r for r in rows if r["provider"] in ("<unset>", "", None)]
    assert not unset_provider, (
        f"\n  mesh:resolveInstance edges with missing provider field:\n"
        + "\n".join(f"    - {r}" for r in unset_provider) + "\n"
        f"\n  This is the allowlist-drift bug class: gateway emits the "
        f"mesh_provider customProperty, the doc-tools sensor's "
        f"_build_relationship_properties allowlist must pipe it onto "
        f"the relationship, AND the discovery Cypher reads "
        f"coalesce(r.provider, type(r)) — but the chain breaks silently "
        f"if any link drops it. The v0.2 gateway-as-sole-writer "
        f"amendment (ADR-0006 §Addendum) eliminates the allowlist hop "
        f"entirely; until that lands, this test catches the drift at "
        f"the substrate."
    )

    # Each edge MUST have a positive timeout_s. The router uses it as
    # the per-provider fan-out budget; a missing value falls through
    # to the global floor, which silently absorbs Cypher pathologies
    # under the budget sized for the slowest provider (the 2s strangle
    # bug the architect flagged).
    bad_timeout = [r for r in rows if not (isinstance(r["timeout_s"], (int, float)) and r["timeout_s"] > 0)]
    assert not bad_timeout, (
        f"\n  mesh:resolveInstance edges with missing or non-positive "
        f"timeout_s:\n"
        + "\n".join(f"    - {r}" for r in bad_timeout) + "\n"
        f"\n  Per-provider timeout budgets MUST be declared at "
        f"registration so the router treats Engine D's 8s p95 and "
        f"Engine E's ms response with the appropriate alarm thresholds. "
        f"A missing timeout collapses to the global floor and hides "
        f"real Cypher pathologies — exactly the asymmetry the architect "
        f"flagged at Gate 6."
    )

    # Each edge MUST have a tool_urn (the registration identity from
    # DataHub MCP). Pre-a44b9fb the match-key didn't include _tool_urn,
    # so multi-provider registrations couldn't be distinguished. This
    # checks the inverse: every edge knows which registration produced
    # it. If a future refactor drops the _tool_urn passthrough, the
    # multi-provider invariant above can still pass by accident — this
    # guard catches the precondition.
    no_urn = [r for r in rows if not r["tool_urn"]]
    assert not no_urn, (
        f"\n  mesh:resolveInstance edges without _tool_urn:\n"
        + "\n".join(f"    - {r}" for r in no_urn) + "\n"
        f"\n  _tool_urn is the registration identity. Without it on "
        f"the edge, the (verb_iri, _tool_urn) match-key from a44b9fb "
        f"cannot distinguish providers. This is the precondition for "
        f"the multi-provider invariant above; missing _tool_urn means "
        f"the multi-provider check above is passing by accident."
    )


def test_known_verbs_typed_correctly(driver):
    """Every known verb has AT LEAST ONE v0.2-provenanced edge typed against
    the expected real subject class at canonical (full IRI) form.

    Catches the failure mode where a re-registration through the gateway
    accidentally reverts to a pseudo-class typing OR to the compact form.

    Multi-registration safe: a verb may be legitimately typed against
    several subjects (e.g. mesh:queryKnowledgeGraph against both
    WorkInstruction and ProcedureStep). This test asserts the expected
    (input, output) pair EXISTS among the verb's v0.2 saga edges, not
    that it's the only one. The dict-overwrite race that bit us
    2026-06-13 — Cypher returning multiple edges per verb and the dict
    landing on whichever came last — is avoided by collecting a SET of
    triples per verb instead.
    """
    expected = {
        "mesh:queryKnowledgeGraph": (WORK_INSTRUCTION, GRAPH_EXPERT_RESPONSE),
        "mesh:retrieveKnowledge": (TECHNICAL_MANUAL, KNOWLEDGE_RETRIEVAL_RESPONSE),
    }
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s)-[r]->(o) WHERE r.iri IN $verbs
              AND r._tool_urn IS NOT NULL
            RETURN r.iri AS verb, s.uri AS input_uri, o.uri AS output_uri,
                   r._input_uri AS recorded_input
            """,
            verbs=list(expected),
        )
        actual: dict[str, set] = {}
        for rec in result:
            actual.setdefault(rec["verb"], set()).add(
                (rec["input_uri"], rec["output_uri"], rec["recorded_input"])
            )
    for verb, (want_in, want_out) in expected.items():
        edges = actual.get(verb, set())
        assert edges, (
            f"Verb {verb} has no v0.2 saga edges (non-NULL _tool_urn) in "
            f"the substrate. Either the engine isn't registered or the "
            f"saga didn't write the edge — check mesh-registrar logs."
        )
        # Assert the EXPECTED triple exists among the verb's edges. Other
        # registrations of the same verb (multi-registration pattern) may
        # exist alongside it and that's fine.
        want = (want_in, want_out, want_in)
        assert want in edges, (
            f"{verb}: expected (input={want_in!r}, output={want_out!r}, "
            f"recorded_input={want_in!r}) not found among v0.2 saga edges. "
            f"Actual edges:\n"
            + "\n".join(f"    - {e}" for e in sorted(edges))
        )


# -----------------------------------------------------------------------------
# Coverage guard (ADR-0006 §Addendum 2026-06-13 amendment): for every routing
# pair the matrix exercises, the substrate must contain at least one v0.2 saga
# edge (_tool_urn IS NOT NULL) reachable via the compat-walk from the subject.
#
# This is the standing guard that would have caught my 2026-06-13 mistake
# BEFORE the DELETE. The orphan DELETE prediction was "no movement" based on
# reasoning (conjunctive invariant + endpoint match). The prediction was
# wrong because the orphans were Phase 5's substrate-direct re-typings that
# the v0.2 saga never overwrote — they were Cypher's only path to the verbs
# for the full-IRI subjects the resolver actually lands on.
#
# With this guard in place, the same DELETE attempt would fail BEFORE the
# substrate change: the guard would point at exactly the (subject, verb)
# pairs that have no v0.2 saga edge — i.e., the orphans are load-bearing
# and shouldn't be deleted until either (a) the source declarations are
# corrected and re-registered (the Option 1 fix the architect prescribed)
# or (b) the matrix's expected routing is intentionally narrowed.
#
# Architect's framing of the rule: "for every matrix-successful (subject,
# verb) pair, assert that the compat-walk from the subject reaches the
# verb via at least one v0.2 saga edge (non-NULL _tool_urn)."
COVERAGE_PAIRS = [
    # Catalog routing via idp:Dataset and its idp:Table/Dashboard subclasses
    # (the resolver lands on idp:Table or idp:Dashboard for specific assets;
    # compat-walk goes subClassOf* up to idp:Dataset which carries the
    # verbs). All 8 engine_a catalog/scope verbs:
    (IDP_DATASET, "mesh:lookupOwnership"),
    (IDP_DATASET, "mesh:traceLineage"),
    (IDP_DATASET, "mesh:assessImpact"),
    (IDP_DATASET, "mesh:findSchema"),
    (IDP_DATASET, "mesh:checkFreshness"),
    (IDP_DATASET, "mesh:filterByTag"),
    (IDP_DATASET, "mesh:describeAsset"),
    (IDP_DATASET, "mesh:enumerateCatalog"),
    # The inheritance case that bit us 2026-06-13: idp:Table queries must
    # reach catalog verbs via subClassOf to idp:Dataset.
    (IDP_TABLE, "mesh:describeAsset"),
    (IDP_TABLE, "mesh:lookupOwnership"),
    (IDP_TABLE, "mesh:traceLineage"),
    (IDP_TABLE, "mesh:findSchema"),
    # Maintenance knowledge graph (engine_e via MRO/WorkInstruction):
    (WORK_INSTRUCTION, "mesh:queryKnowledgeGraph"),
    # Maintenance procedure-step (engine_e's second registration):
    (PROCEDURE_STEP, "mesh:queryKnowledgeGraph"),
    # Manual retrieval (engine_w via MRO/TechnicalManual):
    (TECHNICAL_MANUAL, "mesh:retrieveKnowledge"),
    # Phone book (engine_d + engine_e via mesh:InstanceIdentifier):
    (INSTANCE_IDENTIFIER, "mesh:resolveInstance"),
    # Code agent fallback (engine_a via mesh#AgentTask):
    (MESH_AGENT_TASK, "mesh:analyzeWithCodeAgent"),
]


def test_substrate_covers_routing_via_v02_saga_edges(driver):
    """Coverage guard: every routing pair the matrix exercises MUST be
    backed by a v0.2 saga edge (non-NULL _tool_urn) reachable via the
    compat-walk from the subject. This makes the matrix's routing depend
    only on source-declared, gateway-materialized edges — NOT on
    historical substrate-direct fixes or orphan edges left behind by
    earlier migrations.

    If this test fails for a (subject, verb) pair, it means:
      a) The orphans (pre-v0.2 substrate-direct migrations) are STILL
         load-bearing for that pair — deleting them WILL break routing.
      b) The engine's SDK declaration's input_uri doesn't match the
         subject class the resolver actually lands on for queries that
         should route to this verb. The fix is to re-declare against
         the resolver-target subject (the Option 1 fix shape, 7978260).

    Either failure mode names the cleanup blocker by row.

    The compat-walk direction here mirrors the production resolver in
    agent_fleet/ontology_service/main.py:
      MATCH (subject)-[:subClassOf*0..]->(ancestor)
      MATCH (ancestor)-[verb_edge]->()
    """
    missing = []
    with driver.session() as session:
        for subject, verb in COVERAGE_PAIRS:
            n = session.run(
                """
                MATCH (s:OntologyClass {uri: $subject})
                OPTIONAL MATCH (s)-[:subClassOf*0..10]->(ancestor:OntologyClass)
                WITH collect(DISTINCT coalesce(ancestor, s)) AS ancestors
                UNWIND ancestors AS a
                MATCH (a)-[r {iri: $verb}]->()
                WHERE r._tool_urn IS NOT NULL
                RETURN count(DISTINCT r) AS n
                """,
                subject=subject, verb=verb,
            ).single()["n"]
            if n < 1:
                missing.append((subject, verb))
    assert not missing, (
        "Routing pairs not covered by any v0.2 saga edge (non-NULL "
        "_tool_urn) via subClassOf compat-walk:\n"
        + "\n".join(f"    - {s} → {v}" for s, v in missing)
        + "\n\nEither orphans are load-bearing for these pairs (cleanup "
        "is blocked until the engine's source declaration is corrected "
        "and re-registered) or the source declaration's input_uri "
        "doesn't match the resolver's landing class. See ADR-0006 "
        "§Addendum 2026-06-13: source declarations are the authoritative "
        "registry post-v0.2; substrate-direct fixes that bypass them are "
        "regressions waiting to fire."
    )
