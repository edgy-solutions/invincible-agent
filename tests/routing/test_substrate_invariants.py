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
INSTANCE_IDENTIFIER = MESH_NS + "InstanceIdentifier"  # canonical full-IRI; engine_d + engine_e both registered against this after Session 2 A3 fold
# 2026-06-15: canonicalized from compact "mro:ProcedureStep" to full-IRI
# alongside the source-side canonicalization in agent_fleet/neo4j_expert/main.py.
# The compact form here predated that fix; substrate has the full IRI and the
# resolver lands on the full IRI, so the guard's expected value must match.
PROCEDURE_STEP = MRO_NS + "ProcedureStep"


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

    Subset of the broader test_no_compact_form_ontology_classes below.
    Retained as a focused signal for the Phase-5-migrated subjects.
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


# Compact-form prefixes the widened substrate guard catches. The
# corresponding canonical full-IRI is constructed from a known map for
# the failure message; if a prefix isn't in this map the guard still
# fires (the prefix-form itself is the violation).
_COMPACT_PREFIXES_NAMESPACE_MAP = {
    "mesh:": "http://invincible-agent/mesh#",
    "mro:":  "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/",
    "idp:":  "http://invincible-agent/idp#",
    "data:": "http://invincible-agent/data#",
    "mil:":  "http://edgy-solutions.com/ontology/mil#",
}


def test_no_compact_form_ontology_classes(driver):
    """**The widened class guard (2026-06-13 late).** Every
    :OntologyClass node MUST have a canonical full-IRI URI. Compact-form
    URIs (mesh:Foo, mro:Bar, idp:Baz, data:Qux, mil:Quux) are a
    regression — they create duplicate nodes alongside the canonicals
    that the canonical ingest pipeline materialized, and split edges
    between two identity-but-not-uri-equal nodes.

    Architect's framing (2026-06-13): the original
    test_no_compact_form_for_migrated_subjects only checked 4 specific
    names. There were ~30 OTHER compact-form OntologyClass nodes the
    test never looked at — a guard whose scope was strictly smaller
    than the regression class it was meant to catch. This test widens
    the scope to the class itself: ANY compact-form OntologyClass URI
    is a violation.

    Caveat documented in tests/routing/STATE_GATEWAY_V02.md
    "2026-06-13 compact-form cleanup": a SMALL set of compact-form
    OntologyClass nodes don't yet have canonical full-IRI counterparts
    declared (e.g. data:Dashboard, data:Dataset). Those are banked as
    TBox-decision items. This guard correctly stays red on them —
    that redness is the punch-list, not a flaw in the guard. When the
    TBox declarations land, the canonical pipeline ingests them, the
    migrate-into-canonical cleanup runs, and this guard goes green.

    2026-06-15 update: mesh:Thing — previously banked as a TBox
    declaration item — was traced via pre-flight provenance grouping
    to a synthetic catch-all built by a vanished ad-hoc loader. It is
    NOT a legitimate class needing declaration; it's a deletion target.
    Cleanup pending; see STATE_GATEWAY_V02.md "2026-06-15 mesh:Thing
    investigation" for the writer-hunt trace and the tiered cleanup
    plan.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:OntologyClass)
            WHERE any(p IN $prefixes WHERE c.uri STARTS WITH p)
            RETURN c.uri AS uri ORDER BY uri
            """,
            prefixes=list(_COMPACT_PREFIXES_NAMESPACE_MAP),
        )
        violations = [r["uri"] for r in result]

    if violations:
        # Distinguish "has known canonical equivalent" (cleanup-able)
        # from "needs TBox declaration" (banked).
        canonical_check_rows = session.run if False else None  # placeholder
        with driver.session() as session2:
            details = []
            for compact in violations:
                prefix = compact.split(":", 1)[0] + ":"
                local = compact.split(":", 1)[1]
                expected_full = _COMPACT_PREFIXES_NAMESPACE_MAP[prefix] + local
                has_canonical = session2.run(
                    "MATCH (c:OntologyClass {uri: $u}) RETURN c.uri AS u",
                    u=expected_full,
                ).single()
                details.append((compact, expected_full, has_canonical is not None))

        cleanup_able = [d for d in details if d[2]]
        needs_tbox = [d for d in details if not d[2]]
        lines = [f"{len(violations)} compact-form OntologyClass nodes detected."]
        if cleanup_able:
            lines.append(f"  CLEANUP-ABLE ({len(cleanup_able)}): canonical exists, merge-into-canonical + delete compact:")
            for c, f, _ in cleanup_able[:30]:
                lines.append(f"    {c!r} -> {f!r}")
        if needs_tbox:
            lines.append(f"  NEEDS TBOX DECLARATION ({len(needs_tbox)}): no canonical full-IRI in substrate yet:")
            for c, f, _ in needs_tbox:
                lines.append(f"    {c!r} (expected canonical: {f!r})")
        lines.append("See STATE_GATEWAY_V02.md '2026-06-13 compact-form cleanup' for the merge-into-canonical migration design.")
        raise AssertionError("\n".join(lines))


