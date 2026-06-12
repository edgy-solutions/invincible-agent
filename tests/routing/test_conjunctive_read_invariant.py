"""Standing-guard for the conjunctive-read invariant.

This is the **load-bearing safety test** the ADR-0006 §Addendum
(2026-06-13) rollback decision rests on. The argument: a half-
registered AITool predicate (Neo4j edge present, Weaviate row missing,
or the inverse) is **unroutable by construction** because
``/classify_predicate`` only feeds the LLM verbs that appear in BOTH
stores. If a future change makes single-store presence sufficient to
dispatch a user-question verb, this guard turns red BEFORE the
fork-decision's safety argument quietly weakens.

Cases:

  - **Neo4j-only edge** (case #2 of the partial-failure matrix):
    insert a synthetic predicate edge into Neo4j without a corresponding
    Weaviate row. Verify ``/find_compatible_verbs`` returns the verb
    (Cypher walks the graph — that's the Neo4j side speaking) BUT
    ``/classify_predicate`` does NOT include it in
    ``candidate_verb_iris`` (the LLM's constrained enum).

  - **Weaviate-only row** (case #3): insert a synthetic Predicate row
    into Weaviate without a Neo4j edge. Verify
    ``/find_compatible_verbs`` does NOT return the verb (no edge) AND
    ``/classify_predicate`` filters it out before the enum (the compat
    intersection drops it).

  - **Both present** (control): insert both, verify the verb DOES
    reach the LLM's enum — the invariant correctly admits valid
    registrations.

The tests run against the live cluster's Engine O + Neo4j + Weaviate
via the existing port-forward (same as
``test_resolve_instance_probes.py``). Cleanup is mandatory — every
insert is matched by a delete in a ``finally`` block so a test crash
doesn't poison the substrate.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
import pytest


_BASE = os.getenv("ROUTING_TEST_BASE_URL", "http://localhost:8084")
_TIMEOUT_SEC = float(os.getenv("ROUTING_TEST_TIMEOUT_SEC", "45"))

# We use a fixed real subject the conjunctive test exercises against —
# idp:Dataset (full-IRI form) is canonical and has registered verbs in
# the cluster, so we know the compat path works for real verbs. Our
# synthetic verb is then injected as a SECOND verb typed against the
# same subject.
_TEST_SUBJECT_URI = "http://invincible-agent/idp#Dataset"
_TEST_OUTPUT_URI = "mesh:AssetProfile"
_SYNTHETIC_VERB_IRI = "mesh:conjunctiveInvariantProbeVerb"


@pytest.fixture
def neo4j_driver():
    """Connect to Neo4j via the cluster's bolt endpoint. Tests skip if
    unreachable — this is an integration suite, not a unit one."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        pytest.skip("neo4j driver not installed")
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "changeme-neo4j-sandbox")
    try:
        d = GraphDatabase.driver(uri, auth=(user, pwd))
        d.verify_connectivity()
    except Exception as exc:
        pytest.skip(f"Neo4j unreachable: {exc}")
    yield d
    d.close()


@pytest.fixture
def weaviate_client():
    """Connect to Weaviate. Tests skip if unreachable."""
    try:
        import weaviate
    except ImportError:
        pytest.skip("weaviate-client not installed")
    http_host = os.getenv("WEAVIATE_HTTP_HOST", "localhost")
    http_port = int(os.getenv("WEAVIATE_HTTP_PORT", "8080"))
    grpc_host = os.getenv("WEAVIATE_GRPC_HOST", http_host)
    grpc_port = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))
    try:
        c = weaviate.connect_to_custom(
            http_host=http_host, http_port=http_port, http_secure=False,
            grpc_host=grpc_host, grpc_port=grpc_port, grpc_secure=False,
        )
    except Exception as exc:
        pytest.skip(f"Weaviate unreachable: {exc}")
    yield c
    try:
        c.close()
    except Exception:
        pass


def _post_engine_o(path: str, payload: dict) -> tuple[int, dict]:
    try:
        resp = httpx.post(f"{_BASE}{path}", json=payload, timeout=_TIMEOUT_SEC)
    except httpx.ConnectError as exc:
        pytest.skip(f"Engine O not reachable at {_BASE}{path}: {exc}")
    return resp.status_code, resp.json()


