"""Step 2 finisher: update Weaviate Predicate collection input_uri to match
the re-typed Neo4j edges. Without this, the resolver's semantic verb search
would see stale input_uri (mesh:GraphQuery / mesh:KnowledgeQuery)."""
import os
import weaviate
from weaviate.util import generate_uuid5

UPDATES = [
    ("mesh:queryKnowledgeGraph", "mro:WorkInstruction", "mesh:GraphExpertResponse"),
    ("mesh:retrieveKnowledge", "mro:TechnicalManual", "mesh:KnowledgeRetrievalResponse"),
]

client = weaviate.connect_to_custom(
    http_host=os.environ["WEAVIATE_HTTP_HOST"],
    http_port=8080,
    http_secure=False,
    grpc_host=os.environ["WEAVIATE_GRPC_HOST"],
    grpc_port=50051,
    grpc_secure=False,
)
try:
    col = client.collections.get("Predicate")
    # The seed used generate_uuid5(verb_iri) for the UUID — let's not assume
    # that here; just query then update by found UUID.
    from weaviate.classes.query import Filter
    for verb_iri, new_input, output in UPDATES:
        results = col.query.fetch_objects(
            filters=Filter.by_property("verb_iri").equal(verb_iri),
            limit=5,
        )
        if not results.objects:
            print(f"[skip] {verb_iri}: not found in Predicate collection")
            continue
        for obj in results.objects:
            col.data.update(
                uuid=obj.uuid,
                properties={
                    "input_uri": new_input,
                    "output_uri": output,
                },
            )
            print(f"[update] {verb_iri} (uuid={obj.uuid}): input_uri -> {new_input}")

    # Verify
    print("\n=== Post-update Predicate state ===")
    for verb_iri, _, _ in UPDATES:
        results = col.query.fetch_objects(
            filters=Filter.by_property("verb_iri").equal(verb_iri),
            limit=5,
        )
        for obj in results.objects:
            p = obj.properties
            print(f"  {p['verb_iri']}: input_uri={p['input_uri']} output_uri={p['output_uri']}")
finally:
    client.close()
