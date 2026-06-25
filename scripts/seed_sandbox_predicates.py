#!/usr/bin/env python3
"""Sandbox seed: register the iagent engines as predicates in Neo4j + Weaviate.

doc-tools normally does this via the AITool sensor → sync_aitool_predicate_to_neo4j
asset chain after each engine self-registers to DataHub on startup. For sandbox
testing without DataHub (Phase 2 Option A), this script writes the predicate
edges directly so /search_predicates has something to return.

Run via port-forwards from your local machine:
    kubectl -n sandbox port-forward svc/iagent-neo4j 7687:7687 &
    kubectl -n sandbox port-forward svc/iagent-weaviate 8080:8080 &
    kubectl -n sandbox port-forward svc/iagent-weaviate-grpc 50051:50051 &
    py scripts/seed_sandbox_predicates.py

Idempotent: re-running upserts. Safe to re-seed after a code change.

CANONICAL-FORM DISCIPLINE (2026-06-13). Subject + object URIs (the
`input_uri` / `output_uri` fields below) MUST be canonical full-IRI
(`http://invincible-agent/mesh#*`) — the form `sync_jena_ontologies_to_neo4j`
materializes from `mesh_system.ttl`. Using compact-form (`mesh:*`)
creates DUPLICATE :OntologyClass nodes alongside the canonical ones,
which is the regression class the substrate-level
`test_no_compact_form_for_*` guards catch. This is a SEED script (it
re-runs every sandbox bootstrap), not a one-time migration, so the
class guard's allowlist intentionally does NOT cover this file —
canonical-form is enforced. Verb IRIs (`verb_iri` field) remain
compact-form: the verb relationship `.iri` property is still
substrate-canonical-compact (verbs were NOT migrated by Session 2;
that's a separate scope decision).
"""

from __future__ import annotations

import json
import os
import sys

try:
    from neo4j import GraphDatabase
except ImportError:
    print("ERROR: install neo4j: pip install neo4j", file=sys.stderr)
    sys.exit(1)

try:
    import weaviate
    import weaviate.classes as wvc
    from weaviate.util import generate_uuid5
except ImportError:
    print("ERROR: install weaviate-client: pip install weaviate-client>=4.5.4", file=sys.stderr)
    sys.exit(1)


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme-neo4j-sandbox")

WEAVIATE_HTTP_HOST = os.getenv("WEAVIATE_HTTP_HOST", "localhost")
WEAVIATE_HTTP_PORT = int(os.getenv("WEAVIATE_HTTP_PORT", "8080"))
WEAVIATE_GRPC_HOST = os.getenv("WEAVIATE_GRPC_HOST", "localhost")
WEAVIATE_GRPC_PORT = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))


# ---------------------------------------------------------------------------
# The four engines deployed in Phase 2 sandbox. Mirrors what
# `register_engine_to_mesh()` would have emitted to DataHub (and what
# doc-tools' sensor would have synced).
# ---------------------------------------------------------------------------
# Canonical full-IRI namespace for mesh:* subjects — same form
# `sync_jena_ontologies_to_neo4j` writes from `mesh_system.ttl`. Using
# compact form here creates duplicate OntologyClass nodes (see this
# script's module docstring).
_MESH = "http://invincible-agent/mesh#"


# Post-migration canonical input_uris.
#
# The historical seed wrote each verb against a ``mesh:`` pseudo-class
# (``DatasetAnalysisRequest``, ``KnowledgeQuery``, ``GraphQuery``,
# ``AgentTask``). Subsequent migrations re-typed several of these to
# real ontology classes (Phase 5 moved ``analyzeDataset`` to ``idp:Dataset``;
# the mesh#AgentTask retype kept ``analyzeWithCodeAgent`` against
# ``mesh:AgentTask``). The seed must match the post-migration canonical
# state — otherwise re-running it writes pre-migration rows that coexist
# with the engines' own post-migration self-registrations, bloating
# substrate without misrouting (Step 5 reads endpoint from Neo4j,
# canonical pairs differ so the dedup guard doesn't flag them, but
# they're dead weight that complicates audits).
#
# Each entry's ``input_uri`` MUST match what the engine itself writes
# from its lifespan via ``register_engine_to_mesh`` — that's the
# convergence rule that keeps the seed idempotent against engine
# self-registration.
_IDP = "http://invincible-agent/idp#"