def _insert_neo4j_synthetic_edge(driver: Any, *, tool_urn: str) -> None:
    """MERGE a synthetic predicate edge from _TEST_SUBJECT_URI to
    _TEST_OUTPUT_URI with iri=_SYNTHETIC_VERB_IRI. Both endpoints must
    exist as OntologyClass nodes; we assume they do (canonical idp +
    mesh ingest). Otherwise the MERGE fails and the test correctly
    skips itself by surfacing the failure."""
    cypher = """
    MATCH (s:OntologyClass {uri: $input_uri})
    MATCH (o:OntologyClass {uri: $output_uri})
    WITH s, o
    CALL apoc.merge.relationship(
        s,
        'conjunctiveInvariantProbeVerb',
        {iri: $verb_iri, _tool_urn: $tool_urn},
        {iri: $verb_iri, _tool_urn: $tool_urn,
         endpoint_url: 'http://conjunctive-invariant-probe.test',
         provider: 'conjunctive_probe',
         owner_persona: 'TEST',
         domains: ['DATA_ENGINEERING']},
        o,
        {iri: $verb_iri, _tool_urn: $tool_urn,
         endpoint_url: 'http://conjunctive-invariant-probe.test',
         provider: 'conjunctive_probe',
         owner_persona: 'TEST',
         domains: ['DATA_ENGINEERING']}
    ) YIELD rel
    RETURN type(rel) AS rel_type
    """
    with driver.session() as session:
        session.run(
            cypher,
            input_uri=_TEST_SUBJECT_URI,
            output_uri=_TEST_OUTPUT_URI,
            verb_iri=_SYNTHETIC_VERB_IRI,
            tool_urn=tool_urn,
        )


def _delete_neo4j_synthetic_edge(driver: Any, *, tool_urn: str) -> None:
    cypher = """
    MATCH (s:OntologyClass {uri: $input_uri})-[r]->(o:OntologyClass {uri: $output_uri})
    WHERE r.iri = $verb_iri AND r._tool_urn = $tool_urn
    DELETE r
    """
    with driver.session() as session:
        session.run(
            cypher,
            input_uri=_TEST_SUBJECT_URI,
            output_uri=_TEST_OUTPUT_URI,
            verb_iri=_SYNTHETIC_VERB_IRI,
            tool_urn=tool_urn,
        )


def _insert_weaviate_synthetic_row(weaviate_client: Any, *, tool_urn: str) -> uuid.UUID:
    import hashlib
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    name = f"{_SYNTHETIC_VERB_IRI}|{_TEST_SUBJECT_URI}"
    h = hashlib.sha1(namespace.bytes + name.encode("utf-8")).digest()
    deterministic_uuid = uuid.UUID(bytes=h[:16], version=5)

    collection = weaviate_client.collections.get("Predicate")
    properties = {
        "verb_iri": _SYNTHETIC_VERB_IRI,
        "verb_local": "conjunctiveInvariantProbeVerb",
        "input_uri": _TEST_SUBJECT_URI,
        "output_uri": _TEST_OUTPUT_URI,
        "endpoint_url": "http://conjunctive-invariant-probe.test",
        "owner_persona": "TEST",
        "domains": ["DATA_ENGINEERING"],
        "cost_class": "fast",
        "requires_human_approval": False,
        "search_text": (
            f"{_SYNTHETIC_VERB_IRI} conjunctiveInvariantProbeVerb "
            f"conjunctive read invariant probe verb"
        ),
        "synonyms": ["conjunctive invariant probe verb"],
        "anti_synonyms": [],
        "description": "Conjunctive-read invariant standing-guard probe verb.",
        "tool_urn": tool_urn,
    }
    if collection.data.exists(uuid=deterministic_uuid):
        collection.data.replace(uuid=deterministic_uuid, properties=properties)
    else:
        collection.data.insert(uuid=deterministic_uuid, properties=properties)
    return deterministic_uuid


