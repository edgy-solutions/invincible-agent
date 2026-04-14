import os
import json
from neo4j import GraphDatabase
from smolagents import tool

def get_neo4j_driver():
    """Returns a Neo4j driver configured from the environment."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "changeme")
    return GraphDatabase.driver(uri, auth=(user, password))

@tool
def execute_cypher(query: str) -> str:
    """
    Executes a Cypher read query against the Neo4j military graph database.
    
    CRITICAL DATABASE SCHEMA & RULES:
    You are querying a graph of military technical manuals (S1000D, IADS, DITA, MIL-STD-40051).
    The graph was imported via Neosemantics with handleVocabUris: 'IGNORE'.

    DO NOT USE URI PREFIXES:
    Do NOT prefix labels or properties with `mil:` or any other namespace.
    Correct: MATCH (p:Procedure)
    Incorrect: MATCH (p:`mil:Procedure`)

    CASE SENSITIVITY:
    Neo4j CONTAINS is CASE-SENSITIVE. Always use toLower() for text matching:
    CORRECT:   WHERE toLower(p.name) CONTAINS 'fuel pump'
    INCORRECT: WHERE p.name CONTAINS 'fuel pump'

    STARTING STRATEGY:
    Start broad. First discover what exists with a simple query like:
    MATCH (p:Procedure) RETURN p.name LIMIT 20
    Then refine based on actual data.

    Args:
        query: The raw Cypher string to execute. Limit queries via `LIMIT 50` to prevent payload overflow.
    
    Returns:
        JSON stringified results from the Neo4j session.
    """
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            result = session.execute_read(lambda tx: list(tx.run(query)))
            # Convert Neo4j Records to vanilla dicts for JSON serialization
            records = [dict(record) for record in result]
            return json.dumps(records, default=str)
    except Exception as e:
        return f"Neo4j Query Error: {str(e)}"

@tool
def get_graph_schema() -> str:
    """
    Returns the visual layout of the current Neo4j database schema.
    
    Use this tool if your `execute_cypher` query fails due to a missing property
    or relationship, so you can inspect the live database schema and correct your query.
    
    Returns:
        A JSON stringified representation of all specific labels, relationships,
        and properties present in the live graph.
    """
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            result = session.execute_read(lambda tx: list(tx.run("CALL db.schema.visualization()")))
            
            if not result:
                return "Schema visualization returned no results."
                
            record = result[0]
            
            # Nodes
            nodes = []
            for node in record.get("nodes", []):
                nodes.append({
                    "labels": list(node.labels),
                    "element_id": node.element_id
                })
                
            # Relationships
            relationships = []
            for rel in record.get("relationships", []):
                relationships.append({
                    "type": rel.type,
                    "start_labels": list(rel.start_node.labels),
                    "end_labels": list(rel.end_node.labels)
                })
                
            schema = {
                "available_labels": nodes,
                "available_relationships": relationships
            }
            return json.dumps(schema, indent=2)
    except Exception as e:
        return f"Neo4j Schema Error: {str(e)}"
