"""Step 2: re-type mesh:queryKnowledgeGraph and mesh:retrieveKnowledge against
the real domain subject classes. Kills both Contract D pseudo-class violations
(mesh:GraphQuery, mesh:KnowledgeQuery) in the same pass.

Atomicity: each verb's swap is one transaction. We DELETE the old edge first
(unlinks the pseudo-class) then re-create the same-props edge from the new
input class. APOC props copy avoids losing the synonyms/cost_class/etc.

Run from inside doc-tools pod via stdin (has NEO4J creds in env).
"""
import os
from neo4j import GraphDatabase

# (verb_iri, old_input_uri, new_input_uri, output_uri)
RETYPES = [
    ("mesh:queryKnowledgeGraph", "mesh:GraphQuery",
     "mro:WorkInstruction", "mesh:GraphExpertResponse"),
    ("mesh:retrieveKnowledge", "mesh:KnowledgeQuery",
     "mro:TechnicalManual", "mesh:KnowledgeRetrievalResponse"),
]

# Pseudo-classes to drop after their last referencing verb is gone.
# Only delete if 0 incoming/outgoing edges remain (defensive — should always be 0).
DROP_PSEUDO = ["mesh:GraphQuery", "mesh:KnowledgeQuery"]


def main():
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    try:
        with driver.session() as session:
            for verb_iri, old_input, new_input, output in RETYPES:
                # 1. Capture full props of the existing edge.
                rec = session.run(
                    """
                    MATCH (s:OntologyClass {uri: $old_input})-[r]->(o:OntologyClass {uri: $output})
                    WHERE r.iri = $verb_iri
                    RETURN properties(r) AS props, type(r) AS rel_type LIMIT 1
                    """,
                    old_input=old_input, output=output, verb_iri=verb_iri,
                ).single()
                if not rec:
                    print(f"[skip] {verb_iri}: no edge from {old_input} found")
                    continue
                props = dict(rec["props"])
                rel_type = rec["rel_type"]
                # Update _input_uri to point to the real class.
                props["_input_uri"] = new_input

                # 2. Verify new input + output classes exist (Contract D pre-check).
                missing = session.run(
                    """
                    UNWIND [$new_input, $output] AS uri
                    WITH uri WHERE NOT EXISTS { MATCH (:OntologyClass {uri: uri}) }
                    RETURN collect(uri) AS missing
                    """,
                    new_input=new_input, output=output,
                ).single()["missing"]
                if missing:
                    print(f"[abort] {verb_iri}: required OntologyClass missing: {missing}")
                    continue

                # 3. Delete the old edge.
                deleted = session.run(
                    """
                    MATCH (s:OntologyClass {uri: $old_input})-[r]->(o:OntologyClass {uri: $output})
                    WHERE r.iri = $verb_iri
                    WITH r
                    DELETE r
                    RETURN count(*) AS n
                    """,
                    old_input=old_input, output=output, verb_iri=verb_iri,
                ).single()["n"]
                print(f"[delete] {verb_iri} from {old_input}: {deleted} edge(s) removed")

                # 4. Create the new edge via APOC (preserves rel_type).
                created = session.run(
                    """
                    MATCH (s:OntologyClass {uri: $new_input})
                    MATCH (o:OntologyClass {uri: $output})
                    CALL apoc.create.relationship(s, $rel_type, $props, o) YIELD rel
                    RETURN type(rel) AS type, rel.iri AS iri, rel._input_uri AS _input_uri
                    """,
                    new_input=new_input, output=output, rel_type=rel_type, props=props,
                ).single()
                print(f"[create] ({new_input})-[{created['type']}]->({output}) iri={created['iri']} _input_uri={created['_input_uri']}")

            # 5. Drop orphan pseudo-classes (Contract D phantom-class cleanup).
            for pseudo in DROP_PSEUDO:
                check = session.run(
                    """
                    MATCH (c:OntologyClass {uri: $uri})
                    OPTIONAL MATCH (c)-[r1]-(_)
                    WITH c, count(r1) AS edges
                    RETURN edges
                    """,
                    uri=pseudo,
                ).single()
                if check is None:
                    print(f"[skip] {pseudo}: node not found")
                    continue
                edges = check["edges"]
                if edges > 0:
                    print(f"[skip] {pseudo}: still has {edges} edges, not dropping")
                    continue
                session.run("MATCH (c:OntologyClass {uri: $uri}) DELETE c", uri=pseudo)
                print(f"[drop] {pseudo}: orphan OntologyClass node deleted")

            # 6. Final verification.
            print("\n=== Final verb topology ===")
            result = session.run(
                """
                MATCH (s)-[r]->(o)
                WHERE r.iri IN ['mesh:queryKnowledgeGraph','mesh:retrieveKnowledge']
                RETURN r.iri AS verb, s.uri AS input_uri, o.uri AS output_uri,
                       r._input_uri AS recorded_input
                """
            )
            for row in result:
                print(f"  {row['verb']}: ({row['input_uri']}) -> ({row['output_uri']})  [_input_uri={row['recorded_input']}]")

            print("\n=== Pseudo-class scan ===")
            result = session.run(
                """
                MATCH (c:OntologyClass)
                WHERE c.uri IN ['mesh:GraphQuery','mesh:KnowledgeQuery']
                RETURN c.uri AS uri
                """
            )
            rows = list(result)
            if rows:
                print(f"  STILL PRESENT: {[r['uri'] for r in rows]}")
            else:
                print("  CLEAN: both pseudo-classes removed.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