def _delete_weaviate_synthetic_row(weaviate_client: Any, *, uid: uuid.UUID) -> None:
    collection = weaviate_client.collections.get("Predicate")
    if collection.data.exists(uuid=uid):
        collection.data.delete_by_id(uuid=uid)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_neo4j_only_edge_does_not_reach_llm_enum(neo4j_driver, weaviate_client):
    """Case #2: Neo4j has the edge, Weaviate has no row. The LLM MUST
    NOT see the verb in its constrained enum."""
    tool_urn = f"urn:li:mlModel:(...,conjunctive_probe_n_only,PROD)_{uuid.uuid4().hex[:8]}"
    try:
        _insert_neo4j_synthetic_edge(neo4j_driver, tool_urn=tool_urn)

        # Cypher side: verb SHOULD appear in compat (Neo4j has it).
        status, compat_body = _post_engine_o(
            "/find_compatible_verbs",
            {"subject_uri": _TEST_SUBJECT_URI, "max_hops": 5, "entitled_domains": []},
        )
        assert status == 200
        compat_verbs = [v.get("verb_iri") for v in (compat_body.get("verbs") or [])]
        assert _SYNTHETIC_VERB_IRI in compat_verbs, (
            f"Sanity check failed: Neo4j-only synthetic edge should appear in "
            f"/find_compatible_verbs (Cypher walks the graph). Got: {compat_verbs}"
        )

        # /classify_predicate side: enum MUST NOT include the synthetic verb.
        # The conjunctive-read invariant: only verbs in BOTH stores reach the LLM.
        status, classify_body = _post_engine_o(
            "/classify_predicate",
            {
                "query": "What's the schema of customers_gold?",
                "subject_uri": _TEST_SUBJECT_URI,
                "subject_reasoning": "Synthetic test invocation",
                "entitled_domains": [],
                "domain": "DATA_ENGINEERING",
                "compatible_verb_iris": compat_verbs,
            },
        )
        assert status == 200
        enum_verbs = classify_body.get("candidate_verb_iris") or []
        assert _SYNTHETIC_VERB_IRI not in enum_verbs, (
            f"\n  CONJUNCTIVE-READ INVARIANT VIOLATION (case #2).\n"
            f"  A Neo4j-only synthetic edge entered the LLM's constrained enum.\n"
            f"  Verb: {_SYNTHETIC_VERB_IRI}\n"
            f"  Enum: {enum_verbs}\n"
            f"  Reasoning: {classify_body.get('reasoning')!r}\n"
            f"\n  This is the load-bearing safety property the gateway v0.2\n"
            f"  rollback decision rests on (ADR-0006 §Addendum 2026-06-13).\n"
            f"  If a Neo4j-only verb can dispatch, half-written substrate\n"
            f"  becomes routable and the safety argument collapses.\n"
            f"\n  Likely cause: the fabrication-fallback at\n"
            f"  agent_fleet/ontology_service/main.py was re-introduced.\n"
            f"  Check the §Decision section of the addendum and the\n"
            f"  ADR §Indicators-for-revisiting entry on single-store\n"
            f"  dispatch."
        )
    finally:
        _delete_neo4j_synthetic_edge(neo4j_driver, tool_urn=tool_urn)


