"""B3a — ingest the helmet IADS (MIL-STD-40051) demo, assert against the
coverage table.

Per the architect's 2026-06-13 40051-track assignment:

  > "Predict per WP: maintwp → ProcedureDataModule, tswp →
  > FaultIsolationDataModule, each wpno → canonical instance IRI,
  > xref/tool edges materialize. Then assert: classification correct;
  > G1 GREEN (zero TBox writes, positive control); G2 (every instance
  > INSTANCE_OF a mil:* kind); G3 (idempotent re-ingest); cross-link
  > edges present; pool-hold holds."

What this test covers (mirrors B2 SANDBOXRTX 1-for-1):

  1. Classification — every WP's root tag maps to the predicted mil:*
     kind via the DTD-derived WP_ROOT_TO_KIND map. Pure deterministic
     check, no LLM. Fallthrough WPs (toolidwp) hit mil:DataModule
     and increment FALLTHROUGH_COUNT (positive control on the
     "no silent absorption" rule).

  2. G1 stays GREEN through real ingest. OntologyClass count
     unchanged before/after.

  3. G2 — every WP gets exactly one INSTANCE_OF edge to a mil:*
     kind. Tool placeholder + cross-ref placeholder nodes also.

  4. G3 — re-ingesting the same wpno produces an identical result.

  5. Cross-link materialization — m0004 REQUIRES_TOOL s0002 +
     t0003 REFERENCES m0004 land as substrate edges.

  6. Negative-boundary guard — the helmet TM identifier "1-1680-tng"
     appears in the test substrate (every wpno tail) AND is absent
     from every deploy-path artifact (helm/, agent_fleet/, etc.).
     Same boundary architecture as B2's SANDBOXRTX guard; different
     marker for different fixture (DEMO-watermark public data, not
     SANDBOXRTX synthetic data).

  7. Pool-hold — kind classes have new instances but stay OUT of the
     resolver candidate pool. B0 §3 Wave-3 discipline.

Run requires:
  - Neo4j credentials (sandbox).
  - doc_tools.parsers.{mil_40051_classifier, mil_40051_ingest, iads_extract}
    importable (doc-tools on PYTHONPATH).
  - IADS_HELMET_PATH env var pointing at the helmet.iads file. The
    file is the IADS 4.0 Public Demo Dataset (TM 1-1680-TNG-13P,
    DEMO watermark, redistributable) but is too large for git. If
    the env var is unset and the default path doesn't exist, the
    test skips cleanly.
"""

from __future__ import annotations

import os
import re
import sys
import types
import importlib.util
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
# Derived from the dry-run output (2026-06-13). The architect's
# predict-before-probe discipline: bake these into the test SOURCE so a
# drift in classification fires loudly in CI.
# ---------------------------------------------------------------------------

MIL_NS = "http://edgy-solutions.com/ontology/mil#"
DESCRIPTIVE = MIL_NS + "DescriptiveDataModule"
PROCEDURE = MIL_NS + "ProcedureDataModule"
FAULT_ISO = MIL_NS + "FaultIsolationDataModule"
IPD = MIL_NS + "IllustratedPartsDataModule"
ROOT_DM = MIL_NS + "DataModule"

# (basename, expected_root_tag, expected_wpno_canonical, expected_kind_iri)
COVERAGE_TABLE = [
    ("G0001.xml",     "ginfowp",     "g0001-1-1680-tng", DESCRIPTIVE),
    ("M0004.xml",     "maintwp",     "m0004-1-1680-tng", PROCEDURE),
    ("M0008.xml",     "gen.maintwp", "m0008-1-1680-tng", PROCEDURE),
    ("O0002.xml",     "opusualwp",   "o0002-1-1680-tng", PROCEDURE),
    ("p0005.xml",     "plwp",        "p0005",            IPD),
    ("p0006.xml",     "plwp",        "p0006",            IPD),
    ("p0007.xml",     "plwp",        "p0007",            IPD),
    ("RPSTLCover.xml","introwp",     "rpstl-introwp",    DESCRIPTIVE),
    ("S0002.xml",     "toolidwp",    "s0002-1-1680-tng", ROOT_DM),  # FALLTHROUGH
    ("T0003.xml",     "tswp",        "t0003-1-1680-tng", FAULT_ISO),
    ("t0008.xml",     "tswp",        "t0008-1-1680-tng", FAULT_ISO),
]

