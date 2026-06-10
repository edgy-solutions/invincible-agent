"""Minimum-viable migration: compact URI -> full IRI for the 4 nodes serving
rotor + manuals queries, plus the 2 verb edges that connect them.

Scope (tonight):
  mro:WorkInstruction              -> https://spec.../MaintenanceReferenceOntology/WorkInstruction
  mro:TechnicalManual              -> https://spec.../MaintenanceReferenceOntology/TechnicalManual
  mesh:GraphExpertResponse         -> http://invincible-agent/mesh#GraphExpertResponse
  mesh:KnowledgeRetrievalResponse  -> http://invincible-agent/mesh#KnowledgeRetrievalResponse

  Verb mesh:queryKnowledgeGraph: re-anchor to full-IRI input + output, update _input_uri/_output_uri props
  Verb mesh:retrieveKnowledge:   same

Out of scope tonight (deferred to morning-driven design):
  mro:Procedure / Symptom / Equipment / Diagram / ProcedureStep
  mesh:CatalogAssetQuery / CatalogScopeQuery / DatasetAnalysisRequest / AgentTask / etc.
  data:Dashboard / Dataset / prov:Entity / mesh:Thing

Approach:
  Phase 1 (Neo4j): MERGE full-IRI nodes, copy props from compact, redirect both
                   in/out edges, delete compact node. One atomic transaction
                   per target.
  Phase 2 (Weaviate): delete compact OntologyClass entries (next canonical
                   re-ingest will produce the matching full-IRI entries).
  Phase 3 (Weaviate Predicate): update input_uri/output_uri on the 2 verb
                   records to full IRI.

Reversibility: each phase is a script; failures stop and Phase 1 transactions
roll back. Run in-cluster via doc-tools pod for credentials.
"""
import os
import sys
import weaviate
from weaviate.classes.query import Filter
from weaviate.util import generate_uuid5
from neo4j import GraphDatabase

# Compact -> full IRI mapping (only the 4 in scope tonight).
URI_MAP = {
    "mro:WorkInstruction": "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/WorkInstruction",
    "mro:TechnicalManual": "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/TechnicalManual",
    "mesh:GraphExpertResponse": "http://invincible-agent/mesh#GraphExpertResponse",
    "mesh:KnowledgeRetrievalResponse": "http://invincible-agent/mesh#KnowledgeRetrievalResponse",
}

# Verbs whose _input_uri / _output_uri props reference URIs in URI_MAP.
VERB_URIS = ["mesh:queryKnowledgeGraph", "mesh:retrieveKnowledge"]


def phase1_neo4j_migrate():
    """For each compact-URI node, MERGE the full-IRI equivalent, redirect all
    edges to it (preserving rel type + props), delete the compact node.
    """
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    try:
        with driver.session() as session:
            for compact, full in URI_MAP.items():
                # Pre-check: compact exists, full doesn't (or only is the same node).
                pre = session.run(
                    """
                    OPTIONAL MATCH (c:OntologyClass {uri: $compact})
                    OPTIONAL MATCH (f:OntologyClass {uri: $full})
                    RETURN c IS NOT NULL AS compact_exists,
                           f IS NOT NULL AS full_exists
                    """,
                    compact=compact, full=full,
                ).single()
                if not pre["compact_exists"]:
                    print(f"[skip] {compact}: not in Neo4j; nothing to migrate")
                    continue
                if pre["full_exists"]:
                    print(f"[abort] {full}: already exists separately from {compact}; manual reconciliation needed")
                    return False

                # 1. Capture all incoming and outgoing edges from the compact node.
                in_edges = list(session.run(
                    """
                    MATCH (other)-[r]->(c:OntologyClass {uri: $compact})
                    RETURN type(r) AS rel_type, properties(r) AS props,
                           id(other) AS other_id, other.uri AS other_uri
                    """,
                    compact=compact,
                ))
                out_edges = list(session.run(
                    """
                    MATCH (c:OntologyClass {uri: $compact})-[r]->(other)
                    RETURN type(r) AS rel_type, properties(r) AS props,
                           id(other) AS other_id, other.uri AS other_uri
                    """,
                    compact=compact,
                ))
                print(f"[plan] {compact} -> {full}: {len(in_edges)} in_edges, {len(out_edges)} out_edges")

                # 2. Get the compact node's properties (label, definition, domain).
                node_props = session.run(
                    "MATCH (c:OntologyClass {uri: $compact}) RETURN properties(c) AS p",
                    compact=compact,
                ).single()["p"]

                # 3. Create the full-IRI node with the same props but new URI.
                new_props = dict(node_props)
                new_props["uri"] = full
                session.run(
                    "CREATE (f:OntologyClass) SET f = $props",
                    props=new_props,
                )

                # 4. For each outgoing edge: update _input_uri (if it equals compact)
                #    and _output_uri (if it equals compact's target's mapped URI).
                #    Recreate the edge from the new node.
                for e in out_edges:
                    eprops = dict(e["props"])
                    # Update any URI properties in the edge that reference URIs we're migrating.
                    if eprops.get("_input_uri") == compact:
                        eprops["_input_uri"] = full
                    # Note: _output_uri update happens when we migrate the TARGET node;
                    # here we just preserve whatever's there.
                    target_uri = e["other_uri"]
                    # If the target is itself being migrated, redirect to its full IRI.
                    target_uri_remapped = URI_MAP.get(target_uri, target_uri)
                    session.run(
                        """
                        MATCH (s:OntologyClass {uri: $src})
                        MATCH (o:OntologyClass {uri: $tgt})
                        CALL apoc.create.relationship(s, $rel_type, $props, o) YIELD rel
                        RETURN type(rel) AS t
                        """,
                        src=full, tgt=target_uri_remapped,
                        rel_type=e["rel_type"], props=eprops,
                    )

                # 5. For each incoming edge: recreate from source to the new full-IRI node.
                #    Update _output_uri (if it equals compact).
                for e in in_edges:
                    eprops = dict(e["props"])
                    if eprops.get("_output_uri") == compact:
                        eprops["_output_uri"] = full
                    source_uri = e["other_uri"]
                    source_uri_remapped = URI_MAP.get(source_uri, source_uri)
                    session.run(
                        """
                        MATCH (s:OntologyClass {uri: $src})
                        MATCH (o:OntologyClass {uri: $tgt})
                        CALL apoc.create.relationship(s, $rel_type, $props, o) YIELD rel
                        RETURN type(rel) AS t
                        """,
                        src=source_uri_remapped, tgt=full,
                        rel_type=e["rel_type"], props=eprops,
                    )

                # 6. Delete the compact node (DETACH cleans up the old edges).
                session.run(
                    "MATCH (c:OntologyClass {uri: $compact}) DETACH DELETE c",
                    compact=compact,
                )
                print(f"[done] {compact} -> {full}: migrated and compact deleted")

            # Final verification: no compact URIs remain for the migrated set.
            print("\n=== Phase 1 verify ===")
            for compact, full in URI_MAP.items():
                rec = session.run(
                    """
                    OPTIONAL MATCH (c:OntologyClass {uri: $compact}) WITH c
                    OPTIONAL MATCH (f:OntologyClass {uri: $full})
                    RETURN c IS NOT NULL AS compact_present, f IS NOT NULL AS full_present
                    """,
                    compact=compact, full=full,
                ).single()
                print(f"  {compact}: present={rec['compact_present']}  |  {full}: present={rec['full_present']}")

            # Verify the verb edges have full-IRI _input_uri / _output_uri.
            print("\n=== Verb edges post-migration ===")
            for v in VERB_URIS:
                rec = session.run(
                    """
                    MATCH (s)-[r]->(o) WHERE r.iri = $verb
                    RETURN s.uri AS input_uri, o.uri AS output_uri,
                           r._input_uri AS recorded_input, r._output_uri AS recorded_output
                    """,
                    verb=v,
                ).single()
                if rec:
                    print(f"  {v}: ({rec['input_uri']}) -> ({rec['output_uri']})")
                    print(f"     recorded _input_uri={rec['recorded_input']} _output_uri={rec['recorded_output']}")
                else:
                    print(f"  {v}: NOT FOUND")
        return True
    finally:
        driver.close()