def test_no_blank_node_ontology_classes(driver):
    """**The blank-node phantom guard (2026-06-15).** :OntologyClass
    nodes whose URI matches the rdflib BNode shape (`N[a-f0-9]{16,}`,
    e.g. `N026ed32773d9479cbe31277701541cc1`) are RDF authoring
    artifacts that leaked through a broken blank-node filter in the
    canonical pipeline (sync_jena_ontologies_to_neo4j) between
    Session 2 and 2026-06-15.

    Architect's framing (2026-06-15): the original blank-node filter
    in ontology_assets.py:390 checked `uri.startswith("Bnode_")` and
    `"_:"` — neither matches rdflib's `BNode.__str__` output
    (`N[a-f0-9]{32}`). The filter was a no-op for the entire lifetime
    of the canonical pipeline; every imported ontology with anonymous
    owl:Class restrictions (PROV-O, IOF_Core, S3000L, DINEN62264,
    IOF_MRO) leaked its blank-node restrictions into Neo4j as bogus
    :OntologyClass nodes.

    Discovery: the mesh:Thing investigation's pre-flight provenance
    grouping. Counting blank-node :OntologyClass by `synced_by`
    revealed 441 nodes with `synced_by='sync_jena_ontologies_to_neo4j'`
    — Writer C, the current canonical pipeline, in active source.
    The "fix-the-writer-first" rule applied in its strong form: the
    SPARQL extract_query in ontology_assets.py was fixed (FILTER
    `!isBlank(?uri)` primary, Python isinstance defensive) BEFORE
    cleanup proceeded. See doc-tools'
    test_ontology_assets_blank_node_filter.py for the source-side
    acceptance test.

    This guard is the substrate-side watchman that catches any future
    regression in the writer: a re-introduction of the broken filter
    (or a new pipeline emitting blank-node :OntologyClass) trips this
    test red on the next CI run. Pairs with the source-side test in
    doc-tools so both layers must be intact for the cleanup to stay
    durable.

    Blank-node :OntologyClass nodes are categorically distinct from
    compact-form ones — they have no canonical equivalent to migrate
    TO (they're not real concepts), so the cleanup is delete, not
    canonicalize. The widened compact-form guard
    (test_no_compact_form_ontology_classes) covers the compact-form
    regression class; this guard covers the blank-node regression
    class. Same architectural shape, different shape detection.
    """
    with driver.session() as session:
        result = session.run(
            r"""
            MATCH (c:OntologyClass)
            WHERE c.uri =~ '^[nN][a-f0-9A-F]{16,}.*'
            RETURN c.uri AS uri, c.synced_by AS synced_by,
                   c.ingest_run_id AS run_id,
                   c.source_ontology AS src
            ORDER BY synced_by, src
            LIMIT 50
            """,
        )
        violations = [(r["uri"], r["synced_by"], r["run_id"], r["src"]) for r in result]
        total = session.run(
            r"""
            MATCH (c:OntologyClass) WHERE c.uri =~ '^[nN][a-f0-9A-F]{16,}.*'
            RETURN count(c) AS n
            """,
        ).single()["n"]

    if total:
        # Group by writer fingerprint so the failure message points
        # directly at which pipeline created the regression — the
        # same provenance-grouping pattern that uncovered Writer C
        # during the mesh:Thing investigation.
        with driver.session() as s2:
            by_writer = s2.run(
                r"""
                MATCH (c:OntologyClass) WHERE c.uri =~ '^[nN][a-f0-9A-F]{16,}.*'
                RETURN coalesce(c.synced_by, '<none>') AS synced_by,
                       coalesce(c.ingest_run_id, '<none>') AS run_id,
                       coalesce(c.source_ontology, '<none>') AS src,
                       count(*) AS n
                ORDER BY n DESC
                """,
            ).data()

        lines = [
            f"{total} blank-node :OntologyClass nodes detected "
            f"(uri matches rdflib BNode shape N[a-f0-9]{{16,}}). "
            f"These are RDF authoring artifacts (typically owl:Class "
            f"restrictions from anonymous unionOf/intersectionOf/"
            f"Restriction expressions in imported ontologies), not "
            f"resolver targets. They should be filtered at ingest, "
            f"not materialized.",
            "",
            "By writer fingerprint:",
        ]
        for row in by_writer:
            lines.append(
                f"  n={row['n']:5d}  synced_by={row['synced_by']!r}  "
                f"run_id={row['run_id']!r}  src={row['src']!r}"
            )
        lines.append("")
        lines.append("Likely cause (if synced_by='sync_jena_ontologies_to_neo4j'):")
        lines.append(
            "  the canonical-pipeline blank-node filter regressed. "
            "Check doc_tools/assets/ontology_assets.py for the "
            "`FILTER(!isBlank(?uri))` SPARQL clause and the "
            "`isinstance(row.uri, rdflib.term.BNode)` Python check. "
            "The acceptance test in "
            "doc-tools/tests/test_ontology_assets_blank_node_filter.py "
            "covers both layers."
        )
        lines.append("")
        lines.append("Sample violations (up to 10):")
        for uri, synced_by, run_id, src in violations[:10]:
            lines.append(f"  {uri!r}")
        raise AssertionError("\n".join(lines))


