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

import pytest


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
@pytest.mark.skip(reason=_C_SELF_VERIFY)
def test_C_register_lands_in_both_stores():
    """After register_engine_to_mesh(), assert the verb's IRI appears in
    both Neo4j (with endpoint_url) and Weaviate (in the Predicate
    collection). The morning-report hand-seed shows the canonical path
    silently dropping records; this case forbids that.
    """
    pytest.fail("intentional placeholder — see skip reason")


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


@pytest.mark.skip(reason=_D_INVALID_RANGE_REJECTED)
def test_D_engine_e_GraphQuery_registration_blocked():
    """ADR-0018 §"Migration plan" called out Engine E's existing sloppy
    registration: input_uri='mesh:GraphQuery' which is not an
    :OntologyClass. Contract D promotes that from cosmetic nit to hard
    block — Engine E's current registration must fail Contract D's
    validation and either be quarantined or rejected until the range
    type is fixed to a real class. This case is the regression cover
    once both Contract D AND Engine E's cleanup land.
    """
    pytest.fail("intentional placeholder — see skip reason")


@pytest.mark.skip(reason=_D_PHANTOM_SCAN)
def test_D_phantom_scan_returns_zero_after_valid_registrations():
    """After a full battery of valid registrations, the phantom-scan
    Cypher returns zero. Operational health gate — if it returns
    non-zero, Contract D is being bypassed (someone reintroduced MERGE,
    or a non-canonical write path is in use).
    """
    pytest.fail("intentional placeholder — see skip reason")


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
def test_axis2_placeholders_are_all_marked_skip():
    """Sanity check — every test function in this module starts with
    test_C_ or test_D_ and carries a skip marker. Prevents accidentally
    "going green" by silently removing a skip without implementing the
    contract.
    """
    import inspect
    import sys
    me = sys.modules[__name__]
    contract_tests = [
        (name, obj) for name, obj in inspect.getmembers(me)
        if name.startswith(("test_C_", "test_D_")) and callable(obj)
    ]
    assert len(contract_tests) > 0, "no Axis-2 placeholder tests found"
    for name, fn in contract_tests:
        marks = getattr(fn, "pytestmark", [])
        skips = [m for m in marks if m.name == "skip"]
        assert skips, (
            f"{name}: Axis-2 placeholder must carry an explicit "
            f"@pytest.mark.skip(reason=...) — a missing skip means "
            f"the test will silently pass (it just calls pytest.fail) "
            f"or silently fail without a documented reason. Add the "
            f"skip marker pointing at the production surface that "
            f"would lift it."
        )
