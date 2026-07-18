"""Emergency: recreate the 2 verb edges that were lost during the migration's
ordering bug (target node didn't exist yet when edge was being recreated).

HIBERNATED — do not run unless the originating incident recurs. The
endpoint_url values below were updated 2026-06-16 from the legacy
`*-svc.default.svc.cluster.local` DNS pattern to the current actual
K8s service names (`iagent-engine-{e,w}`); legacy DNS is unresolvable in
the current cluster. If you're considering running this script, also
revisit whether mesh-registrar's saga is the right path now (it has
been since v0.2, ADR-0006 §Addendum) and prefer that over direct edge
creation.
"""
import os
import sys
from neo4j import GraphDatabase

# DESTRUCTIVE-RUN GUARD (bootstrap-state-debt law; docs/principles/bootstrap-state-debt.md).
# NON-REPRODUCIBLE MANUAL ACTION — never a fix. Executes at import/top-level (no main()),
# is HIBERNATED, and NON-IDEMPOTENT (apoc.create.relationship DUPLICATES the verb edges on
# every run). mesh-registrar's saga has owned these edges since v0.2 (ADR-0006 §Addendum) —
# that is the reproducible home. A WORK-shaped target is refused OUTRIGHT (no flag); a
# sandbox run also needs the ack flag AND the reproducible fix to land the same session.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap_guard import refuse_unless_throwaway  # noqa: E402
refuse_unless_throwaway(
    "Neo4j verb edges (apoc.create -> NON-IDEMPOTENT, DUPLICATES on re-run; HIBERNATED)",
    ack_env="ALLOW_HIBERNATED_RECREATE",
    reproducible_home="the mesh-registrar saga (ADR-0006 Addendum — sole writer of verb edges)",
    targets=[os.environ.get("NEO4J_URI", "")],
)

# The known props of each verb (captured pre-migration).
# input_uri and output_uri are now the FULL IRI forms.
EDGES = [
    {
        "rel_type": "queryKnowledgeGraph",
        "input_uri": "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/WorkInstruction",
        "output_uri": "http://invincible-agent/mesh#GraphExpertResponse",
        "props": {
            "_input_uri": "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/WorkInstruction",
            "_output_uri": "http://invincible-agent/mesh#GraphExpertResponse",
            "anti_synonyms": [],
            "cost_class": "slow",
            "domains": ["MAINTENANCE", "MANUFACTURING"],
            "endpoint_url": "http://iagent-engine-e:8086/query_graph",
            "iri": "mesh:queryKnowledgeGraph",
            "namespace_authority": "platform",
            "openapi_schema": "{}",
            "owner_persona": "AUDITOR",
            "requires_human_approval": False,
            "sdk_version": "0.0.0",
            "synonyms": ["query graph", "graph lookup", "cypher query", "find in graph", "knowledge graph search"],
            "tool_kind": "Engine",
            "tool_urn": "urn:li:mlModel:(urn:li:dataPlatform:mesh,engine_e_neo4j_expert,PROD)",
            "version": "0.1.0",
        },
    },
    {
        "rel_type": "retrieveKnowledge",
        "input_uri": "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/TechnicalManual",
        "output_uri": "http://invincible-agent/mesh#KnowledgeRetrievalResponse",
        "props": {
            "_input_uri": "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/TechnicalManual",
            "_output_uri": "http://invincible-agent/mesh#KnowledgeRetrievalResponse",
            "anti_synonyms": [],
            "cost_class": "medium",
            "domains": ["MAINTENANCE", "MANUFACTURING"],
            "endpoint_url": "http://iagent-engine-w:8088/query_knowledge",
            "iri": "mesh:retrieveKnowledge",
            "namespace_authority": "platform",
            "openapi_schema": "{}",
            "owner_persona": "TECH_WRITER",
            "requires_human_approval": False,
            "sdk_version": "0.0.0",
            "synonyms": ["search docs", "find in manuals", "semantic search", "look up policy", "consult manual"],
            "tool_kind": "Engine",
            "tool_urn": "urn:li:mlModel:(urn:li:dataPlatform:mesh,engine_w_weaviate_expert,PROD)",
            "version": "0.1.0",
        },
    },
]

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
)
try:
    with driver.session() as session:
        for e in EDGES:
            # Verify both endpoints exist.
            pre = session.run(
                """
                OPTIONAL MATCH (s:OntologyClass {uri: $input_uri})
                OPTIONAL MATCH (o:OntologyClass {uri: $output_uri})
                RETURN s IS NOT NULL AS in_ok, o IS NOT NULL AS out_ok
                """,
                input_uri=e["input_uri"], output_uri=e["output_uri"],
            ).single()
            if not (pre["in_ok"] and pre["out_ok"]):
                print(f"ABORT {e['rel_type']}: in_ok={pre['in_ok']} out_ok={pre['out_ok']}")
                continue
            session.run(
                """
                MATCH (s:OntologyClass {uri: $input_uri})
                MATCH (o:OntologyClass {uri: $output_uri})
                CALL apoc.create.relationship(s, $rel_type, $props, o) YIELD rel
                RETURN type(rel) AS t
                """,
                input_uri=e["input_uri"], output_uri=e["output_uri"],
                rel_type=e["rel_type"], props=e["props"],
            )
            print(f"[create] ({e['input_uri']})-[{e['rel_type']}]->({e['output_uri']})")

        print("\n=== Verify ===")
        result = session.run(
            """
            MATCH (s)-[r]->(o)
            WHERE r.iri IN ['mesh:queryKnowledgeGraph','mesh:retrieveKnowledge']
            RETURN r.iri AS verb, s.uri AS input, o.uri AS output,
                   r._input_uri AS recorded_in, r._output_uri AS recorded_out
            """
        )
        for row in result:
            print(f"  {row['verb']}: ({row['input']}) -> ({row['output']})")
            print(f"    recorded _input_uri={row['recorded_in']} _output_uri={row['recorded_out']}")
finally:
    driver.close()