def test_no_path_derived_domains(driver):
    """**The explicit-per-file domain guard (2026-06-16).** Every
    :OntologyClass node MUST have a `domain` that matches the explicit
    declaration in `setup/prime_databases.py:CANONICAL_TTL_MANIFEST`
    for its `synced_from` s3 path. No domain may come from the
    writer's path-derivation fallback (legacy mechanism removed
    2026-06-16 after producing confidently-wrong routing for the B4-V1
    fault-isolation question).

    Architect's framing (2026-06-15 late late): "path-derivation
    demoted to flagged-fallback-or-removed. Every domain is asserted,
    none derived. The guard catches the next mil/-shaped bug at CI
    — a new TTL added without an explicit domain declaration trips
    it, instead of silently landing wherever its path happens to
    derive."

    What this guard catches:
    1. A future ingest path bypassing the explicit-declaration
       mechanism (e.g., a one-off seed that doesn't pass
       extra_metadata.domain AND lands in a bucket without
       x-amz-meta-domain).
    2. A drift in CANONICAL_TTL_MANIFEST where an entry's declared
       domain doesn't match what's in the substrate (e.g., someone
       updates the manifest but doesn't re-run the pipeline).
    3. The original mil_extension.ttl bug: the manifest had
       domain='MIL' (path-name-derived) while the resolver queries
       with semantic domain 'MAINTENANCE'.

    Read the failure message for the specific mismatched (synced_from,
    expected_domain, observed_domain) triple. The fix is one of:
    - Update CANONICAL_TTL_MANIFEST's entry for that path to the
      correct semantic domain
    - Re-run the canonical pipeline so the substrate picks up the
      manifest's declaration
    - Delete substrate entries from a deprecated/residue write path
      that no longer goes through the canonical pipeline (e.g., the
      pre-existing Munitions residue at MAINTENANCE — banked as
      separate cleanup, exempt below)
    """
    # CANONICAL_TTL_MANIFEST source-of-truth. Each entry maps a
    # synced_from s3 key to its declared semantic domain. Copied here
    # to avoid cross-repo import (the manifest lives in
    # invincible-agent/setup/prime_databases.py but this test is in
    # tests/routing/). If the manifest there changes, this map must
    # be updated — drift between them is a regression this guard
    # catches indirectly (manifest disagreement → substrate mismatch
    # → this test fires).
    DECLARED_DOMAINS_BY_S3_KEY = {
        # MAINTENANCE
        "maintenance/IOF_Core.rdf":                 "MAINTENANCE",
        "maintenance/IOF_MRO.rdf":                  "MAINTENANCE",
        "maintenance/DINEN62264.owl":               "MAINTENANCE",
        "maintenance/mro_extension.ttl":            "MAINTENANCE",
        "maintenance/maintenance_extension.ttl":    "MAINTENANCE",
        "mil/mil_extension.ttl":                    "MAINTENANCE",   # CORRECTED 2026-06-16 from 'MIL'
        # SUSTAINMENT
        "sustainment/IOF_Core.rdf":                 "SUSTAINMENT",
        "sustainment/S3000L.ttl":                   "SUSTAINMENT",
        # DATA_ENGINEERING
        "idp/PROV-O.ttl":                           "DATA_ENGINEERING",
        "idp/idp_extension.ttl":                    "DATA_ENGINEERING",
        # MESH (system ontology)
        "mesh/mesh_system.ttl":                     "MESH",
    }

    # Entries that are KNOWN deprecated/residue (not currently in the
    # canonical pipeline) — exempt from this guard until they're
    # either retired or re-ingested with correct domain. The mesh:Thing
    # arc retired 1,191 phantom blank nodes; Munitions follows the
    # same shape (deprecated direct-load residue, sitting at the
    # wrong domain because the writer that wrote it is gone). Listing
    # them here is a banked-not-blocked declaration.
    KNOWN_RESIDUE_EXEMPT = {
        "mro/IOF_Core.rdf",
        "mro/MIL_Unified.ttl",
        "mro/Munitions.ttl",
        "sustainment/PCN_PDN_Extension.ttl",
    }

    with driver.session() as session:
        rows = session.run(
            r"""
            MATCH (c:OntologyClass)
            WHERE c.synced_from IS NOT NULL
            WITH replace(c.synced_from, 's3://ontologies/', '') AS s3_key,
                 c.domain AS observed_domain,
                 count(*) AS n
            RETURN s3_key, observed_domain, n
            ORDER BY s3_key
            """
        ).data()

    violations = []
    for row in rows:
        s3_key = row["s3_key"]
        observed = row["observed_domain"]
        if s3_key in KNOWN_RESIDUE_EXEMPT:
            continue
        declared = DECLARED_DOMAINS_BY_S3_KEY.get(s3_key)
        if declared is None:
            violations.append((
                s3_key, "<not in manifest>", observed, row["n"],
                "UNDECLARED",
            ))
        elif observed != declared:
            violations.append((
                s3_key, declared, observed, row["n"],
                "DECLARED_MISMATCH",
            ))

    if violations:
        lines = [
            f"{sum(v[3] for v in violations)} :OntologyClass nodes "
            f"across {len(violations)} ingest paths have a domain that "
            f"does not match the explicit declaration in "
            f"setup/prime_databases.py:CANONICAL_TTL_MANIFEST. "
            f"Domain-by-derivation-instead-of-declaration is the "
            f"regression class this guard catches.",
            "",
            "Violations:",
        ]
        for s3_key, declared, observed, n, kind in violations:
            lines.append(
                f"  [{kind}] n={n:4d}  s3_key={s3_key!r:42s}  "
                f"declared={declared!r}  observed={observed!r}"
            )
        lines.append("")
        lines.append("Remediation paths:")
        lines.append(
            "  - DECLARED_MISMATCH: re-run the canonical pipeline for "
            "this s3_key (manifest is the source of truth; substrate "
            "should reflect it after re-ingest)."
        )
        lines.append(
            "  - UNDECLARED: either (a) add the s3_key to "
            "CANONICAL_TTL_MANIFEST with its semantic domain, then "
            "re-ingest, OR (b) add to KNOWN_RESIDUE_EXEMPT in this "
            "test if it's deprecated direct-load residue that's banked "
            "for separate cleanup."
        )
        raise AssertionError("\n".join(lines))


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
    """Every known (verb_iri, _tool_urn) registration has an edge typed
    against the expected real subject class at canonical (full IRI) form.

    Registration identity is the PAIR (verb_iri, _tool_urn), not the bare
    verb_iri (ADR-0019 §Contract D addendum, 2026-06-12). This test pins
    one expected (input_uri, output_uri) per (verb_iri, _tool_urn) pair
    rather than per verb_iri, which is what the multi-registration
    pattern (Engine E's two registrations of mesh:queryKnowledgeGraph
    against WorkInstruction + ProcedureStep) actually needs.

    Catches the failure modes:
      a) Re-registration through the gateway reverts to a pseudo-class
         OR compact form (per-pair, so a multi-registered verb regressing
         on ONE of its registrations doesn't hide behind the other one).
      b) The match-key from a44b9fb regresses — two registrations under
         distinct _tool_urns collapse onto one edge with last-write-wins.
         Pinning by pair makes the collapse fail loudly.
      c) The dict-overwrite race that bit us 2026-06-13 (Cypher returning
         multiple edges per verb_iri and the dict landing on whichever
         came last). Keying by pair structurally eliminates it.
    """
    # Tool URN suffix → expected (input_uri, output_uri). Suffix used
    # because the engine_X_name part is what registrations actually
    # control; the leading "urn:li:mlModel:(urn:li:dataPlatform:mesh,"
    # is boilerplate.
    expected_by_pair = {
        ("mesh:queryKnowledgeGraph", "engine_e_neo4j_expert"): (
            WORK_INSTRUCTION, GRAPH_EXPERT_RESPONSE,
        ),
        ("mesh:queryKnowledgeGraph", "engine_e_neo4j_expert_procedure_step"): (
            PROCEDURE_STEP, GRAPH_EXPERT_RESPONSE,
        ),
        ("mesh:retrieveKnowledge", "engine_w_weaviate_expert"): (
            TECHNICAL_MANUAL, KNOWLEDGE_RETRIEVAL_RESPONSE,
        ),
    }
    verbs = sorted({verb for verb, _ in expected_by_pair})
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s)-[r]->(o) WHERE r.iri IN $verbs
              AND r._tool_urn IS NOT NULL
            RETURN r.iri AS verb,
                   r._tool_urn AS tool_urn,
                   s.uri AS input_uri,
                   o.uri AS output_uri,
                   r._input_uri AS recorded_input
            """,
            verbs=verbs,
        )
        # Key by (verb_iri, tool_urn_name). Collect a SET of triples per
        # key so multiple edges under one identity (orphans, leftover
        # legacy rows) don't mask the expected one.
        actual_by_pair: dict[tuple[str, str], set] = {}
        for rec in result:
            urn = rec["tool_urn"] or ""
            # Extract the engine_X_name suffix from the URN.
            name_part = urn.rsplit(",", 2)[-2] if urn.count(",") >= 2 else urn
            key = (rec["verb"], name_part)
            actual_by_pair.setdefault(key, set()).add(
                (rec["input_uri"], rec["output_uri"], rec["recorded_input"])
            )
    for (verb, urn_suffix), (want_in, want_out) in expected_by_pair.items():
        edges = actual_by_pair.get((verb, urn_suffix), set())
        assert edges, (
            f"Registration ({verb}, _tool_urn=…{urn_suffix},…) has no v0.2 "
            f"saga edge. Either the engine isn't registered or the "
            f"a44b9fb match-key regressed — check mesh-registrar logs "
            f"for `Registered {verb}` and gateway saga output."
        )
        want = (want_in, want_out, want_in)
        assert want in edges, (
            f"({verb}, _tool_urn=…{urn_suffix},…): expected "
            f"(input={want_in!r}, output={want_out!r}, "
            f"recorded_input={want_in!r}) not found among the "
            f"registration's edges. Actual:\n"
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


# -----------------------------------------------------------------------------
# Substrate DNS guard — the sibling of `tests/routing/test_no_legacy_dns_references.py`
#
# The 2026-06-17 incident that motivated this guard: a user's UI query
# ("what tables do you have?") timed out because the supervisor dispatched
# to a legacy-DNS endpoint (`restate-agent-svc.default.svc.cluster.local:8081`).
# The SOURCE-side guard (`test_no_live_legacy_dns_references`) was GREEN —
# every source file's default URL had been class-fixed in the
# legacy-DNS sweep. But TEN substrate verb edges still carried the
# legacy URL, because they had been registered by OLDER images (pre-fix
# source defaults), and nothing had re-registered them after the source
# fix landed. The class-fix at the source layer didn't propagate to
# the materialized substrate edges until the engine pods rolled over
# with a corrected env var or rebuilt image.
#
# **The architectural lesson (third instance of the pattern):**
# source-clean does NOT imply runtime-clean. Registration materializes
# source-time defaults into substrate edges; edges materialized BEFORE
# a source fix retain the old value until something re-registers.
#
# Prior instances of the same pattern:
#   - compact-form classes: source guard green while compact-form
#     :OntologyClass nodes sat in Neo4j (closed by adding the substrate
#     `test_no_compact_form_ontology_classes` guard).
#   - mesh-registrar chart-vs-cluster gap: chart's `meshRegistrar.enabled`
#     default was false while a manually-deployed pod ran; source-side
#     inspection couldn't see the inconsistency; the rehearsal caught it.
#
# **Standing rule earned:** every source-level guard needs a substrate-
# level sibling, because registration is what crosses the layer boundary
# and substrate edges outlive the source-time defaults they were minted
# from. When you add a source guard, ask: "what's the substrate version
# of this property, and is it guarded too?"
#
# This guard is the substrate sibling of `test_no_live_legacy_dns_references`.
# It runs the same scan in Neo4j, asserting zero verb edges with the legacy
# DNS pattern in their `endpoint_url`. Together the source + substrate
# guards close the class: source-clean stays source-clean (source guard);
# any past or future materialization of legacy DNS into substrate trips
# at CI (substrate guard) before it can break dispatch.
LEGACY_DNS_FRAGMENT = ".default.svc.cluster.local"


def test_no_legacy_dns_in_substrate_verb_edges(driver):
    """No verb edge in Neo4j may carry a `*-svc.default.svc.cluster.local`
    URL in its endpoint_url. Substrate-side sibling of the source-level
    `tests/routing/test_no_legacy_dns_references.py` guard.

    If this fails: the substrate contains verb edges whose endpoint URLs
    point to non-resolvable legacy K8s service names. Dispatch will fail
    on these — supervisor → engine fails at DNS, the dagster run dies,
    cortex_bff times out. The fix is the same shape as the 2026-06-17
    Engine A + DA incident: pin the relevant engine's `ENGINE_*_PUBLIC_URL`
    in the deployment's env (helm values), restart the engine pod, and
    let mesh-registrar's idempotent v0.2 saga MERGE update the edges via
    re-registration.

    The pre-fix incident: user's query routed to mesh:enumerateCatalog →
    dispatched to `http://restate-agent-svc.default.svc.cluster.local:8081/analyze`
    → DNS failure → dagster run failed in 17s. Substrate had 10 verb edges
    with legacy DNS that the source guard couldn't see.
    """
    with driver.session() as session:
        offenders = session.run(
            """
            MATCH (s:OntologyClass)-[r]->(o:OntologyClass)
            WHERE r.iri IS NOT NULL
              AND r.endpoint_url CONTAINS $fragment
            RETURN
                r.iri          AS verb_iri,
                s.uri          AS subject_uri,
                r.endpoint_url AS endpoint_url,
                r._tool_urn    AS tool_urn
            ORDER BY r.iri, s.uri
            """,
            fragment=LEGACY_DNS_FRAGMENT,
        ).data()
    assert not offenders, (
        f"Found {len(offenders)} substrate verb edge(s) with legacy DNS "
        f"pattern '{LEGACY_DNS_FRAGMENT}' in endpoint_url. These edges "
        f"will FAIL DISPATCH (legacy service names don't resolve in "
        f"current cluster). Fix shape (per the 2026-06-17 Engine A + DA "
        f"incident):\n"
        f"  1. Identify which engine owns each edge (group by tool_urn "
        f"     or subject_uri).\n"
        f"  2. Pin that engine's ENGINE_*_PUBLIC_URL in helm values "
        f"     pointing at the actual K8s service "
        f"     (`iagent-<component>:<port>`).\n"
        f"  3. helm upgrade + kubectl rollout restart the engine pod.\n"
        f"  4. Engine re-registers via mesh-registrar's idempotent v0.2 "
        f"     saga; MERGE updates the edge endpoint_url in place.\n"
        f"  5. Re-run this guard; verify zero offenders.\n"
        f"\n"
        f"Offending edges:\n"
        + "\n".join(
            f"    - {e['verb_iri']} from {e['subject_uri']} "
            f"-> {e['endpoint_url']} (tool_urn={e['tool_urn']})"
            for e in offenders
        )
    )