# Expected cross-link edges (the composition probe)
EXPECTED_TOOL_EDGES = [
    ("m0004-1-1680-tng", "s0002-1-1680-tng", "SCREWDRIVER, CROSS-TIP"),
]
EXPECTED_XREF_EDGES = [
    ("t0003-1-1680-tng", "m0004-1-1680-tng"),
]

EXPECTED_FALLTHROUGH = {"toolidwp": 1}

# The DEMO marker — the helmet TM identifier. Appears in every wpno
# in the test substrate; must be absent from every deploy-path artifact.
HELMET_DEMO_MARKER = "1-1680-tng"


# ---------------------------------------------------------------------------
# Helmet IADS location — env-var with documented default.
# ---------------------------------------------------------------------------

_DEFAULT_HELMET = Path(os.path.expanduser("~/Downloads/helmet.iads"))
_HELMET_PATH = Path(os.getenv("IADS_HELMET_PATH", str(_DEFAULT_HELMET)))


# ---------------------------------------------------------------------------
# Neo4j adapter (same shape B2 uses).
# ---------------------------------------------------------------------------

class Neo4jAdapter:
    def __init__(self, driver):
        self.driver = driver

    def execute_query(self, cypher, params=None):
        with self.driver.session() as session:
            result = session.run(cypher, params or {})
            records = [dict(r) for r in result]
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


# ---------------------------------------------------------------------------
# Load doc_tools.parsers.* without going through the package __init__.
# Same sidestep B2 uses.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mods():
    doc_tools_root = Path(os.getenv(
        "DOC_TOOLS_REPO",
        Path(__file__).parent.parent.parent.parent / "doc-tools",
    ))
    parsers_dir = doc_tools_root / "doc_tools" / "parsers"
    if not parsers_dir.exists():
        pytest.skip(
            f"doc-tools parsers dir not found at {parsers_dir}. Set "
            f"DOC_TOOLS_REPO=/path/to/doc-tools to point at the right place."
        )

    pkg_root = types.ModuleType("doc_tools")
    pkg_root.__path__ = [str(doc_tools_root / "doc_tools")]
    pkg_parsers = types.ModuleType("doc_tools.parsers")
    pkg_parsers.__path__ = [str(parsers_dir)]
    sys.modules.setdefault("doc_tools", pkg_root)
    sys.modules.setdefault("doc_tools.parsers", pkg_parsers)

    def _load(modname, fname):
        spec = importlib.util.spec_from_file_location(modname, parsers_dir / fname)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        return mod

    _load("doc_tools.parsers.mil_info_code_map", "mil_info_code_map.py")
    _load("doc_tools.parsers.dmc_canonicalizer", "dmc_canonicalizer.py")
    classifier = _load("doc_tools.parsers.mil_40051_classifier", "mil_40051_classifier.py")
    ingest = _load("doc_tools.parsers.mil_40051_ingest", "mil_40051_ingest.py")
    extract = _load("doc_tools.parsers.iads_extract", "iads_extract.py")
    return {"classifier": classifier, "ingest": ingest, "extract": extract}


