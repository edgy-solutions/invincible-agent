"""B2 — ingest the SANDBOXRTX corpus, assert against the coverage table.

Per the architect's B2 recipe Step 3: predict before run, assert after.
Per the boundary rule: every assertion here exercises the synthetic
sandbox fixture; the negative boundary guard asserts the SANDBOXRTX
marker NEVER appears in deploy-path artifacts.

What this test covers:

  1. Classification correctness — every module's info code maps to the
     predicted mil:* content kind, per the coverage table. Pure
     deterministic check; no LLM.

  2. G1 stays GREEN through real ingest (positive control). The
     scaffold's G1 test (test_b2_format_ingest_guards.py) was proven
     red on TBox violations; this test proves it stays quiet on a
     legitimate instance-only ingest. A guard only ever seen firing
     red is untested on its green path — the abstention-needs-positive-
     control lesson applied to ingestion.

  3. G2 — every ingested DataModule instance has its INSTANCE_OF edge
     to a canonical kind class. No orphans.

  4. G3 — re-ingesting the same DMC produces an identical result
     (idempotency via MERGE-by-URI). Row 8 of the coverage table is
     a deliberate re-ingest of row 3 for this assertion.

  5. Composition cross-links — row 7's tool + spare references land
     as mil:requiresTool / mil:hasPart edges to mil:Tool / mil:Part
     instances. The Q5 composition plumbing is exercised as data.

  6. Negative boundary guard — the SANDBOXRTX MIC appears in the
     test substrate AND is ABSENT from every deploy-path artifact
     (setup/, helm/, prime-script manifests, every URL in
     CANONICAL_TTL_MANIFEST). The fabrication is designed to be
     found if it ever escapes the fixture.

  7. Pool-hold — the kind classes have new instances but stay OUT of
     the resolver candidate pool (no verbs typed). A maintenance
     query still routes via the existing retrieveKnowledge baseline.
     B0 §3's Wave-3-discipline bulk-declare rule.

Run requires:
  - Neo4j credentials (env or sandbox defaults).
  - doc_tools.parsers.s1000d_ingest importable (doc-tools on PYTHONPATH).
  - The SANDBOXRTX fixture committed at tests/fixtures/s1000d_sandbox_rtx/.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

try:
    from neo4j import GraphDatabase
except ImportError:
    pytest.skip("neo4j driver not installed", allow_module_level=True)


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j"))
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "changeme-neo4j-sandbox")


# ---------------------------------------------------------------------------
# Coverage table — the predictions, before any code runs.
# Match the architect's B2 coverage table 1-for-1.
# ---------------------------------------------------------------------------

MIL_NS = "http://edgy-solutions.com/ontology/mil#"
DESCRIPTIVE = MIL_NS + "DescriptiveDataModule"
PROCEDURE = MIL_NS + "ProcedureDataModule"
FAULT_ISO = MIL_NS + "FaultIsolationDataModule"
IPD = MIL_NS + "IllustratedPartsDataModule"

# (fixture_filename, expected_kind_iri, expected_dmc_substring, has_composition_refs)
COVERAGE_TABLE = [
    ("DMC-SANDBOXRTX-A-46-10-00-00A-040A-D_000-01_EN-US.XML", DESCRIPTIVE,
     "SANDBOXRTX-A-46-10-00-00A-040A-D", False),
    ("DMC-SANDBOXRTX-A-46-15-00-00A-042A-D_000-01_EN-US.XML", DESCRIPTIVE,
     "SANDBOXRTX-A-46-15-00-00A-042A-D", False),
    ("DMC-SANDBOXRTX-B-72-30-10-00A-520A-A_000-01_EN-US.XML", PROCEDURE,
     "SANDBOXRTX-B-72-30-10-00A-520A-A", False),
    ("DMC-SANDBOXRTX-C-95-20-15-00A-720A-A_000-01_EN-US.XML", PROCEDURE,
     "SANDBOXRTX-C-95-20-15-00A-720A-A", False),
    ("DMC-SANDBOXRTX-A-46-20-05-00A-420A-A_000-01_EN-US.XML", FAULT_ISO,
     "SANDBOXRTX-A-46-20-05-00A-420A-A", False),
    ("DMC-SANDBOXRTX-C-95-40-00-00A-941A-A_000-01_EN-US.XML", IPD,
     "SANDBOXRTX-C-95-40-00-00A-941A-A", False),
    ("DMC-SANDBOXRTX-A-46-30-00-00A-520A-A_000-01_EN-US.XML", PROCEDURE,
     "SANDBOXRTX-A-46-30-00-00A-520A-A", True),  # composition row
]

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "s1000d_sandbox_rtx"

SANDBOX_MIC = "SANDBOXRTX"


# ---------------------------------------------------------------------------
# Neo4j adapter — minimal wrapper that exposes `.execute_query` with `.records`
# matching the JenaResource/Neo4jResource shape doc-tools uses.
# ---------------------------------------------------------------------------

class Neo4jAdapter:
    def __init__(self, driver):
        self.driver = driver

    def execute_query(self, cypher, params=None):
        with self.driver.session() as session:
            result = session.run(cypher, params or {})
            records = [dict(r) for r in result]
        # match the .records attribute the s1000d_ingest module reads
        return type("Result", (), {"records": records})()


@pytest.fixture(scope="module")
def driver():
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        drv.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j unreachable at {NEO4J_URI}: {e}")
    yield drv
    drv.close()


@pytest.fixture(scope="module")
def neo4j_client(driver):
    return Neo4jAdapter(driver)


@pytest.fixture(scope="module")
def ingest_module():
    """Import doc_tools.parsers.s1000d_ingest; skip if not on PYTHONPATH."""
    try:
        from doc_tools.parsers import s1000d_ingest
        return s1000d_ingest
    except ImportError:
        pytest.skip(
            "doc_tools.parsers.s1000d_ingest not importable. This test runs in "
            "the doc-tools-aware environment (CI guard build, or local with "
            "doc-tools on PYTHONPATH)."
        )


# ---------------------------------------------------------------------------
# Pre-ingest snapshot — capture the OntologyClass node count so the G1
# positive-control check can compare AFTER ingest.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pre_ingest_state(driver):
    with driver.session() as session:
        rec = session.run(
            "MATCH (c:OntologyClass) RETURN count(c) AS n"
        ).single()
        ontology_class_count = rec["n"]
        rec = session.run(
            "MATCH ()-[r]->() WHERE r.iri IS NOT NULL AND r._tool_urn IS NOT NULL "
            "RETURN count(r) AS n"
        ).single()
        v02_saga_count = rec["n"]
    return {"ontology_class_count": ontology_class_count,
            "v02_saga_count": v02_saga_count}


# ---------------------------------------------------------------------------
# THE INGEST RUN — executes once for the whole test module, then the
# subsequent tests assert against the result.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ingest_results(neo4j_client, ingest_module, pre_ingest_state):
    """Ingest the 7 distinct corpus files, then re-ingest row 3 for G3.

    Returns: dict of fixture_filename → result dict.
    Side effect: instance nodes + edges in Neo4j.
    """
    if not FIXTURE_DIR.exists():
        pytest.skip(f"Fixture dir not present: {FIXTURE_DIR}")

    results = {}
    for fname, _exp_kind, _exp_dmc, _has_comp in COVERAGE_TABLE:
        xml = (FIXTURE_DIR / fname).read_bytes()
        results[fname] = ingest_module.process_s1000d_data_module(
            neo4j_client=neo4j_client,
            xml_bytes=xml,
            source_path=f"tests/fixtures/s1000d_sandbox_rtx/{fname}",
        )

    # Row 8 — re-ingest row 3 for G3 idempotency probe.
    row3 = COVERAGE_TABLE[2]
    xml = (FIXTURE_DIR / row3[0]).read_bytes()
    results["__row8_g3_reingest__"] = ingest_module.process_s1000d_data_module(
        neo4j_client=neo4j_client,
        xml_bytes=xml,
        source_path=f"tests/fixtures/s1000d_sandbox_rtx/{row3[0]}",
    )

    return results


# ---------------------------------------------------------------------------
# ASSERTIONS — the predict-then-verify gates.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fname,expected_kind,expected_dmc,_has_comp",
    COVERAGE_TABLE,
    ids=[c[2] for c in COVERAGE_TABLE],
)
def test_classification_matches_coverage_table(
    ingest_results, fname, expected_kind, expected_dmc, _has_comp,
):
    """The core B2 claim: every info code maps to the predicted mil:* kind."""
    r = ingest_results[fname]
    assert r["kind_iri"] == expected_kind, (
        f"Classification miss for {fname}: expected {expected_kind!r}, "
        f"got {r['kind_iri']!r}. mil_info_code_map needs to check info "
        f"code {expected_dmc.split('-')[-2]!r}."
    )
    assert expected_dmc in r["instance_uri"], (
        f"DMC URI miss for {fname}: expected to contain {expected_dmc!r}, "
        f"got {r['instance_uri']!r}."
    )


def test_g1_stays_green_through_instance_only_ingest(
    driver, ingest_results, pre_ingest_state,
):
    """G1 POSITIVE CONTROL: a legitimate instance-only ingest writes
    ZERO OntologyClass nodes.

    The scaffold's G1 test proved G1 fires red on TBox violations.
    This test proves it stays quiet on the green path — the
    abstention-needs-positive-control lesson applied to ingestion.

    Concretely: the count of :OntologyClass nodes must be the same
    after ingest as before. The ingest may have MATCHed kind classes
    (it must, to write INSTANCE_OF edges) but it must NEVER have
    MERGEd or CREATEd any.
    """
    with driver.session() as session:
        post_count = session.run(
            "MATCH (c:OntologyClass) RETURN count(c) AS n"
        ).single()["n"]
    assert post_count == pre_ingest_state["ontology_class_count"], (
        f"G1 violation: OntologyClass count changed during ingest. "
        f"Before: {pre_ingest_state['ontology_class_count']}, "
        f"after: {post_count}. The format-ingest path wrote to TBox — "
        f"check s1000d_ingest for any MERGE (:OntologyClass {{...}}) "
        f"call. The architectural rule (B0 §1) is that format ingest "
        f"writes ABox ONLY."
    )


def test_g1_stays_green_no_v02_saga_edges_added(
    driver, ingest_results, pre_ingest_state,
):
    """G1 corollary: no v0.2 saga (predicate-graph routing) edges written.

    The format-ingest path must NEVER touch the resolver candidate
    pool. The v0.2 saga edges (_tool_urn IS NOT NULL) are the routing
    layer's domain. Format ingest creating one would mean the parser
    decided to register a verb on the fly.
    """
    with driver.session() as session:
        post = session.run(
            "MATCH ()-[r]->() WHERE r.iri IS NOT NULL "
            "AND r._tool_urn IS NOT NULL RETURN count(r) AS n"
        ).single()["n"]
    assert post == pre_ingest_state["v02_saga_count"], (
        f"G1 violation: v0.2 saga edge count changed during ingest. "
        f"Before: {pre_ingest_state['v02_saga_count']}, after: {post}. "
        f"The format-ingest path wrote a predicate routing edge — that "
        f"is the gateway saga's domain only, never the parser's."
    )


@pytest.mark.parametrize(
    "fname,expected_kind,expected_dmc,_has_comp",
    COVERAGE_TABLE,
    ids=[c[2] for c in COVERAGE_TABLE],
)
def test_g2_every_instance_has_instance_of_edge(
    driver, ingest_results, fname, expected_kind, expected_dmc, _has_comp,
):
    """G2: every ingested instance must have INSTANCE_OF → canonical kind."""
    r = ingest_results[fname]
    with driver.session() as session:
        rec = session.run(
            """
            MATCH (dm:DataModule {uri: $uri})-[:INSTANCE_OF]->(kind:OntologyClass)
            RETURN kind.uri AS kind_uri
            """,
            {"uri": r["instance_uri"]},
        ).single()
    assert rec is not None, (
        f"G2 violation: {fname}'s instance ({r['instance_uri']!r}) "
        f"has NO INSTANCE_OF edge. Every ingested DM must carry one "
        f"(the fallback for missing info code is mil:DataModule root, "
        f"never an absent edge)."
    )
    assert rec["kind_uri"] == expected_kind


def test_g3_reingest_idempotent(driver, ingest_results):
    """G3: re-ingesting the same DMC (row 8 == row 3) produces the
    same result — no duplicate nodes, no edge proliferation."""
    row3 = COVERAGE_TABLE[2]
    expected_dmc = row3[2]
    with driver.session() as session:
        count = session.run(
            "MATCH (dm:DataModule {dmc: $dmc}) RETURN count(dm) AS n",
            {"dmc": expected_dmc},
        ).single()["n"]
    assert count == 1, (
        f"G3 violation: re-ingest of {expected_dmc!r} produced "
        f"{count} :DataModule nodes (expected exactly 1 via MERGE by URI). "
        f"The s1000d_ingest module's MERGE clause is broken — same DMC "
        f"must round-trip to the same identity."
    )

    # Edge multiplicity check: INSTANCE_OF must remain exactly 1 even
    # after re-ingest.
    edge_count = (
        driver.session()
        .run(
            "MATCH (dm:DataModule {dmc: $dmc})-[r:INSTANCE_OF]->() "
            "RETURN count(r) AS n",
            {"dmc": expected_dmc},
        )
        .single()["n"]
    )
    assert edge_count == 1, (
        f"G3 violation: re-ingest of {expected_dmc!r} produced "
        f"{edge_count} INSTANCE_OF edges (expected exactly 1). MERGE "
        f"on the relationship pattern, not CREATE."
    )


def test_composition_row_creates_tool_and_part_edges(
    driver, ingest_results,
):
    """Row 7 (LTAMDS PS remove) declares one tool + one spare. The
    ingest must materialize them as mil:Tool / mil:Part instances
    with mil:requiresTool / mil:hasPart edges from the DM."""
    row7 = COVERAGE_TABLE[6]
    fname = row7[0]
    r = ingest_results[fname]

    with driver.session() as session:
        tool_rec = session.run(
            """
            MATCH (dm:DataModule {uri: $uri})-[:REQUIRES_TOOL]->(t:Tool)
            -[:INSTANCE_OF]->(k:OntologyClass)
            RETURN t.partNumber AS pn, k.uri AS kind
            """,
            {"uri": r["instance_uri"]},
        ).single()
        spare_rec = session.run(
            """
            MATCH (dm:DataModule {uri: $uri})-[:HAS_PART]->(p:Part)
            -[:INSTANCE_OF]->(k:OntologyClass)
            RETURN p.partNumber AS pn, k.uri AS kind
            """,
            {"uri": r["instance_uri"]},
        ).single()

    assert tool_rec is not None, (
        f"Composition probe failed: row 7 (LTAMDS PS) declared a "
        f"supportEquipDescr in the XML but no REQUIRES_TOOL edge "
        f"materialized in Neo4j. Q5's composition plumbing is missing."
    )
    assert tool_rec["pn"] == "TW-001"
    assert tool_rec["kind"] == MIL_NS + "Tool"

    assert spare_rec is not None, (
        f"Composition probe failed: row 7 declared a spareDescr but "
        f"no HAS_PART edge materialized."
    )
    assert spare_rec["pn"] == "FUSE-5A"
    assert spare_rec["kind"] == MIL_NS + "Part"


# ---------------------------------------------------------------------------
# NEGATIVE BOUNDARY GUARD — the architect's load-bearing rule.
# ---------------------------------------------------------------------------

def test_sandboxrtx_appears_in_test_substrate(driver, ingest_results):
    """Positive half of the boundary: after ingest, SANDBOXRTX IS
    present in the test substrate. (If this fails, the ingest didn't
    fire and the negative-half result is vacuous.)"""
    with driver.session() as session:
        n = session.run(
            "MATCH (dm:DataModule) WHERE dm.modelIdentCode = $mic "
            "RETURN count(dm) AS n",
            {"mic": SANDBOX_MIC},
        ).single()["n"]
    assert n >= 7, (
        f"Positive half of negative-boundary guard failed: only {n} "
        f"SANDBOXRTX DMs found in Neo4j (expected at least 7). "
        f"Without the marker present here, the absence-from-deploy-path "
        f"half is meaningless."
    )


DEPLOY_PATH_DIRS = [
    "setup",
    "helm",
    "agent_fleet",
    "scripts",
    "src",
    "baml_shared",
    "Procfile",
    "pyproject.toml",
]
# Within those dirs, ignore non-relevant binaries + the fixture itself
DEPLOY_PATH_EXCLUDES = re.compile(
    r"(\.venv|\.git|node_modules|tests/fixtures/s1000d_sandbox_rtx|__pycache__|\.png|\.jpg|\.pyc|\.lock|uv\.lock|baml_client/types\.py)"
)


def test_sandboxrtx_marker_absent_from_deploy_path_artifacts():
    """The negative half. SANDBOXRTX must NOT appear anywhere a deploy
    consumes — setup/, helm/, prime-script manifests, agent_fleet/
    engine source, bootstrap fetch URLs.

    The fabrication is designed so leakage is catchable. If a single
    synthetic DMC slips into a deploy-path artifact, this test fires
    with the exact path it leaked into.
    """
    repo_root = Path(__file__).parent.parent.parent
    violations = []
    for entry in DEPLOY_PATH_DIRS:
        path = repo_root / entry
        if not path.exists():
            continue
        if path.is_file():
            files = [path]
        else:
            files = [
                p for p in path.rglob("*")
                if p.is_file() and not DEPLOY_PATH_EXCLUDES.search(str(p))
            ]
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if SANDBOX_MIC in text:
                violations.append(str(f.relative_to(repo_root)))

    assert not violations, (
        f"NEGATIVE BOUNDARY GUARD FAILED. The SANDBOXRTX marker leaked "
        f"into {len(violations)} deploy-path artifacts: {violations[:10]}. "
        f"The synthetic test corpus is appearing in code that ships to "
        f"the work cluster. This is the worst version of the problem — "
        f"test data wearing realistic-looking RTX identifiers in the "
        f"production substrate. Remove every reference to SANDBOXRTX "
        f"from the listed paths. The marker exists EXACTLY so this "
        f"guard catches it; do not weaken the test."
    )


# ---------------------------------------------------------------------------
# POOL-HOLD CHECK — Wave-3 bulk-declare rule under instance load.
# ---------------------------------------------------------------------------

def test_pool_hold_kind_classes_have_no_verbs_yet(driver, ingest_results):
    """B0 §3 / Wave-3 rule: kind classes are DECLARED in the TBox and
    HAVE INSTANCES now, but must NOT be in the resolver candidate pool
    (no verbs typed against them). B4 adds verbs on demand; until then
    the kinds stay pool-held.

    Tests that no v0.2 saga edge points at any mil:*DataModule
    content-kind class as its input_uri.
    """
    kind_iris = [DESCRIPTIVE, PROCEDURE, FAULT_ISO, IPD]
    with driver.session() as session:
        rec = session.run(
            """
            MATCH (s:OntologyClass)-[r]->()
            WHERE s.uri IN $kinds AND r._tool_urn IS NOT NULL
            RETURN s.uri AS subject, r.iri AS verb, count(*) AS n
            """,
            {"kinds": kind_iris},
        )
        leaks = [(r["subject"], r["verb"]) for r in rec]
    assert not leaks, (
        f"Pool-hold violation: mil:* content-kind classes have verb "
        f"edges (resolver-pool entries) before B4 ships: {leaks}. "
        f"Add the verb only when a real user question demands it; "
        f"see B0 §3 (Wave-3 discipline)."
    )
