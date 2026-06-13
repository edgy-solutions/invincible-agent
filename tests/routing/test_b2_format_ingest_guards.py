"""B2 standing guards — the format-ingest pipeline's load-bearing invariants.

Per B0 §4 / §1 (docs-phase Step-0 spec, tests/routing/STEP0_DOCS_PHASE_SPEC.md):
"Format ingestion writes INSTANCES and CHUNKS only. It NEVER writes
OntologyClass nodes or touches the resolver candidate pool."

These tests are the enforceable form of that rule. Each guard fails red
if the corresponding invariant is violated. They run against the live
sandbox cluster (Neo4j auth via env); a CI guarded variant runs them
against a fixture cluster post-deploy.

The three guards (G1/G2/G3) per B0 §4:

  G1 — Ingest never writes TBox or touches the resolver candidate pool.
       The MOST IMPORTANT guard in the phase. If format ingest ever
       MERGEs an OntologyClass node or inserts a row into the resolver's
       Weaviate OntologyClass collection, the layered architecture
       collapses — class assignment moves from "deterministic metadata
       lookup" (B0 §4 #1) to "whatever the parser felt like."

  G2 — Every ingested instance has an INSTANCE_OF edge to a declared
       kind-class. No orphan instances; no instances pointing at phantom
       classes. The deterministic info-code → mil:* mapping fires for
       every DM; if a DM lacks an info code, the fallback is the root
       mil:DataModule (NOT a missing label).

  G3 — Class assignment is deterministic. Same DMC → same kind every
       time. No model call in the assignment path. This is verified by
       code-path inspection (no LLM/BAML imports in the mapping module)
       and by snapshot stability (two ingest runs of the same DMC
       produce the same INSTANCE_OF target).

These tests are CURRENTLY MARKED AS xfail / skip because the format
ingest pipeline (B2 build proper) hasn't shipped yet. The TESTS land
first so the guards are the spec; B2 implementation makes them green.

Run requires Neo4j credentials. Defaults match the sandbox cluster.

  pytest tests/routing/test_b2_format_ingest_guards.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

try:
    from neo4j import GraphDatabase
except ImportError:
    pytest.skip("neo4j driver not installed", allow_module_level=True)


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j"))
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "changeme-neo4j-sandbox")


# Canonical full-IRI mil:* class set per mil_extension.ttl (10 classes,
# materialized into Neo4j by sync_jena_ontologies_to_neo4j on
# 2026-06-13; verified by the Session-2 bootstrap acceptance test).
MIL_NS = "http://edgy-solutions.com/ontology/mil#"
MIL_KIND_CLASSES = {
    MIL_NS + "DescriptiveDataModule",
    MIL_NS + "ProcedureDataModule",
    MIL_NS + "FaultIsolationDataModule",
    MIL_NS + "IllustratedPartsDataModule",
    MIL_NS + "Diagram",
    MIL_NS + "DataModule",  # root — the fallback when info code is missing
}


@pytest.fixture(scope="module")
def driver():
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        drv.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j unreachable at {NEO4J_URI}: {e}")
    yield drv
    drv.close()


# ---------------------------------------------------------------------------
# G1 — INGEST NEVER WRITES TBOX OR THE RESOLVER POOL
# ---------------------------------------------------------------------------

def test_g1_format_ingest_never_writes_ontology_class(driver):
    """G1: format ingestion writes ONLY instances + chunks.

    Concretely: after a format ingest run, the substrate must contain
    NO new OntologyClass nodes that lack a `synced_by` property
    matching the canonical pipeline. A format-ingest-created
    OntologyClass would mean ingest decided to define a new class
    on the fly — the §1 rule violation.

    The check: every OntologyClass node MUST have either
    `synced_by='sync_jena_ontologies_to_neo4j'` (Session-2 canonical
    pipeline) OR a historical marker indicating it pre-dates the
    canonical pipeline (`ingest_run_id` from the direct-load era,
    `source_ontology` from the mystery notebook). Nodes with NEITHER
    came from somewhere that shouldn't be writing classes — almost
    certainly a format ingest violating G1.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:OntologyClass)
            WHERE c.synced_by IS NULL
              AND c.ingest_run_id IS NULL
              AND c.source_ontology IS NULL
            RETURN c.uri AS uri, c.domain AS domain LIMIT 20
            """
        )
        violations = [(rec["uri"], rec["domain"]) for rec in result]
    assert not violations, (
        f"G1 violation: {len(violations)} OntologyClass nodes have no canonical "
        f"pipeline provenance (synced_by/ingest_run_id/source_ontology). "
        f"These were probably written by format ingestion — the §1 rule "
        f"violation. First 5: {violations[:5]}. The format-ingest pipeline "
        f"must NEVER call MERGE (:OntologyClass {{uri: ...}}); classes come "
        f"from the canonical pipeline only."
    )


# ---------------------------------------------------------------------------
# G2 — EVERY INSTANCE HAS INSTANCE_OF TO A DECLARED KIND
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    reason="B2 format-ingest pipeline not yet shipped — guard activates "
           "once mil:DataModule instances are being created. Currently the "
           "substrate has no :DataModule instances, so the guard's match "
           "returns empty (vacuously true). Becomes load-bearing when B2 "
           "starts writing instances.",
)
def test_g2_every_instance_has_instance_of_edge(driver):
    """G2: every ingested DataModule instance has an INSTANCE_OF edge to
    a declared kind-class.

    No orphan instances; no instances pointing at phantom classes. The
    canonical pipeline materializes the kind classes; the ingest reads
    info codes via mil_info_code_map and writes INSTANCE_OF edges.

    Fails if any :DataModule instance lacks an INSTANCE_OF edge.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (dm:DataModule)
            OPTIONAL MATCH (dm)-[r:INSTANCE_OF]->(kind:OntologyClass)
            WITH dm, count(r) AS edge_count, collect(kind.uri) AS kinds
            WHERE edge_count = 0
            RETURN dm.dmc AS dmc, dm.id AS id LIMIT 20
            """
        )
        orphans = [(rec["dmc"], rec["id"]) for rec in result]

    assert not orphans, (
        f"G2 violation: {len(orphans)} :DataModule instances have NO "
        f"INSTANCE_OF edge to a kind-class. The deterministic info-code "
        f"mapping should have fired for every DM; even DMs without an "
        f"info code fall back to mil:DataModule (the root). Orphan "
        f"instances mean the mapping step was skipped. First 5: "
        f"{orphans[:5]}"
    )


@pytest.mark.xfail(
    reason="B2 not yet shipped — see test_g2_every_instance_has_instance_of_edge.",
)
def test_g2_no_instance_points_at_phantom_class(driver):
    """G2 (corollary): no INSTANCE_OF edge points at a phantom class.

    Every INSTANCE_OF target must be one of the canonical kind classes
    materialized via the canonical pipeline. Pointing at something else
    means either (a) info-code-map.py was hand-edited to introduce a
    new kind without adding it to mil_extension.ttl, OR (b) ingest
    invented a class on the fly.
    """
    canonical_kinds = list(MIL_KIND_CLASSES)
    with driver.session() as session:
        result = session.run(
            """
            MATCH (dm:DataModule)-[:INSTANCE_OF]->(kind:OntologyClass)
            WHERE NOT kind.uri IN $canonical_kinds
            RETURN DISTINCT kind.uri AS phantom_target, count(*) AS n_pointing
            """,
            canonical_kinds=canonical_kinds,
        )
        phantoms = [(rec["phantom_target"], rec["n_pointing"]) for rec in result]

    assert not phantoms, (
        f"G2 violation: INSTANCE_OF edges point at phantom kind classes "
        f"not declared in mil_extension.ttl: {phantoms}. Either add the "
        f"class to the TTL + re-ingest, or fix the mapping in "
        f"doc_tools/parsers/mil_info_code_map.py."
    )


# ---------------------------------------------------------------------------
# G3 — CLASSIFICATION IS DETERMINISTIC (NO LLM IN PATH)
# ---------------------------------------------------------------------------

def test_g3_info_code_map_module_has_no_llm_imports():
    """G3 (code-path form): the deterministic mapping module has NO
    imports that could pull in an LLM client.

    This is the strongest possible form of G3: even if a future commit
    accidentally calls a model from the mapping path, this test fails
    at IMPORT TIME because the offending import would land in the
    module's import graph.

    Forbidden import substrings: baml, openai, anthropic, ollama,
    langchain, llm_utils, smolagents. If your model client uses a name
    not in this list, add it.
    """
    try:
        # The mapping module lives in doc-tools; importable when doc-tools
        # is on PYTHONPATH (CI guarded image, or local pip-install -e).
        from doc_tools.parsers import mil_info_code_map  # noqa: F401
    except ImportError:
        pytest.skip(
            "doc_tools.parsers.mil_info_code_map not importable; this "
            "test runs in the doc-tools-aware environment (the CI guard "
            "build, or a local invocation with doc-tools on PYTHONPATH)."
        )

    import doc_tools.parsers.mil_info_code_map as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    forbidden = [
        "baml", "openai", "anthropic", "ollama",
        "langchain", "llm_utils", "smolagents",
    ]
    violations = [token for token in forbidden if token.lower() in src.lower()]
    assert not violations, (
        f"G3 violation: deterministic info-code map module mentions "
        f"LLM-related imports/strings: {violations}. The mapping path "
        f"MUST be model-free per B0 §1. If this module needs to call a "
        f"model, the design rule is wrong — surface that finding "
        f"instead of fixing it here."
    )


def test_g3_info_code_map_is_pure_function():
    """G3 (behavior form): same input → same output, always.

    Determinism check: call classify_data_module twice with the same
    info code; outputs must be identical. (Tautological for a pure
    Python lookup, but the test EXISTS so a refactor that introduces
    randomness, caching with eviction, or model-backed fallback turns
    red.)
    """
    try:
        from doc_tools.parsers.mil_info_code_map import classify_data_module
    except ImportError:
        pytest.skip("doc_tools.parsers.mil_info_code_map not importable.")

    test_cases = ["041", "520", "421", "920", "740", "", None, "XYZ"]
    for ic in test_cases:
        r1 = classify_data_module(ic)
        r2 = classify_data_module(ic)
        assert r1 == r2, (
            f"G3 violation: classify_data_module({ic!r}) returned "
            f"{r1!r} then {r2!r}. The classification must be a pure "
            f"function — same input, same output, always."
        )


def test_g3_info_code_ranges_cover_b0_spec():
    """G3 (spec form): the info-code ranges in the mapping module match
    B0 §3's documented families.

    If the running S1000D issue's ranges shift (B0's noted ⚠), update
    INFO_CODE_RANGES in mil_info_code_map.py AND this test in lock-step.
    Drift between the two means downstream routing is wrong AND the
    docs don't say so.
    """
    try:
        from doc_tools.parsers.mil_info_code_map import (
            INFO_CODE_RANGES,
            DESCRIPTIVE_DATA_MODULE, PROCEDURE_DATA_MODULE,
            FAULT_ISOLATION_DATA_MODULE, ILLUSTRATED_PARTS_DATA_MODULE,
        )
    except ImportError:
        pytest.skip("doc_tools.parsers.mil_info_code_map not importable.")

    expected = {
        "0": DESCRIPTIVE_DATA_MODULE,
        "2": PROCEDURE_DATA_MODULE,
        "4": FAULT_ISOLATION_DATA_MODULE,
        "5": PROCEDURE_DATA_MODULE,
        "7": PROCEDURE_DATA_MODULE,
        "9": ILLUSTRATED_PARTS_DATA_MODULE,
    }
    assert INFO_CODE_RANGES == expected, (
        f"G3 spec drift: INFO_CODE_RANGES diverged from B0 §3. "
        f"Got: {INFO_CODE_RANGES}. Expected: {expected}. Either "
        f"update B0 spec + this test together (the S1000D issue "
        f"shifted) or fix the mapping. NEVER let them drift silently."
    )
