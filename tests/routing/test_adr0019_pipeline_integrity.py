"""ADR-0019 Axis 2 — pipeline integrity (Contracts C and D).

Companion to ``test_adr0019_contracts.py`` (routing decisions, Axis 1) and
``test_adr0019_engine_o_contract_a.py`` (Contract A teeth). This file
covers the **substrate** contracts — the ones that protect the two
graphs the routing layer rides on from silent drop and silent
corruption.

Why these are SKIPPED today
---------------------------
Axis 1 tests assert routing behavior the supervisor / Engine O already
implement (correctly or incorrectly). Axis 2 tests assert behavior that
**does not exist anywhere in the code yet** — there is no self-
verifying registration check, no snapshot/diff tool, no Contract D
range-validation hook. Stubbing those into existence in tests would
mean inventing an interface the production code hasn't committed to,
and the tests would lock in the wrong shape before the design lands.

So each case here is documented as a ``pytest.mark.skip`` with a
specific reason that names:

  - which ADR-0019 contract it asserts,
  - what production surface needs to exist to lift the skip,
  - what the test will assert once that surface exists.

When the Contract C/D work lands, the developer removes the skip
marker on each case and the test becomes load-bearing. Until then, the
matrix's pytest run surfaces these cases by name (as `s` in pytest's
output), so the gap stays visible — neither silently green nor red.

Contracts in scope here
-----------------------
**Contract C** (two-pipeline integrity):

  - Self-verifying registration: after ``register_engine_to_mesh()``,
    the verb landed in BOTH Neo4j and Weaviate; mismatch fails loud.
  - Canonical ingestion reproduces hand-seeds: ``ingest_ontology_job``
    materializes the same records ops hand-seeded via Weaviate REST.
  - Ontology snapshot diff: a deploy that drops class count or
    ``subClassOf`` edges relative to the known-good snapshot raises
    an alarm before routing sees it.
  - Substrate write-surface separation: TBox mirror / predicate
    registry / ABox are not editable as one blob — an agent
    "optimizing routing" cannot prune classes as a side effect of
    touching verbs.

**Contract D** (typed-range validation, no auto-MERGE):

  - Valid range registers: verb with ``input_uri`` and ``output_uri``
    that resolve to pre-existing ``:OntologyClass`` nodes is accepted.
  - Invalid range REJECTED: verb whose declared input/output URIs
    are not real classes in the loaded substrate is rejected with a
    loud error naming the offending URI. **No phantom**
    ``:OntologyClass`` **node is created.** This is the silent-MERGE
    trap that pollutes the noun graph.
  - Phantom scan: post-registration, no ``:OntologyClass`` exists
    with zero ``subClassOf`` edges AND no ingestion provenance.

Out of scope for THIS file
--------------------------
The ``expected_questions`` canary (ADR-0015 promoted to required by
ADR-0019 §4) is a separate runtime concern, not a registration-time
contract. It belongs in its own test once the canary harness lands.
This file is registration-time integrity only.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest


# ---------------------------------------------------------------------------
# Live-cluster gating
# ---------------------------------------------------------------------------
#
# A few cases below assert OUTCOMES that are observable against the live
# substrate today (phantom :OntologyClass nodes, dual-store registration
# gaps). They run when the cluster's Neo4j and Weaviate are reachable;
# they skip with a reason naming the missing infrastructure when not.
#
# This is the skip-vs-fail discriminator that ADR-0019's matrix
# specifically requires: a contract violation observable against current
# code is a FAILING test (RED in CI when the cluster is up); a contract
# whose test surface does not yet exist is a SKIP. The infrastructure
# gating here distinguishes "I cannot reach the substrate" (skip) from
# "I reached the substrate and the contract is violated" (fail).

_NEO4J_BOLT_URL = os.getenv("NEO4J_URI", "bolt://localhost:7687")
_NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme-neo4j-sandbox")
_WEAVIATE_BASE = os.getenv(
    "WEAVIATE_BASE_URL",
    f"http://{os.getenv('WEAVIATE_HOST', 'localhost')}:"
    f"{os.getenv('WEAVIATE_PORT', '8080')}",
)


def _neo4j_driver():
    """Return a Neo4j driver, or None if the import or connection fails.

    Importing neo4j is fine (it's in the base deps), but the driver
    construction itself is what fails when the cluster isn't reachable.
    Caller treats None as the gating signal.
    """
    try:
        from neo4j import GraphDatabase  # noqa: WPS433
    except ImportError:
        return None
    try:
        drv = GraphDatabase.driver(
            _NEO4J_BOLT_URL, auth=(_NEO4J_USER, _NEO4J_PASSWORD),
        )
        # Verify connectivity once so the test skips cleanly rather
        # than hitting a session-level error mid-assertion.
        drv.verify_connectivity()
        return drv
    except Exception:
        try:
            drv.close()
        except Exception:
            pass
        return None


def _weaviate_get(path: str, timeout: float = 5.0) -> dict | None:
    """GET a Weaviate REST path, or None if unreachable. Same gating
    pattern as ``_neo4j_driver``.

    Weaviate's ``/v1/.well-known/ready`` returns 200 with an empty
    body, so an empty body counts as success (returns ``{}``) and
    only network/JSON errors return None.
    """
    url = f"{_WEAVIATE_BASE.rstrip('/')}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return {}
            return json.loads(body)
    except (urllib.error.URLError, OSError, ValueError):
        return None


@pytest.fixture(scope="module")
def neo4j_driver():
    drv = _neo4j_driver()
    if drv is None:
        pytest.skip(
            "Live-cluster contract test skipped: Neo4j not reachable at "
            f"{_NEO4J_BOLT_URL}. Set NEO4J_URI/NEO4J_USERNAME/"
            "NEO4J_PASSWORD env vars to point at a running cluster "
            "(e.g. `kubectl -n sandbox port-forward svc/iagent-neo4j "
            "7687:7687`)."
        )
    yield drv
    drv.close()


@pytest.fixture(scope="module")
def weaviate_ready():
    """Skip if Weaviate REST isn't reachable. Returns the base URL."""
    if _weaviate_get("/v1/.well-known/ready") is None:
        pytest.skip(
            "Live-cluster contract test skipped: Weaviate not reachable "
            f"at {_WEAVIATE_BASE}. Set WEAVIATE_HOST/WEAVIATE_PORT env "
            "vars to point at a running cluster (e.g. `kubectl -n "
            "sandbox port-forward svc/iagent-weaviate 8080:8080`)."
        )
    return _WEAVIATE_BASE


# Common skip reasons — kept as constants so the wording is consistent
# across cases. The reason is the punch-list entry.
_C_SELF_VERIFY = (
    "ADR-0019 Contract C — self-verifying registration not yet implemented. "
    "Production surface needed: a post-registration verification hook that "
    "reads back the verb from both Neo4j and Weaviate after "
    "register_engine_to_mesh() returns, and raises a loud error (alarm, "
    "exception) if either store is missing the record. Once that hook "
    "exists, lift this skip and assert: register a verb → both stores show "
    "it; simulate a Weaviate-write failure → registration raises."
)
_C_INGEST_REPRODUCES = (
    "ADR-0019 Contract C — canonical ingestion path (ingest_ontology_job + "
    "doc-tools sensor) not yet exercised in test. Production surface needed: "
    "a deterministic test harness that runs the registration → DataHub → "
    "doc-tools sensor → Neo4j+Weaviate chain end-to-end against a sandbox "
    "stack. Once that harness exists, assert: hand-seeded enumerateCatalog "
    "+ analyzeDataset records exactly match what ingest_ontology_job "
    "materializes from the same engine's register_engine_to_mesh() call. "
    "The band-aid becomes redundant; the canonical path is proven."
)
_C_SNAPSHOT_DIFF = (
    "ADR-0019 Contract C — ontology snapshot/diff tooling does not exist. "
    "Production surface needed: (a) a known-good snapshot of the noun "
    "graph (class count, subClassOf edge count, top-level taxonomy hash), "
    "(b) a diff function that compares a live Neo4j read against the "
    "snapshot, (c) an alarm threshold (e.g. >5% class drop = block "
    "routing, >0% drop = warn). Once these exist, assert: an artificially "
    "depleted graph triggers the alarm; an identical graph diffs clean; "
    "a small intentional addition diffs as an addition, not a regression."
)
_C_WRITE_SURFACE_SEPARATION = (
    "ADR-0019 Contract C — TBox/registry/ABox write-surface separation is "
    "a structural design commitment without an enforcement mechanism yet. "
    "Production surface needed: separate Neo4j roles/credentials per "
    "write surface, OR an audit log on Neo4j writes that flags cross-"
    "surface edits, OR APOC procedures that gate the cross-edits. Once "
    "in place, assert: an attempted predicate-registry write that also "
    "modifies a TBox class is rejected/audited; the trigger-incident "
    "shape (verb-only optimization that wipes classes) cannot reproduce."
)
_D_VALID_RANGE = (
    "ADR-0019 Contract D — typed-range validation hook does not exist in "
    "register_engine_to_mesh() yet. Production surface needed: at "
    "registration time, look up input_uri and output_uri in the loaded "
    "Neo4j noun graph; if both exist as :OntologyClass nodes, accept and "
    "create the verb edge. Once the hook exists, this case asserts the "
    "accept-path: a verb whose declared range types are real classes "
    "registers successfully and the edge appears in both stores."
)
_D_INVALID_RANGE_REJECTED = (
    "ADR-0019 Contract D — register_engine_to_mesh() currently auto-MERGEs "
    "input/output classes on the verb edge (no validation), which silently "
    "creates phantom :OntologyClass nodes when the URI is invented. "
    "Production surface needed: REPLACE the MERGE with a MATCH that fails "
    "loud if the class doesn't pre-exist. Once that change lands, this "
    "case asserts: registering a verb with input_uri='mesh:NotAClass' "
    "raises a specific exception naming the offending URI, AND a post-"
    "registration scan finds zero new :OntologyClass nodes."
)
_D_PHANTOM_SCAN = (
    "ADR-0019 Contract D — phantom scan utility does not exist. "
    "Production surface needed: a Cypher query that returns "
    "(:OntologyClass) nodes with zero subClassOf edges AND no "
    "ingestion-provenance property; an operational job that runs the scan "
    "and alarms on non-empty results. Once in place, assert: after a "
    "battery of valid + invalid registration attempts, the scan returns "
    "zero phantoms; if the MERGE-instead-of-MATCH regresses, this scan "
    "catches it before users do."
)


# ---------------------------------------------------------------------------
# Contract C — two-pipeline integrity
# ---------------------------------------------------------------------------
def test_C_register_lands_in_both_stores(neo4j_driver, weaviate_ready):
    """**Runnable today.** Outcome assertion: every verb edge in Neo4j
    that carries an ``r.iri`` (= a registered tool, per
    ``/find_compatible_verbs``' filter) MUST also have a matching
    Predicate record in Weaviate. Symmetrically: every Weaviate
    Predicate record's ``verb_iri`` MUST exist as a Neo4j edge.

    The morning-report ``enumerateCatalog`` + ``analyzeDataset`` gap is
    exactly this contract being broken — those edges existed in Neo4j
    (planted by hand for the smoke test) but the Predicate corpus in
    Weaviate didn't have them until they were REST-seeded. Red today
    likely means there's still drift, OR the registration path is
    dropping records.

    The assertion prints both directions of the diff so the red test
    doubles as the cleanup worklist (which verbs to re-register, which
    Weaviate stragglers to evict).
    """
    # Pull the verb IRIs from Neo4j (the routing graph half).
    def _read_neo4j_verbs():
        with neo4j_driver.session() as s:
            return {
                r["verb_iri"]
                for r in s.run(
                    "MATCH ()-[r]->() WHERE r.iri IS NOT NULL "
                    "RETURN DISTINCT r.iri AS verb_iri"
                )
                if r["verb_iri"]
            }
    neo4j_verbs = _read_neo4j_verbs()

    # Pull verb IRIs from Weaviate Predicate collection (the corpus half).
    weaviate_payload = _weaviate_get(
        "/v1/objects?class=Predicate&limit=200",
    )
    assert weaviate_payload is not None, (
        "Weaviate became unreachable mid-test; the fixture should have "
        "caught this. Re-running with WEAVIATE_BASE_URL set explicitly "
        "may help."
    )
    weaviate_verbs = {
        o["properties"].get("verb_iri")
        for o in (weaviate_payload.get("objects") or [])
        if o.get("properties", {}).get("verb_iri")
    }

    only_in_neo4j = sorted(neo4j_verbs - weaviate_verbs)
    only_in_weaviate = sorted(weaviate_verbs - neo4j_verbs)

    assert not only_in_neo4j and not only_in_weaviate, (
        f"\nADR-0019 Contract C — dual-store landing FAILED.\n"
        f"  Neo4j-side total: {len(neo4j_verbs)}\n"
        f"  Weaviate-side total: {len(weaviate_verbs)}\n"
        f"  Verbs in Neo4j but missing in Weaviate "
        f"({len(only_in_neo4j)}): {only_in_neo4j}\n"
        f"  Verbs in Weaviate but missing in Neo4j "
        f"({len(only_in_weaviate)}): {only_in_weaviate}\n"
        f"\nFix path: re-run register_engine_to_mesh() for the "
        f"missing-in-Weaviate entries, OR run doc-tools' "
        f"ingest_ontology_job so the canonical pipeline reconciles "
        f"both stores. Hand-seeding via Weaviate REST is the band-aid "
        f"Contract C forbids as a steady state."
    )


@pytest.mark.skip(reason=_C_SELF_VERIFY)
def test_C_weaviate_write_failure_raises():
    """Simulate the Weaviate write half failing. register_engine_to_mesh()
    must raise a specific exception, NOT swallow it and report success.
    Silent partial success is exactly the failure mode that produced the
    enumerateCatalog/analyzeDataset gap.
    """
    pytest.fail("intentional placeholder — see skip reason")


@pytest.mark.skip(reason=_C_INGEST_REPRODUCES)
def test_C_ingest_job_reproduces_handseeded_records():
    """Run ingest_ontology_job against a fresh substrate; assert the
    resulting Predicate corpus matches what was hand-seeded via REST
    for enumerateCatalog + analyzeDataset. When equal, the band-aid is
    redundant; when not, the canonical path is confirmed broken.
    """
    pytest.fail("intentional placeholder — see skip reason")


@pytest.mark.skip(reason=_C_SNAPSHOT_DIFF)
def test_C_snapshot_diff_detects_class_drop():
    """Drop 10% of classes from a working substrate copy; the diff must
    flag it as a regression alarm before any routing call observes the
    drop. The trigger-incident shape (agent wipes the ontology) must
    become detectable within minutes, not by user-facing wrong answers.
    """
    pytest.fail("intentional placeholder — see skip reason")


@pytest.mark.skip(reason=_C_SNAPSHOT_DIFF)
def test_C_snapshot_diff_passes_clean_substrate():
    """An unchanged substrate must diff clean against its own snapshot.
    Tests the false-positive floor — alarms should fire on regressions,
    not on normal operation.
    """
    pytest.fail("intentional placeholder — see skip reason")


@pytest.mark.skip(reason=_C_WRITE_SURFACE_SEPARATION)
def test_C_predicate_write_cannot_modify_tbox():
    """An attempted predicate-registry write that also touches an
    :OntologyClass node (the trigger-incident shape: verb optimization
    that prunes classes as a side effect) must be rejected or audited.
    Structural anti-regression for the wipe.
    """
    pytest.fail("intentional placeholder — see skip reason")


# ---------------------------------------------------------------------------
# Contract D — typed-range validation, no auto-MERGE
# ---------------------------------------------------------------------------
@pytest.mark.skip(reason=_D_VALID_RANGE)
def test_D_valid_range_registers():
    """A verb with input_uri and output_uri that both resolve to
    pre-existing :OntologyClass nodes registers cleanly. Baseline that
    proves the validation doesn't over-reject.
    """
    pytest.fail("intentional placeholder — see skip reason")


@pytest.mark.skip(reason=_D_INVALID_RANGE_REJECTED)
def test_D_invalid_input_uri_rejected_no_phantom_created():
    """Register a verb with input_uri='mesh:NotARealClass'. Today this
    silently MERGE-creates a phantom :OntologyClass node, making the
    verb permanently unroutable (no real subject's subClassOf walk
    reaches the phantom) AND polluting the noun graph.

    Per Contract D: the call must raise an exception that names
    'mesh:NotARealClass', and a Cypher scan immediately after must find
    ZERO new :OntologyClass nodes vs the pre-registration state.
    """
    pytest.fail("intentional placeholder — see skip reason")


@pytest.mark.skip(reason=_D_INVALID_RANGE_REJECTED)
def test_D_invalid_output_uri_rejected_no_phantom_created():
    """Same as above for output_uri. Symmetric: both endpoints must be
    validated, both silent-MERGEs are the same trap class.
    """
    pytest.fail("intentional placeholder — see skip reason")


def test_D_no_phantom_for_mesh_GraphQuery(neo4j_driver):
    """**Runnable today, framed as outcome not mechanism.** ADR-0018
    flagged Engine E's registration of ``input_uri: mesh:GraphQuery``
    as not a real ``:OntologyClass``. Contract D's outcome
    consequence: post-registration, ``mesh:GraphQuery`` MUST NOT
    exist as a phantom ``:OntologyClass`` (= a node that no canonical
    ontology load created — has no ingestion provenance properties
    AND no ``subClassOf`` to a defined ontology).

    Likely RED today: Engine E's startup MERGE-created the node when
    nothing else defined it. The fix is upstream (replace MERGE with
    MATCH in registration; fix Engine E's range to a real class) — the
    test asserts the OUTCOME, so it goes green when either fix lands
    without coupling to the mechanism choice.
    """
    with neo4j_driver.session() as s:
        rows = list(s.run(
            """
            MATCH (c:OntologyClass {uri: 'mesh:GraphQuery'})
            RETURN c.uri AS uri,
                   EXISTS { (c)-[:subClassOf]->() } AS has_out_subclass,
                   EXISTS { (c)<-[:subClassOf]-() } AS has_in_subclass,
                   keys(c) AS props
            """
        ))

    if not rows:
        # The class doesn't exist at all → Contract D upheld by absence.
        # Either Engine E was never registered, or its range was already
        # cleaned up. Pass.
        return

    row = rows[0]
    props = set(row["props"] or [])
    has_provenance = bool(props & {
        "source_ontology", "source", "ingested_at", "provenance",
        "ingest_job_id", "ingest_run_id",
    })

    is_phantom = (
        not row["has_out_subclass"]
        and not row["has_in_subclass"]
        and not has_provenance
    )

    assert not is_phantom, (
        f"\nADR-0019 Contract D — phantom :OntologyClass for "
        f"mesh:GraphQuery FAILED.\n"
        f"  Node properties: {sorted(props)}\n"
        f"  Has outgoing subClassOf: {row['has_out_subclass']}\n"
        f"  Has incoming subClassOf: {row['has_in_subclass']}\n"
        f"  Has provenance property: {has_provenance}\n"
        f"\nWhat this means: mesh:GraphQuery was MERGE-created at "
        f"Engine E's registration without being defined by any "
        f"canonical ontology load. It pollutes the noun graph and "
        f"its verb (mesh:queryKnowledgeGraph) is reachable only "
        f"through whatever subClassOf bridges were manually planted "
        f"to it. The fix is either: (a) replace MERGE with MATCH in "
        f"the registration path so invalid ranges raise loud, OR "
        f"(b) fix Engine E to register against a real class. Either "
        f"turns this assertion green."
    )


def test_D_phantom_scan_returns_zero(neo4j_driver):
    """**Runnable today.** Scan the entire ``:OntologyClass`` namespace
    for phantoms — nodes with no ``subClassOf`` edges in either
    direction AND no ingestion provenance. The scan IS the operational
    health gate Contract D §3 promises.

    Expected RED today: Engine A/E/W's registrations MERGE-created
    ``mesh:GraphQuery``, ``mesh:CatalogScopeQuery``,
    ``mesh:CatalogAssetQuery``, ``mesh:KnowledgeQuery``,
    ``mesh:DatasetAnalysisRequest``, ``mesh:AgentTask``, etc. as
    bare nodes. The smoke-test session planted some subClassOf
    bridges to fix the immediate routing, but the bare nodes remain
    until the ontology is canonically loaded with those URIs as
    classes (which the upcoming ``ingest_ontology_job`` should do).

    The assertion prints every offending URI so the red test
    doubles as the cleanup worklist.
    """
    with neo4j_driver.session() as s:
        # Phantoms: no subClassOf in or out, no provenance property.
        # Provenance properties we recognize as "canonical ingestion
        # output" — extend as the doc-tools job grows them.
        prov_keys = ("source_ontology", "source", "ingested_at",
                     "provenance", "ingest_job_id", "ingest_run_id")
        prov_predicate = " OR ".join(f"'{k}' IN keys(c)" for k in prov_keys)
        cypher = (
            f"MATCH (c:OntologyClass) "
            f"WHERE NOT EXISTS {{ (c)-[:subClassOf]->() }} "
            f"  AND NOT EXISTS {{ (c)<-[:subClassOf]-() }} "
            f"  AND NOT ({prov_predicate}) "
            f"RETURN c.uri AS uri ORDER BY c.uri"
        )
        phantoms = [r["uri"] for r in s.run(cypher) if r["uri"]]

    assert not phantoms, (
        f"\nADR-0019 Contract D — phantom :OntologyClass scan FAILED. "
        f"Found {len(phantoms)} phantom node(s):\n"
        + "".join(f"  - {p}\n" for p in phantoms)
        + "\nThese nodes have no subClassOf edges in either direction "
        "and no ingestion-provenance property — they were created by "
        "registration-time MERGE rather than canonical ontology load. "
        "They make their verb edges silently unroutable (no real "
        "subject's subClassOf walk reaches them) and pollute coverage "
        "signals.\n"
        "\nFix path (one or more):\n"
        "  - Run doc-tools' ingest_ontology_job so canonical class "
        "definitions overlay these nodes with real taxonomy + "
        "provenance.\n"
        "  - Fix engine registrations to declare input_uri/output_uri "
        "against real ontology classes (Engine E's mesh:GraphQuery is "
        "the canonical example).\n"
        "  - Replace MERGE with MATCH in the registration write path "
        "so future invalid-range registrations raise loud (Contract D "
        "mechanism)."
    )


@pytest.mark.skip(reason=_D_PHANTOM_SCAN)
def test_D_phantom_scan_detects_artificial_phantom():
    """Inject a phantom :OntologyClass directly (no subClassOf, no
    provenance); the scan must find it. Tests the scan's detection
    floor — if it can't catch a deliberate phantom, it can't catch a
    real regression.
    """
    pytest.fail("intentional placeholder — see skip reason")


# ---------------------------------------------------------------------------
# Meta-test: every case in this file is skip-with-a-reason, never silent
# ---------------------------------------------------------------------------
def test_axis2_governance_every_test_is_skip_or_fixture_gated():
    """Sanity check — every Contract C/D test in this module must EITHER
    carry a ``@pytest.mark.skip(reason=...)`` (because its production
    surface doesn't exist yet) OR depend on a live-cluster fixture
    (``neo4j_driver`` / ``weaviate_ready``) which gates skip on
    infrastructure reachability.

    Either form satisfies ADR-0019's skip-vs-fail discriminator:

      - A test whose target outcome cannot be observed today (the
        validation mechanism doesn't exist, the snapshot tool isn't
        built, the canonical ingest job hasn't materialized) ⇒
        skip with a reason naming the missing artifact.
      - A test whose target outcome IS observable today against the
        live substrate (phantom :OntologyClass nodes, dual-store
        gaps) ⇒ live-fixture-gated, runs red when the cluster is
        up and the bug is present, skips with an env-var pointer
        when the cluster is unreachable.

    Either form is auditable: the skip reason or the fixture's skip
    message name a concrete missing piece. What this meta-test
    forbids is a test function that simply ``pytest.fail()``s without
    either guard — that would be a permanent red without context.
    """
    import inspect
    import sys
    me = sys.modules[__name__]
    contract_tests = [
        (name, obj) for name, obj in inspect.getmembers(me)
        if name.startswith(("test_C_", "test_D_")) and callable(obj)
    ]
    assert len(contract_tests) > 0, "no Axis-2 contract tests found"

    live_fixtures = {"neo4j_driver", "weaviate_ready"}
    for name, fn in contract_tests:
        marks = getattr(fn, "pytestmark", [])
        has_skip = any(m.name == "skip" for m in marks)
        sig = inspect.signature(fn)
        params = set(sig.parameters)
        has_live_fixture = bool(params & live_fixtures)
        assert has_skip or has_live_fixture, (
            f"{name}: Axis-2 contract test must EITHER carry an explicit "
            f"@pytest.mark.skip(reason=...) (for surfaces that don't "
            f"exist yet) OR depend on a live-cluster fixture "
            f"({sorted(live_fixtures)}) (for outcomes observable today). "
            f"Got params={sorted(params)} marks={[m.name for m in marks]}. "
            f"A bare test with neither would be a silent permanent red "
            f"without context — the failure mode this meta-test forbids."
        )