def phase2_weaviate_delete_compact():
    """Delete the OntologyClass entries with compact URIs that we're migrating.
    The next canonical re-ingest will produce the matching full-IRI entries.
    """
    client = weaviate.connect_to_custom(
        http_host=os.environ["WEAVIATE_HTTP_HOST"],
        http_port=8080, http_secure=False,
        grpc_host=os.environ["WEAVIATE_GRPC_HOST"],
        grpc_port=50051, grpc_secure=False,
    )
    try:
        col = client.collections.get("OntologyClass")
        for compact in URI_MAP:
            # generate_uuid5 with the compact URI gives us the existing UUID.
            uuid = generate_uuid5(compact)
            existed = col.data.exists(uuid)
            if existed:
                col.data.delete_by_id(uuid)
                print(f"[weaviate] deleted compact OntologyClass {compact} (uuid={uuid})")
            else:
                print(f"[skip] {compact}: not in Weaviate (UUID {uuid})")
    finally:
        client.close()


def phase3_weaviate_predicate_update():
    """Update Predicate collection input_uri / output_uri to full IRIs for the
    two verbs whose endpoints we migrated."""
    client = weaviate.connect_to_custom(
        http_host=os.environ["WEAVIATE_HTTP_HOST"],
        http_port=8080, http_secure=False,
        grpc_host=os.environ["WEAVIATE_GRPC_HOST"],
        grpc_port=50051, grpc_secure=False,
    )
    try:
        col = client.collections.get("Predicate")
        for verb in VERB_URIS:
            results = col.query.fetch_objects(
                filters=Filter.by_property("verb_iri").equal(verb),
                limit=5,
            )
            for obj in results.objects:
                props_now = obj.properties
                new_in = URI_MAP.get(props_now.get("input_uri"), props_now.get("input_uri"))
                new_out = URI_MAP.get(props_now.get("output_uri"), props_now.get("output_uri"))
                col.data.update(
                    uuid=obj.uuid,
                    properties={"input_uri": new_in, "output_uri": new_out},
                )
                print(f"[predicate] {verb}: input_uri -> {new_in}, output_uri -> {new_out}")
    finally:
        client.close()


if __name__ == "__main__":
    print("=== Phase 1: Neo4j migration ===")
    if not phase1_neo4j_migrate():
        print("\nABORTED in phase 1; review above output before retrying.")
        sys.exit(1)
    print("\n=== Phase 2: Weaviate OntologyClass cleanup ===")
    phase2_weaviate_delete_compact()
    print("\n=== Phase 3: Weaviate Predicate update ===")
    phase3_weaviate_predicate_update()
    print("\nDone.")
