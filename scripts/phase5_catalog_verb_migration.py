"""Phase 5 — Catalog verb migration to idp:* subjects.

9 catalog verbs are currently typed against pseudo-classes
(mesh:CatalogAssetQuery, mesh:CatalogScopeQuery, mesh:DatasetAnalysisRequest).
Migrate them to type against the real idp:* subjects declared in idp_extension.ttl
(Phase 4 Layer 1). After this, the compat-walk from idp:Dataset (or via
subClassOf from idp:Table / idp:Dashboard) reaches every catalog verb directly —
no more Contract B false-passes via fallback semantic verb search.

Scope (the 9 catalog verbs):
  mesh:CatalogAssetQuery (7 verbs):
    - mesh:assessImpact
    - mesh:checkFreshness
    - mesh:describeAsset
    - mesh:filterByTag
    - mesh:findSchema
    - mesh:lookupOwnership
    - mesh:traceLineage
  mesh:CatalogScopeQuery (1 verb):
    - mesh:enumerateCatalog
  mesh:DatasetAnalysisRequest (1 verb):
    - mesh:analyzeDataset

OUT of scope (separate concerns):
  mesh:AgentTask (1 verb): mesh:analyzeWithCodeAgent — not a catalog verb;
    its proper subject is "generic agent task," not a data-engineering noun.
    Stays typed against mesh:AgentTask until its proper home is decided.

Phases:
  1. Ensure idp:Dataset exists as OntologyClass node in Neo4j (the canonical
     pipeline syncs to Weaviate + Jena, NOT Neo4j directly — Neo4j needs an
     explicit MERGE).
  2. For each of the 9 verbs: capture old edge props, delete old edge,
     recreate from idp:Dataset to same output.
  3. Drop the 3 pseudo-class OntologyClass nodes if they're orphaned.
  4. Update Weaviate Predicate collection input_uri to match.

Mirror of scripts/migrate_compact_to_full_iri.py + recreate_verb_edges.py
from the mro migration, adapted for the catalog scope.
"""
import os
import sys
from neo4j import GraphDatabase
import weaviate
from weaviate.classes.query import Filter

IDP_DATASET = "http://invincible-agent/idp#Dataset"
IDP_TABLE = "http://invincible-agent/idp#Table"
IDP_DASHBOARD = "http://invincible-agent/idp#Dashboard"
IDP_COLUMN = "http://invincible-agent/idp#Column"
IDP_PIPELINE = "http://invincible-agent/idp#Pipeline"
IDP_JOB = "http://invincible-agent/idp#Job"

# All 6 idp classes — MERGE all so they're available as compat-walk targets
# (Table/Dashboard subClassOf Dataset edges land at TTL ingest via the
# Jena→Neo4j step, but the nodes themselves need to exist for verb edges
# to anchor to them).
IDP_CLASSES = [
    (IDP_DATASET, "Dataset", None),
    (IDP_TABLE, "Table", IDP_DATASET),
    (IDP_DASHBOARD, "Dashboard", IDP_DATASET),
    (IDP_COLUMN, "Column", None),
    (IDP_PIPELINE, "Pipeline", None),
    (IDP_JOB, "Job", None),
]

# 9 verbs to migrate: (verb_iri, old_input_uri)
CATALOG_VERBS = [
    ("mesh:assessImpact", "mesh:CatalogAssetQuery"),
    ("mesh:checkFreshness", "mesh:CatalogAssetQuery"),
    ("mesh:describeAsset", "mesh:CatalogAssetQuery"),
    ("mesh:filterByTag", "mesh:CatalogAssetQuery"),
    ("mesh:findSchema", "mesh:CatalogAssetQuery"),
    ("mesh:lookupOwnership", "mesh:CatalogAssetQuery"),
    ("mesh:traceLineage", "mesh:CatalogAssetQuery"),
    ("mesh:enumerateCatalog", "mesh:CatalogScopeQuery"),
    ("mesh:analyzeDataset", "mesh:DatasetAnalysisRequest"),
]

# Pseudo-classes to drop after they're orphaned.
PSEUDO_DROP = [
    "mesh:CatalogAssetQuery",
    "mesh:CatalogScopeQuery",
    "mesh:DatasetAnalysisRequest",
]


def phase1_merge_idp_classes(driver):
    """Pre-create all 6 idp:* classes in Neo4j with subClassOf hierarchy."""
    print("=== Phase 1: MERGE 6 idp:* classes in Neo4j ===")
    with driver.session() as session:
        for uri, label, parent in IDP_CLASSES:
            session.run(
                "MERGE (c:OntologyClass {uri: $uri}) SET c.label = $label",
                uri=uri, label=label,
            )
            print(f"  MERGE {uri}")
            if parent:
                session.run(
                    """
                    MATCH (child:OntologyClass {uri: $child_uri})
                    MATCH (par:OntologyClass {uri: $parent_uri})
                    MERGE (child)-[:subClassOf]->(par)
                    """,
                    child_uri=uri, parent_uri=parent,
                )
                print(f"    subClassOf -> {parent}")