ENGINES = [
    {
        "name": "engine_a_restate_analyst",
        "verb_iri": "mesh:analyzeWithCodeAgent",   # verbs stay compact (substrate-canonical for verbs)
        # ``mesh:AgentTask`` per the 2026-06-11 system-verb retype —
        # matches restate_analyst/main.py's lifespan registration.
        "input_uri": _MESH + "AgentTask",
        "output_uri": _MESH + "AgentResponse",
        "endpoint_url": "http://iagent-engine-a:8081/analyze",
        "owner_persona": "DATA_STEWARD",
        "domains": ["MAINTENANCE", "MANUFACTURING", "SUSTAINMENT"],
        "synonyms": ["analyze", "process query", "code agent analysis",
                     "smolagents loop", "general analysis"],
        "description": "Durable analyst engine. Runs a smolagents CodeAgent "
                       "loop with mem0 memory + DataHub-aware tool injection.",
        "cost_class": "slow",
        "requires_human_approval": False,
    },
    {
        "name": "engine_e_neo4j_expert",
        "verb_iri": "mesh:queryKnowledgeGraph",
        # Engine E self-registers ``queryKnowledgeGraph`` against THREE
        # distinct input_uris (WorkInstruction, ProcedureStep,
        # ProcedureDataModule) — one per maintenance sub-domain. The
        # seed picks ``mesh:GraphQuery`` (the canonical envelope class
        # for graph queries) as the skeleton entry; the per-sub-domain
        # rows arrive on engine boot.
        "input_uri": _MESH + "GraphQuery",
        "output_uri": _MESH + "GraphExpertResponse",
        "endpoint_url": "http://iagent-engine-e:8086/query_graph",
        "owner_persona": "AUDITOR",
        "domains": ["MAINTENANCE", "MANUFACTURING"],
        "synonyms": ["query graph", "graph lookup", "cypher query",
                     "find in graph", "knowledge graph search"],
        "description": "Knowledge graph expert. Runs a smolagents CodeAgent "
                       "over Neo4j with execute_cypher / get_graph_schema / "
                       "search_manual_text tools.",
        "cost_class": "slow",
        "requires_human_approval": False,
    },
    {
        "name": "engine_da_data_analyst",
        "verb_iri": "mesh:analyzeDataset",
        # ``idp:Dataset`` per the Phase 5 catalog-verb migration
        # (2026-06-11). Matches data_analyst/main.py:61. Re-seeding
        # this against the pre-migration ``mesh:DatasetAnalysisRequest``
        # is the substrate-bloat shape Step 2 of the contamination-fix
        # sequence was meant to clean — fixing the seed makes the
        # clean idempotent.
        "input_uri": _IDP + "Dataset",
        "output_uri": _MESH + "DatasetAnalysisReport",
        "endpoint_url": "http://iagent-data-analyst:8089/analyze_data",
        "owner_persona": "DATA_STEWARD",
        "domains": ["DATA_ENGINEERING"],
        "synonyms": ["analyze data", "run SQL", "query dataset",
                     "data analysis", "sql analysis"],
        "description": "Data analyst agent. smolagents writes SQL against "
                       "DataHub-backed datasets via CortexDataClient + DuckDB.",
        "cost_class": "slow",
        "requires_human_approval": False,
    },
    {
        "name": "engine_w_weaviate_expert",
        "verb_iri": "mesh:retrieveKnowledge",
        # Engine W self-registers ``retrieveKnowledge`` against FOUR
        # distinct input_uris (TechnicalManual, FaultIsolationDataModule,
        # IllustratedPartsDataModule, DescriptiveDataModule) — one per
        # manual sub-class. The seed picks ``mesh:KnowledgeQuery`` (the
        # canonical envelope class) as the skeleton entry; the per-
        # sub-class rows arrive on engine boot.
        "input_uri": _MESH + "KnowledgeQuery",
        "output_uri": _MESH + "KnowledgeRetrievalResponse",
        "endpoint_url": "http://iagent-engine-w:8088/query_knowledge",
        "owner_persona": "TECH_WRITER",
        "domains": ["MAINTENANCE", "MANUFACTURING"],
        "synonyms": ["search docs", "find in manuals", "semantic search",
                     "look up policy", "consult manual"],
        "description": "Knowledge retrieval engine. Weaviate v4 hybrid search "
                       "(near_text + BM25) with strict domain segregation.",
        "cost_class": "medium",
        "requires_human_approval": False,
    },
]