def test_weaviate_only_row_does_not_reach_llm_enum(neo4j_driver, weaviate_client):
    """Case #3: Weaviate has the row, Neo4j has no edge. The verb is
    filtered out before the enum because it's not in the compat
    whitelist that Cypher produces."""
    tool_urn = f"urn:li:mlModel:(...,conjunctive_probe_w_only,PROD)_{uuid.uuid4().hex[:8]}"
    inserted_uuid = None
    try:
        inserted_uuid = _insert_weaviate_synthetic_row(weaviate_client, tool_urn=tool_urn)

        # Cypher side: verb should NOT appear in compat (Neo4j doesn't have it).
        status, compat_body = _post_engine_o(
            "/find_compatible_verbs",
            {"subject_uri": _TEST_SUBJECT_URI, "max_hops": 5, "entitled_domains": []},
        )
        assert status == 200
        compat_verbs = [v.get("verb_iri") for v in (compat_body.get("verbs") or [])]
        assert _SYNTHETIC_VERB_IRI not in compat_verbs, (
            f"Sanity check failed: Weaviate-only synthetic row should NOT "
            f"appear in /find_compatible_verbs. Got: {compat_verbs}"
        )

        # /classify_predicate: enum MUST NOT include the synthetic verb,
        # even though it's in Weaviate's hybrid search results — the
        # compat filter drops it.
        status, classify_body = _post_engine_o(
            "/classify_predicate",
            {
                "query": "What's the conjunctive read invariant probe verb?",
                "subject_uri": _TEST_SUBJECT_URI,
                "subject_reasoning": "Synthetic test invocation",
                "entitled_domains": [],
                "domain": "DATA_ENGINEERING",
                "compatible_verb_iris": compat_verbs,
            },
        )
        assert status == 200
        enum_verbs = classify_body.get("candidate_verb_iris") or []
        assert _SYNTHETIC_VERB_IRI not in enum_verbs, (
            f"\n  CONJUNCTIVE-READ INVARIANT VIOLATION (case #3).\n"
            f"  A Weaviate-only synthetic row entered the LLM's constrained enum.\n"
            f"  Verb: {_SYNTHETIC_VERB_IRI}\n"
            f"  Enum: {enum_verbs}\n"
            f"\n  This is the load-bearing safety property the gateway v0.2\n"
            f"  rollback decision rests on (ADR-0006 §Addendum 2026-06-13).\n"
            f"  Most likely cause: a future change to /classify_predicate\n"
            f"  made the compat filter bypassable, or the filter was\n"
            f"  removed entirely."
        )
    finally:
        if inserted_uuid is not None:
            _delete_weaviate_synthetic_row(weaviate_client, uid=inserted_uuid)


def test_both_present_does_reach_llm_enum(neo4j_driver, weaviate_client):
    """Control case: when BOTH stores agree, the verb DOES reach the
    LLM's enum. The invariant should admit valid registrations, not
    reject them too — this test catches the failure mode where the
    filter becomes overly strict and blocks correctly-registered verbs.
    """
    tool_urn = f"urn:li:mlModel:(...,conjunctive_probe_both,PROD)_{uuid.uuid4().hex[:8]}"
    inserted_uuid = None
    try:
        _insert_neo4j_synthetic_edge(neo4j_driver, tool_urn=tool_urn)
        inserted_uuid = _insert_weaviate_synthetic_row(weaviate_client, tool_urn=tool_urn)

        status, compat_body = _post_engine_o(
            "/find_compatible_verbs",
            {"subject_uri": _TEST_SUBJECT_URI, "max_hops": 5, "entitled_domains": []},
        )
        assert status == 200
        compat_verbs = [v.get("verb_iri") for v in (compat_body.get("verbs") or [])]
        assert _SYNTHETIC_VERB_IRI in compat_verbs

        status, classify_body = _post_engine_o(
            "/classify_predicate",
            {
                "query": "What's the conjunctive read invariant probe verb?",
                "subject_uri": _TEST_SUBJECT_URI,
                "subject_reasoning": "Synthetic test invocation",
                "entitled_domains": [],
                "domain": "DATA_ENGINEERING",
                "compatible_verb_iris": compat_verbs,
            },
        )
        assert status == 200
        enum_verbs = classify_body.get("candidate_verb_iris") or []
        assert _SYNTHETIC_VERB_IRI in enum_verbs, (
            f"\n  Control case FAILURE: a verb present in BOTH stores did NOT "
            f"reach the LLM's enum.\n"
            f"  Verb: {_SYNTHETIC_VERB_IRI}\n"
            f"  Compat (Neo4j): {compat_verbs}\n"
            f"  Enum (post-filter): {enum_verbs}\n"
            f"\n  The conjunctive-read invariant must ADMIT valid registrations.\n"
            f"  If this turns red, the filter has become too strict — likely\n"
            f"  the predicate hybrid search is dropping the row, or a recent\n"
            f"  refactor broke the (verb_iri, input_uri) deterministic UUID."
        )
    finally:
        _delete_neo4j_synthetic_edge(neo4j_driver, tool_urn=tool_urn)
        if inserted_uuid is not None:
            _delete_weaviate_synthetic_row(weaviate_client, uid=inserted_uuid)
