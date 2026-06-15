"""Seed the 3 mro_extension classes into Weaviate (OntologyClass, domain=MAINTENANCE)
and Neo4j (:OntologyClass nodes), matching how the existing 614 MAINTENANCE classes
got there.

CANONICAL PIPELINE GAP (filed as Step-1 follow-up):
  - ingest_ontology_job derives Weaviate `domain` from the s3 path's first segment
    (`mro/` -> `MRO`). The resolver queries with `domain="MAINTENANCE"`, so classes
    landed at `MRO` are invisible. The 614 existing MAINTENANCE classes were seeded
    by a path that's not in invincible-agent or doc-tools — likely an interactive
    notebook or external repo. Tonight we mirror that path here so the gate can
    pass; the canonical pipeline needs either domain-mapping (mro -> MAINTENANCE)
    or the resolver needs multi-domain query support. Either fix is a separate PR.

This runs INSIDE the doc-tools pod via stdin so it has Weaviate/Neo4j credentials
already.

CANONICAL-FORM DISCIPLINE (2026-06-15). Subject URIs MUST be canonical
full-IRI (`https://spec.industrialontologies.org/.../`) — the form
`sync_jena_ontologies_to_neo4j` materializes from `mro_extension.ttl`.
Using compact-form (`mro:*`) creates DUPLICATE :OntologyClass nodes
alongside the canonicals, which is the regression class the substrate-
level test_no_compact_form_* guards catch. This is a RE-RUNNABLE seed
(class guard's RE_RUNNABLE_SEED_SCRIPTS_NOT_EXEMPT set), not a one-time
migration, so canonical-form is enforced. Same fix pattern as
`seed_sandbox_predicates.py` 2026-06-13.
"""
import os
import weaviate
from weaviate.classes.init import Auth
from weaviate.util import generate_uuid5
from neo4j import GraphDatabase

# Canonical full-IRI namespace for mro:* subjects per IOF / MaintenanceReferenceOntology.
# Same form `sync_jena_ontologies_to_neo4j` writes from `mro_extension.ttl`.
_MRO = "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/"


CLASSES = [
    {
        "uri": _MRO + "TechnicalManual",
        "label": "Technical Manual",
        "definition": (
            "A document conveying descriptive technical information about a "
            "system, asset, or procedure — operations manuals, maintenance "
            "manuals, troubleshooting guides, and reference documentation. "
            "Routable subject for manual-text search verbs (mesh:retrieveKnowledge "
            "against Engine W). Queries about searching, looking up, or consulting "
            "a technical manual or its content target this class."
        ),
        "domain": "MAINTENANCE",
    },
    {
        "uri": _MRO + "Diagram",
        "label": "Diagram",
        "definition": (
            "A visual representation attached to a work instruction or technical "
            "manual — schematics, exploded views, callouts, and procedural "
            "illustrations. Queries asking for a diagram, drawing, schematic, "
            "or illustration target this class."
        ),
        "domain": "MAINTENANCE",
    },
    {
        "uri": _MRO + "ProcedureStep",
        "label": "Procedure Step",
        "definition": (
            "A single ordered action within a maintenance procedure or work "
            "instruction — pre-conditions, action, verification. Queries for "
            "the steps of a procedure or a specific step of a work instruction "
            "target this class."
        ),
        "domain": "MAINTENANCE",
    },
]


def seed_weaviate():
    client = weaviate.connect_to_custom(
        http_host=os.environ["WEAVIATE_HTTP_HOST"],
        http_port=8080,
        http_secure=False,
        grpc_host=os.environ["WEAVIATE_GRPC_HOST"],
        grpc_port=50051,
        grpc_secure=False,
    )
    try:
        col = client.collections.get("OntologyClass")
        for cls in CLASSES:
            uuid = generate_uuid5(cls["uri"])
            existed = col.data.exists(uuid)
            col.data.insert(
                properties={
                    "uri": cls["uri"],
                    "label": cls["label"],
                    "definition": cls["definition"],
                    "domain": cls["domain"],
                },
                uuid=uuid,
            ) if not existed else col.data.update(
                uuid=uuid,
                properties={
                    "uri": cls["uri"],
                    "label": cls["label"],
                    "definition": cls["definition"],
                    "domain": cls["domain"],
                },
            )
            print(f"[weaviate] {'updated' if existed else 'inserted'} {cls['uri']} (domain={cls['domain']})")
    finally:
        client.close()


def seed_neo4j():
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    try:
        with driver.session() as session:
            for cls in CLASSES:
                result = session.run(
                    """
                    MERGE (c:OntologyClass {uri: $uri})
                    SET c.label = $label, c.definition = $definition, c.domain = $domain
                    RETURN c.uri AS uri
                    """,
                    uri=cls["uri"], label=cls["label"],
                    definition=cls["definition"], domain=cls["domain"],
                )
                rec = result.single()
                print(f"[neo4j] OntologyClass MERGE -> {rec['uri']}")
    finally:
        driver.close()


if __name__ == "__main__":
    seed_weaviate()
    seed_neo4j()
    print("Done.")