def phase2_retype_verbs(driver):
    """For each catalog verb: capture old edge, delete it, recreate from idp:Dataset."""
    print("\n=== Phase 2: Re-type 9 catalog verbs ===")
    with driver.session() as session:
        for verb_iri, old_input in CATALOG_VERBS:
            rec = session.run(
                """
                MATCH (s:OntologyClass {uri: $old})-[r]->(o:OntologyClass)
                WHERE r.iri = $verb
                RETURN properties(r) AS props, type(r) AS rel_type, o.uri AS output_uri
                LIMIT 1
                """,
                old=old_input, verb=verb_iri,
            ).single()
            if not rec:
                print(f"  [skip] {verb_iri}: no edge from {old_input} found")
                continue
            props = dict(rec["props"])
            output_uri = rec["output_uri"]
            rel_type = rec["rel_type"]
            # Update _input_uri prop
            props["_input_uri"] = IDP_DATASET

            # Delete old edge
            session.run(
                """
                MATCH (s:OntologyClass {uri: $old})-[r]->(o:OntologyClass {uri: $out})
                WHERE r.iri = $verb
                DELETE r
                """,
                old=old_input, out=output_uri, verb=verb_iri,
            )
            # Create new edge from idp:Dataset
            session.run(
                """
                MATCH (s:OntologyClass {uri: $new_input})
                MATCH (o:OntologyClass {uri: $out})
                CALL apoc.create.relationship(s, $rel_type, $props, o) YIELD rel
                RETURN type(rel)
                """,
                new_input=IDP_DATASET, out=output_uri, rel_type=rel_type, props=props,
            )
            print(f"  [retype] ({old_input})--[{verb_iri}]-->({output_uri})  =>  (idp:Dataset)--[{verb_iri}]-->({output_uri})")


def phase3_drop_orphan_pseudo_classes(driver):
    """Drop the 3 pseudo-classes if they have no remaining edges."""
    print("\n=== Phase 3: Drop orphan pseudo-class nodes ===")
    with driver.session() as session:
        for pseudo in PSEUDO_DROP:
            edges = session.run(
                "MATCH (c:OntologyClass {uri: $u}) OPTIONAL MATCH (c)-[r]-() WITH c, count(r) AS n RETURN n",
                u=pseudo,
            ).single()
            n = edges["n"] if edges else None
            if n is None:
                print(f"  [skip] {pseudo}: node not found")
                continue
            if n > 0:
                print(f"  [skip] {pseudo}: still has {n} edges (subClassOf bridges)")
                continue
            session.run("MATCH (c:OntologyClass {uri: $u}) DELETE c", u=pseudo)
            print(f"  [drop] {pseudo}")


def phase4_sync_weaviate_predicate(client):
    """Update Predicate collection input_uri for the 9 verbs to idp:Dataset."""
    print("\n=== Phase 4: Update Weaviate Predicate input_uri ===")
    col = client.collections.get("Predicate")
    for verb_iri, _ in CATALOG_VERBS:
        results = col.query.fetch_objects(
            filters=Filter.by_property("verb_iri").equal(verb_iri),
            limit=5,
        )
        for obj in results.objects:
            col.data.update(uuid=obj.uuid, properties={"input_uri": IDP_DATASET})
            print(f"  [update] {verb_iri}: input_uri -> {IDP_DATASET}")


def verify(driver):
    print("\n=== Verify: final verb topology ===")
    with driver.session() as session:
        for verb_iri, _ in CATALOG_VERBS:
            rec = session.run(
                """
                MATCH (s)-[r]->(o) WHERE r.iri = $verb
                RETURN s.uri AS input, o.uri AS output, r._input_uri AS recorded
                LIMIT 1
                """,
                verb=verb_iri,
            ).single()
            if rec:
                ok = "OK" if rec["input"] == IDP_DATASET and rec["recorded"] == IDP_DATASET else "BAD"
                print(f"  [{ok}] {verb_iri}: ({rec['input']}) -> ({rec['output']}) _input_uri={rec['recorded']}")
            else:
                print(f"  [MISSING] {verb_iri}: no edge found")


def main():
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    weav = weaviate.connect_to_custom(
        http_host=os.environ["WEAVIATE_HTTP_HOST"],
        http_port=8080, http_secure=False,
        grpc_host=os.environ["WEAVIATE_GRPC_HOST"],
        grpc_port=50051, grpc_secure=False,
    )
    try:
        phase1_merge_idp_classes(driver)
        phase2_retype_verbs(driver)
        phase3_drop_orphan_pseudo_classes(driver)
        phase4_sync_weaviate_predicate(weav)
        verify(driver)
    finally:
        driver.close()
        weav.close()


if __name__ == "__main__":
    main()
