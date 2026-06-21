"""Legacy-namespace residue guard — class-fix for the pre-canonical direct-load era.

## The class this guards against

Before the canonical ontology pipeline (doc-tools'
`sync_jena_ontologies_to_neo4j` asset) became the sole writer of
`:OntologyClass` nodes (per ADR-0006 §Addendum source-authority rule), a
pre-canonical direct-load mechanism wrote ontology classes under a
placeholder `http://example.com/...` namespace with no provenance
(`synced_by=None`, `synced_from=None`). Those nodes survived multiple
re-deploys because nothing removed them.

They are NOT inert. They live in the **same routing pools** the canonical
classes do — Neo4j (`:OntologyClass`) and Weaviate (`OntologyClass`
collection) — so they compete as resolution candidates against the
canonical classes the system actually stamps instances with. The
ADR-0021 Phase 1 verification probe (2026-06-20) caught this concretely:

  query: "What are the assembly steps for the M67 grenade?"
  before cleanup: resolved to http://example.com/manufacturing#MunitionsAssemblyStep @ 0.85
  after cleanup:  resolved to http://edgy-solutions.com/ontology/mfg#WorkInstruction @ 0.98

Both are at `domain=MANUFACTURING`. The residue had a BM25-friendly label
("Munitions Assembly Step") and won lexically against the canonical
`WorkInstruction` — but the instances stamped by the manufacturing plugin
carry `INSTANCE_OF mfg:WorkInstruction`. So the verb couldn't actually
reach its instances through the resolved class — the conjunctive-read
failure made concrete.

## What's residue: the two-store discipline

Verb routing is two-store: **Neo4j** holds the predicate-graph edge
(used by `/find_compatible_verbs`), **Weaviate** holds the Predicate
collection (used by `/classify_predicate`'s LLM prompt context). The
Phase 1 cleanup found that residue at EITHER store with input_uri
under the placeholder namespace is the same pool-bleed condition,
discovered only after the Neo4j-only cleanup left the LLM still
seeing the legacy `MunitionsAssemblyStep` in its Predicate-collection
prompt and refusing the verb on "substrate mismatch" grounds. The
guard now spans both stores.

## The 9 OntologyClass nodes cleaned 2026-06-20

  http://example.com/manufacturing#Class_1_1
  http://example.com/manufacturing#Class_1_3
  http://example.com/manufacturing#ComplianceRule
  http://example.com/manufacturing#ExplosiveMaterial
  http://example.com/manufacturing#ExplosivesSafetyHazard
  http://example.com/manufacturing#MunitionsAssemblyStep
  http://example.com/manufacturing#StandardIndustrialProcess
  http://example.com/isa95#MaterialClass
  http://example.com/isa95#ProcessSegment

Plus 1 Weaviate Predicate row whose `input_uri` referenced
`MunitionsAssemblyStep` — replaced with a canonical row pointing at
`mfg:WorkInstruction`. Same writer-hunt rule: the verb registration
had to be migrated in BOTH stores, not just Neo4j.

## What this guard enforces

Any `:OntologyClass` whose `uri` starts with `http://example.com/` AND
whose `synced_by` is `NULL` is **residue** by definition (the canonical
pipeline never writes either condition). The invariant is **zero such
nodes at steady state**.

A non-zero count means either:
  - a regression of the pre-canonical writer reappeared, OR
  - someone wrote a class with the placeholder namespace through a new
    code path (the right fix is to use a real namespace; the placeholder
    is reserved for documentation examples ONLY and must never reach
    substrate).

The check runs against the same Neo4j the rest of `test_substrate_invariants.py`
hits. Defaults are the sandbox values; CI sets via env.

  pytest tests/routing/test_no_legacy_residue.py
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


@pytest.fixture(scope="module")
def neo4j_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        driver.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j not reachable at {NEO4J_URI}: {e}")
    yield driver
    driver.close()


def test_no_placeholder_namespace_residue(neo4j_driver):
    """No :OntologyClass at http://example.com/* without canonical provenance.

    The placeholder namespace is reserved for documentation examples.
    Any class node carrying it AND having no `synced_by` is residue from
    a retired pre-canonical writer (see module docstring). Steady state
    is zero such nodes.
    """
    with neo4j_driver.session() as s:
        rows = list(s.run(
            """
            MATCH (c:OntologyClass)
            WHERE c.uri STARTS WITH 'http://example.com/'
              AND c.synced_by IS NULL
            RETURN c.uri AS uri, c.domain AS domain
            ORDER BY c.uri
            """
        ))
    residue = [(r["uri"], r["domain"]) for r in rows]
    assert residue == [], (
        f"Found {len(residue)} legacy-namespace residue OntologyClass nodes "
        f"(no canonical provenance). Class regressed — investigate which "
        f"writer is producing http://example.com/* URIs without "
        f"synced_by/synced_from, and clean the residue once the writer is "
        f"fixed:\n  " + "\n  ".join(f"{u!r} (domain={d!r})" for u, d in residue)
    )


# Sibling guard — Weaviate Predicate collection. Verb routing is
# two-store: Neo4j carries the compat-walk edge, Weaviate carries the
# LLM's prompt context for /classify_predicate. A canonical edge in
# Neo4j paired with a residue Predicate row in Weaviate makes the LLM
# refuse the verb (substrate mismatch on input_uri it reads from
# Weaviate). This guard catches that condition as a class.
#
# Two failure modes are equivalent for purposes of this check:
#   (a) Predicate.input_uri starts with http://example.com/ (legacy ns)
#   (b) Predicate.input_uri references a URI that exists in Weaviate
#       Predicate but has NO corresponding :OntologyClass in Neo4j
#       (dangling reference after class cleanup).
# This first version enforces (a) only — the structural placeholder-ns
# check that mirrors the Neo4j guard. (b) is a richer check across
# stores and is a separate test to add once the two-store consistency
# invariants are spec'd.

WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8080")


def _weaviate_count(input_uri_filter_text: str) -> int:
    """Run an Aggregate count over Predicate.input_uri with a Like filter."""
    try:
        import requests
    except ImportError:
        pytest.skip("requests not installed")
    q = (
        '{ Aggregate { Predicate(where: {operator: Like, '
        f'path: ["input_uri"], valueText: "{input_uri_filter_text}"}}) '
        '{ meta { count } } } }'
    )
    try:
        r = requests.post(f"{WEAVIATE_URL}/v1/graphql",
                          json={"query": q}, timeout=10)
    except Exception as e:
        pytest.skip(f"Weaviate not reachable at {WEAVIATE_URL}: {e}")
    body = r.json()
    return body["data"]["Aggregate"]["Predicate"][0]["meta"]["count"]


def _weaviate_residue_input_uris() -> list[str]:
    """Return the actual residue Predicate input_uri strings (for messaging)."""
    import requests
    q = (
        '{ Get { Predicate(where: {operator: Like, '
        'path: ["input_uri"], valueText: "http://example.com*"}, '
        'limit: 100) { input_uri verb_iri } } }'
    )
    r = requests.post(f"{WEAVIATE_URL}/v1/graphql",
                      json={"query": q}, timeout=10)
    rows = r.json().get("data", {}).get("Get", {}).get("Predicate", []) or []
    return [(row["input_uri"], row.get("verb_iri")) for row in rows]


def test_no_placeholder_namespace_predicate_residue():
    """No Predicate row at http://example.com/* input_uri.

    Sibling of test_no_placeholder_namespace_residue (which guards Neo4j
    OntologyClass). The verb routing is two-store and a Predicate row at
    a placeholder-ns input_uri produces the same pool-bleed failure mode
    seen during Phase 1 cleanup (2026-06-20): canonical compat-walk in
    Neo4j paired with stale Weaviate Predicate context made the LLM
    refuse the verb on substrate-mismatch grounds.
    """
    count = _weaviate_count("http://example.com*")
    if count > 0:
        residue = _weaviate_residue_input_uris()
        details = "\n  ".join(f"input_uri={u!r} verb_iri={v!r}" for u, v in residue)
        raise AssertionError(
            f"Found {count} Predicate row(s) at placeholder-namespace "
            f"input_uri. Pool-bleed risk: classify_predicate's LLM reads "
            f"Weaviate Predicate as prompt context, so a placeholder-ns "
            f"input_uri there leads to substrate-mismatch refusals even "
            f"when Neo4j's compat-walk returns canonical edges.\n  "
            + details
        )