# ---------------------------------------------------------------------------
# Pre-ingest snapshot — for G1 positive control.
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
# THE INGEST RUN — executes once for the whole module, then assertions
# inspect the substrate.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ingest_results(neo4j_client, mods, pre_ingest_state):
    """Walk every XML entry in helmet.iads; ingest each WP via the
    format-general reader. Returns (results_by_basename, summary)."""
    if not _HELMET_PATH.exists():
        pytest.skip(
            f"helmet.iads not present at {_HELMET_PATH}. Set "
            f"IADS_HELMET_PATH=/path/to/helmet.iads to point at the IADS "
            f"4.0 Demo Dataset (TM 1-1680-TNG-13P; public, redistributable)."
        )

    classifier = mods["classifier"]
    ingest = mods["ingest"]
    extract = mods["extract"]

    classifier.reset_fallthrough_count()

    results: dict[str, dict] = {}
    skipped_non_wp = 0
    for relpath, body in extract.iter_iads_xml_entries(_HELMET_PATH):
        basename = relpath.split("\\")[-1]
        r = ingest.process_40051_work_package(
            neo4j_client=neo4j_client,
            xml_bytes=body,
            source_path=f"helmet.iads/{relpath}",
        )
        if r is None:
            skipped_non_wp += 1
            continue
        results[basename] = r

    # G3 — re-ingest one WP (M0004) for idempotency check.
    for relpath, body in extract.iter_iads_xml_entries(_HELMET_PATH):
        if relpath.split("\\")[-1] == "M0004.xml":
            results["__g3_reingest_m0004__"] = ingest.process_40051_work_package(
                neo4j_client=neo4j_client,
                xml_bytes=body,
                source_path=f"helmet.iads/{relpath}",
            )
            break

    return {
        "by_basename": results,
        "skipped_non_wp": skipped_non_wp,
        "fallthrough_count": dict(classifier.FALLTHROUGH_COUNT),
    }


# ---------------------------------------------------------------------------
# ASSERTIONS — the predict-then-verify gates.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "basename,exp_root,exp_wpno,exp_kind",
    COVERAGE_TABLE,
    ids=[c[2] for c in COVERAGE_TABLE],
)
def test_classification_matches_coverage_table(
    ingest_results, basename, exp_root, exp_wpno, exp_kind,
):
    """The core B3a claim: every WP root maps to the predicted mil:* kind."""
    results = ingest_results["by_basename"]
    assert basename in results, (
        f"Coverage-table row {basename!r} missing from ingest results. "
        f"Either the .iads doesn't contain this file, or read_40051_wp "
        f"returned None for it (treated as non-WP front-matter — which "
        f"would be a classifier bug)."
    )
    r = results[basename]
    assert r["root_tag"] == exp_root, (
        f"Root-tag miss for {basename}: predicted {exp_root!r}, got "
        f"{r['root_tag']!r}. The XML's root element changed?"
    )
    assert r["wpno"] == exp_wpno, (
        f"wpno-canonicalization miss for {basename}: predicted "
        f"{exp_wpno!r}, got {r['wpno']!r}. canonicalize_wpno's output "
        f"changed shape — same-canonicalizer-both-sides rule means a "
        f"phone-book lookup would also miss now."
    )
    assert r["kind_iri"] == exp_kind, (
        f"Classification miss for {basename}: predicted {exp_kind!r}, "
        f"got {r['kind_iri']!r}. WP_ROOT_TO_KIND[{exp_root!r}] is the "
        f"line to inspect."
    )


def test_g1_stays_green_through_instance_only_ingest(
    driver, ingest_results, pre_ingest_state,
):
    """G1 POSITIVE CONTROL: a legitimate 40051 instance-only ingest writes
    ZERO OntologyClass nodes.

    Same shape as B2's G1 positive control. Proves the 40051 ingest
    obeys the ABox-only contract: it MATCHes mil:* kind classes,
    never MERGEs them.
    """
    with driver.session() as session:
        post_count = session.run(
            "MATCH (c:OntologyClass) RETURN count(c) AS n"
        ).single()["n"]
    assert post_count == pre_ingest_state["ontology_class_count"], (
        f"G1 violation: OntologyClass count changed during 40051 ingest. "
        f"Before: {pre_ingest_state['ontology_class_count']}, "
        f"after: {post_count}. The format-ingest path wrote to TBox. "
        f"Check mil_40051_ingest for any MERGE (:OntologyClass {{...}})."
    )


def test_g1_stays_green_no_v02_saga_edges_added(
    driver, ingest_results, pre_ingest_state,
):
    """G1 corollary: no v0.2 saga (predicate-graph routing) edges written
    during 40051 ingest. The format-ingest path must never register a verb."""
    with driver.session() as session:
        post = session.run(
            "MATCH ()-[r]->() WHERE r.iri IS NOT NULL "
            "AND r._tool_urn IS NOT NULL RETURN count(r) AS n"
        ).single()["n"]
    assert post == pre_ingest_state["v02_saga_count"], (
        f"G1 violation: v0.2 saga edge count changed during 40051 ingest. "
        f"Before: {pre_ingest_state['v02_saga_count']}, after: {post}."
    )