PREDICATE_COLLECTION = "Predicate"


def humanize_verb_local(verb_local: str) -> str:
    """camelCase → 'camel case' (matches doc-tools' _humanize_verb_local)."""
    out = []
    for i, ch in enumerate(verb_local):
        if i > 0 and ch.isupper() and not verb_local[i - 1].isupper():
            out.append(" ")
        out.append(ch.lower())
    return "".join(out).strip()


def get_verb_local_name(verb_iri: str) -> str:
    return verb_iri.split(":")[-1] if ":" in verb_iri else verb_iri


def build_search_text(verb_iri: str, verb_local: str, synonyms: list,
                      description: str) -> str:
    parts = [humanize_verb_local(verb_local)]
    if synonyms:
        parts.append(", ".join(s for s in synonyms if s))
    if description:
        parts.append(description)
    return ". ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Neo4j seed
# ---------------------------------------------------------------------------
NEO4J_CYPHER = """
MERGE (s:OntologyClass {uri: $input_uri})
MERGE (o:OntologyClass {uri: $output_uri})
WITH s, o
CALL apoc.merge.relationship(
    s,
    $verb_local,
    {iri: $verb_iri},
    $props,
    o,
    $props
) YIELD rel
RETURN type(rel) AS rel_type
"""


def seed_neo4j():
    print(f"[neo4j] Connecting to {NEO4J_URI} ...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            for eng in ENGINES:
                verb_local = get_verb_local_name(eng["verb_iri"])
                props = {
                    "iri": eng["verb_iri"],
                    "synonyms": eng["synonyms"],
                    "domains": eng["domains"],
                    "owner_persona": eng["owner_persona"],
                    "endpoint_url": eng["endpoint_url"],
                    "cost_class": eng["cost_class"],
                    "requires_human_approval": eng["requires_human_approval"],
                    "namespace_authority": "platform",
                    "tool_kind": "Engine",
                    "version": "0.1.0",
                    "sdk_version": "0.0.0",
                    "openapi_schema": "",
                    "tool_urn": f"urn:li:mlModel:(urn:li:dataPlatform:mesh,{eng['name']},PROD)",
                }
                result = session.run(
                    NEO4J_CYPHER,
                    input_uri=eng["input_uri"],
                    output_uri=eng["output_uri"],
                    verb_local=verb_local,
                    verb_iri=eng["verb_iri"],
                    props=props,
                )
                rec = result.single()
                print(f"  ✓ ({eng['input_uri']}) -[{rec['rel_type']}]-> "
                      f"({eng['output_uri']}) for {eng['name']}")
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# Weaviate seed
# ---------------------------------------------------------------------------
def ensure_predicate_collection(client):
    # Delete and recreate so we pick up schema changes (inverted-index
    # property-length config). Sandbox-safe — the seed below re-populates.
    if client.collections.exists(PREDICATE_COLLECTION):
        print(f"[weaviate] {PREDICATE_COLLECTION} exists — dropping for re-create")
        client.collections.delete(PREDICATE_COLLECTION)
    print(f"[weaviate] Creating {PREDICATE_COLLECTION} collection")
    return client.collections.create(
        name=PREDICATE_COLLECTION,
        # IndexPropertyLength=true is required by Engine O's domain-scope
        # filter which uses `Filter.by_property('domains', length=True).equal(0)`
        # to match domain-agnostic predicates. Without it Weaviate errors:
        # "Property length must be indexed to be filterable!"
        inverted_index_config=wvc.config.Configure.inverted_index(
            index_property_length=True,
        ),
        properties=[
            wvc.config.Property(name="verb_iri", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="verb_local", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="input_uri", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="output_uri", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="endpoint_url", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="owner_persona", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="domains", data_type=wvc.config.DataType.TEXT_ARRAY),
            wvc.config.Property(name="cost_class", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="requires_human_approval", data_type=wvc.config.DataType.BOOL),
            wvc.config.Property(name="search_text", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="synonyms", data_type=wvc.config.DataType.TEXT_ARRAY),
            wvc.config.Property(name="description", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="tool_urn", data_type=wvc.config.DataType.TEXT),
        ],
    )


def seed_weaviate():
    print(f"[weaviate] Connecting to {WEAVIATE_HTTP_HOST}:{WEAVIATE_HTTP_PORT} "
          f"+ grpc {WEAVIATE_GRPC_HOST}:{WEAVIATE_GRPC_PORT} ...")
    client = weaviate.connect_to_custom(
        http_host=WEAVIATE_HTTP_HOST,
        http_port=WEAVIATE_HTTP_PORT,
        http_secure=False,
        grpc_host=WEAVIATE_GRPC_HOST,
        grpc_port=WEAVIATE_GRPC_PORT,
        grpc_secure=False,
    )
    try:
        collection = ensure_predicate_collection(client)
        for eng in ENGINES:
            verb_local = get_verb_local_name(eng["verb_iri"])
            search_text = build_search_text(
                eng["verb_iri"], verb_local, eng["synonyms"], eng["description"]
            )
            uuid = generate_uuid5(f"{eng['verb_iri']}|{eng['input_uri']}")
            props = {
                "verb_iri": eng["verb_iri"],
                "verb_local": verb_local,
                "input_uri": eng["input_uri"],
                "output_uri": eng["output_uri"],
                "endpoint_url": eng["endpoint_url"],
                "owner_persona": eng["owner_persona"],
                "domains": eng["domains"],
                "cost_class": eng["cost_class"],
                "requires_human_approval": eng["requires_human_approval"],
                "search_text": search_text,
                "synonyms": eng["synonyms"],
                "description": eng["description"],
                "tool_urn": f"urn:li:mlModel:(urn:li:dataPlatform:mesh,{eng['name']},PROD)",
            }
            if collection.data.exists(uuid=uuid):
                collection.data.replace(uuid=uuid, properties=props)
                print(f"  ✓ replaced {eng['verb_iri']} (uuid={uuid})")
            else:
                collection.data.insert(uuid=uuid, properties=props)
                print(f"  ✓ inserted {eng['verb_iri']} (uuid={uuid})")
    finally:
        client.close()


def main():
    print("== Sandbox predicate seed ==")
    print(f"  Neo4j: {NEO4J_URI}")
    print(f"  Weaviate: http {WEAVIATE_HTTP_HOST}:{WEAVIATE_HTTP_PORT}, "
          f"grpc {WEAVIATE_GRPC_HOST}:{WEAVIATE_GRPC_PORT}")
    print(f"  {len(ENGINES)} engines to register")
    print()
    seed_neo4j()
    print()
    seed_weaviate()
    print()
    print("== Done ==")
    print()
    print("Verify with Engine O:")
    print('  curl -s -X POST http://localhost:8084/search_predicates \\')
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"query":"diagnose vibration","entitled_domains":["MAINTENANCE"],"limit":3}\' | jq')


if __name__ == "__main__":
    main()