@pytest.mark.parametrize(
    "basename,_exp_root,_exp_wpno,exp_kind",
    COVERAGE_TABLE,
    ids=[c[2] for c in COVERAGE_TABLE],
)
def test_g2_every_instance_has_instance_of_edge(
    driver, ingest_results, basename, _exp_root, _exp_wpno, exp_kind,
):
    """G2: every ingested WP instance must have INSTANCE_OF → kind."""
    results = ingest_results["by_basename"]
    r = results[basename]
    with driver.session() as session:
        rec = session.run(
            """
            MATCH (wp:DataModule {uri: $uri})-[:INSTANCE_OF]->(kind:OntologyClass)
            RETURN kind.uri AS kind_uri
            """,
            {"uri": r["instance_uri"]},
        ).single()
    assert rec is not None, (
        f"G2 violation: {basename}'s instance ({r['instance_uri']!r}) "
        f"has NO INSTANCE_OF edge."
    )
    assert rec["kind_uri"] == exp_kind


def test_g3_reingest_idempotent(driver, ingest_results):
    """G3: re-ingesting M0004 produces the same substrate — exactly 1
    :DataModule node, exactly 1 INSTANCE_OF edge."""
    canonical = "m0004-1-1680-tng"
    with driver.session() as session:
        count = session.run(
            "MATCH (dm:DataModule {wpno: $w}) RETURN count(dm) AS n",
            {"w": canonical},
        ).single()["n"]
    assert count == 1, (
        f"G3 violation: re-ingest of {canonical!r} produced {count} "
        f":DataModule nodes (expected exactly 1 via MERGE by URI)."
    )
    with driver.session() as session:
        edge_count = session.run(
            "MATCH (dm:DataModule {wpno: $w})-[r:INSTANCE_OF]->() "
            "RETURN count(r) AS n",
            {"w": canonical},
        ).single()["n"]
    assert edge_count == 1, (
        f"G3 violation: re-ingest produced {edge_count} INSTANCE_OF edges "
        f"(expected exactly 1). MERGE on the relationship pattern, not CREATE."
    )


@pytest.mark.parametrize(
    "src_wpno,target_wpno,_tool_name",
    EXPECTED_TOOL_EDGES,
    ids=[f"{a}->{b}" for a, b, _ in EXPECTED_TOOL_EDGES],
)
def test_tool_edges_materialized(driver, ingest_results, src_wpno, target_wpno, _tool_name):
    """Composition probe (REQUIRES_TOOL): m0004's tool-setup-item lands as
    an edge to the s0002 tool WP."""
    with driver.session() as session:
        rec = session.run(
            """
            MATCH (src:DataModule {wpno: $src})-[:REQUIRES_TOOL]->(t:DataModule {wpno: $tgt})
            RETURN t.title AS title
            """,
            {"src": src_wpno, "tgt": target_wpno},
        ).single()
    assert rec is not None, (
        f"Composition probe failed: REQUIRES_TOOL edge "
        f"{src_wpno} → {target_wpno} did not materialize. "
        f"read_40051_wp's tool extraction or merge_40051_wp_instance's "
        f"REQUIRES_TOOL MERGE is broken."
    )


@pytest.mark.parametrize(
    "src_wpno,target_wpno",
    EXPECTED_XREF_EDGES,
    ids=[f"{a}->{b}" for a, b in EXPECTED_XREF_EDGES],
)
def test_xref_edges_materialized(driver, ingest_results, src_wpno, target_wpno):
    """Composition probe (REFERENCES): t0003's <xref wpid="m0004-..."> lands."""
    with driver.session() as session:
        rec = session.run(
            """
            MATCH (src:DataModule {wpno: $src})-[:REFERENCES]->(tgt:DataModule {wpno: $tgt})
            RETURN tgt.wpno AS w
            """,
            {"src": src_wpno, "tgt": target_wpno},
        ).single()
    assert rec is not None, (
        f"REFERENCES edge {src_wpno} → {target_wpno} did not materialize. "
        f"Check read_40051_wp's xref extraction."
    )


def test_fallthrough_counter_increments_on_morning_decision_cluster(ingest_results):
    """Positive control on the 'no silent absorption' rule: the toolidwp
    fallthrough hit must be visible in FALLTHROUGH_COUNT after a real
    helmet ingest. If this drops to {} the morning-decision visibility
    is broken."""
    assert ingest_results["fallthrough_count"] == EXPECTED_FALLTHROUGH, (
        f"FALLTHROUGH_COUNT drift: predicted {EXPECTED_FALLTHROUGH!r}, "
        f"got {ingest_results['fallthrough_count']!r}. Either the helmet "
        f"contains different WP types than expected, or the classifier "
        f"stopped logging fallthroughs (silent-absorption regression)."
    )


# ---------------------------------------------------------------------------
# NEGATIVE BOUNDARY GUARD — the architect's load-bearing rule for the
# helmet demo. The DEMO marker (helmet TM number, "1-1680-tng") must
# appear in the test substrate but NOT in any deploy-path artifact.
# ---------------------------------------------------------------------------

def test_helmet_demo_marker_appears_in_test_substrate(driver, ingest_results):
    """Positive half: after ingest, the helmet TM identifier IS present.
    If absent, the negative-half result is vacuous."""
    with driver.session() as session:
        n = session.run(
            "MATCH (wp:DataModule) WHERE wp.wpno CONTAINS $m "
            "RETURN count(wp) AS n",
            {"m": HELMET_DEMO_MARKER},
        ).single()["n"]
    assert n >= 7, (
        f"Positive half of helmet-demo boundary guard failed: only {n} "
        f"WPs with marker {HELMET_DEMO_MARKER!r} in Neo4j (expected >=7). "
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
DEPLOY_PATH_EXCLUDES = re.compile(
    r"(\.venv|\.git|node_modules|tests/fixtures/iads_40051_demo|__pycache__|\.png|\.jpg|\.pyc|\.lock|uv\.lock|baml_client/types\.py)"
)


def test_helmet_demo_marker_absent_from_deploy_path_artifacts():
    """The negative half. The helmet TM identifier '1-1680-tng' must not
    appear anywhere a deploy consumes. The DEMO-watermark fixture is
    designed so leakage is catchable — same architecture as SANDBOXRTX
    for S1000D, different marker for the public-data fixture."""
    repo_root = Path(__file__).parent.parent.parent
    # The marker is case-insensitive for grep purposes; we lowercased
    # the wpno during canonicalization but the literal TM identifier
    # in deploy paths could be in any case.
    markers = [HELMET_DEMO_MARKER, HELMET_DEMO_MARKER.upper()]
    violations = []
    for entry in DEPLOY_PATH_DIRS:
        path = repo_root / entry
        if not path.exists():
            continue
        files = [path] if path.is_file() else [
            p for p in path.rglob("*")
            if p.is_file() and not DEPLOY_PATH_EXCLUDES.search(str(p))
        ]
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if any(m in text for m in markers):
                violations.append(str(f.relative_to(repo_root)))

    assert not violations, (
        f"HELMET-DEMO BOUNDARY GUARD FAILED. The marker {HELMET_DEMO_MARKER!r} "
        f"leaked into {len(violations)} deploy-path artifacts: {violations[:10]}. "
        f"The helmet TM is real-shape public data — its identifier appearing "
        f"in deploy paths means the demo fixture is being treated as production "
        f"input. Remove the leakage; do not weaken the test."
    )


# ---------------------------------------------------------------------------
# POOL-HOLD CHECK — Wave-3 bulk-declare rule under 40051 instance load.
# ---------------------------------------------------------------------------

def test_pool_hold_kind_classes_have_no_verbs_yet(driver, ingest_results):
    """Kind classes now have 40051 instances but must NOT be in the
    resolver candidate pool (no verbs typed against them)."""
    kind_iris = [DESCRIPTIVE, PROCEDURE, FAULT_ISO, IPD, ROOT_DM]
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
        f"Pool-hold violation: mil:* content-kind classes have verb edges "
        f"(resolver-pool entries) before B4 ships: {leaks}. Add the verb "
        f"only when a real user question demands it; see B0 §3 (Wave-3 "
        f"discipline)."
    )
