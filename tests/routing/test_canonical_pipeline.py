"""Canonical pipeline integration tests — guard the BUILD-state.

`test_substrate_invariants.py` guards the END state of the substrate
(no pseudo-classes, no phantoms, correct verb typings, no compact
duplicates for migrated subjects). This file guards the **pipeline
that builds that state**: MinIO → Dagster ``ingest_ontology_job`` →
Jena named graph + Weaviate OntologyClass sync.

The pair is what makes the canonical claim defensible. Invariants
alone can stay green while the pipeline silently breaks — you only
find out the next time you try to rebuild. These tests fail FAST
when:

  - The pipeline regresses (explicit_domain override breaks; rdflib
    extract misses classes; Weaviate sync writes wrong properties)
  - A required TTL goes missing from MinIO
  - Jena/Weaviate auth or schema drifts

Marked as integration: they hit real MinIO + Dagster + Jena +
Weaviate, and take ~3-5 min per test (job queue + worker
spin-up + rdflib parse + GSP PUT + Weaviate batch insert). CI should
run them on a sandbox-up cron, not per-commit.

Skip when ``CANONICAL_PIPELINE_TEST_ENABLED`` is unset, so local
unit-test runs aren't blocked on cluster access.

Usage (sandbox cluster up, port-forwards established):

  CANONICAL_PIPELINE_TEST_ENABLED=1 \
  DAGSTER_GRAPHQL_URL=http://localhost:13000/graphql \
  MINIO_ENDPOINT=http://localhost:19000 \
  WEAVIATE_URL=http://localhost:18080 \
  JENA_URL=http://localhost:13030 \
  AWS_ACCESS_KEY_ID=minio-sandbox \
  AWS_SECRET_ACCESS_KEY=minio-sandbox-secret \
  pytest tests/routing/test_canonical_pipeline.py -v
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

import pytest

# Skip the whole module if integration mode isn't enabled.
if not os.environ.get("CANONICAL_PIPELINE_TEST_ENABLED"):
    pytest.skip(
        "set CANONICAL_PIPELINE_TEST_ENABLED=1 to run canonical pipeline tests",
        allow_module_level=True,
    )

try:
    import boto3
    import weaviate
    from weaviate.util import generate_uuid5
except ImportError as e:
    pytest.skip(f"missing integration dep: {e}", allow_module_level=True)


DAGSTER_GRAPHQL_URL = os.environ.get(
    "DAGSTER_GRAPHQL_URL", "http://localhost:13000/graphql"
)
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:19000")
WEAVIATE_HTTP_HOST = os.environ.get("WEAVIATE_HTTP_HOST", "localhost")
WEAVIATE_HTTP_PORT = int(os.environ.get("WEAVIATE_HTTP_PORT", "18080"))
WEAVIATE_GRPC_HOST = os.environ.get("WEAVIATE_GRPC_HOST", "localhost")
WEAVIATE_GRPC_PORT = int(os.environ.get("WEAVIATE_GRPC_PORT", "50051"))
JENA_URL = os.environ.get("JENA_URL", "http://localhost:13030")
JENA_DS = os.environ.get("JENA_DS", "ds")
JENA_USER = os.environ.get("JENA_USERNAME", "admin")
JENA_PASS = os.environ.get("JENA_PASSWORD", "")

ONTOLOGIES_BUCKET = "ontologies"

# Ingest job takes ~60-90s end-to-end. Allow generous slack for queue
# back-pressure (the AITool sensor sometimes saturates the daemon).
INGEST_TIMEOUT_S = 300

PROBE_URI = "http://invincible-agent/probe#CanonicalPipelineProbe"
PROBE_S3_KEY = "PROBE/test_canonical_pipeline_probe.ttl"
PROBE_TTL = """@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix probe: <http://invincible-agent/probe#> .

<http://internal/probe> a owl:Ontology ;
    rdfs:label "Canonical pipeline test probe" .

probe:CanonicalPipelineProbe a owl:Class ;
    rdfs:label "Canonical Pipeline Probe" ;
    rdfs:comment "Class used by test_canonical_pipeline.py to verify the MinIO -> Dagster -> Jena -> Weaviate pipeline still works end-to-end. Safe to delete." .
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        DAGSTER_GRAPHQL_URL, data=body,
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def _launch_ingest(file_url: str, *, domain: str | None) -> str:
    """Fire ingest_ontology_job and return the runId."""
    config = {
        "ops": {
            "ingest_ontology_to_jena": {
                "config": {"file_url": file_url}
            }
        }
    }
    if domain:
        # Use extra_metadata path so the explicit-domain override is exercised.
        config["ops"]["ingest_ontology_to_jena"]["config"]["extra_metadata"] = {
            "domain": domain
        }
    mutation = """
    mutation Launch($params: ExecutionParams!) {
      launchRun(executionParams: $params) {
        __typename
        ... on LaunchRunSuccess { run { runId status } }
        ... on PythonError { message }
        ... on RunConfigValidationInvalid { errors { message } }
      }
    }
    """
    resp = _gql(mutation, {
        "params": {
            "selector": {
                "repositoryLocationName": "doc-tools",
                "repositoryName": "__repository__",
                "jobName": "ingest_ontology_job",
            },
            "runConfigData": json.dumps(config),
            "mode": "default",
        }
    })
    typename = resp.get("data", {}).get("launchRun", {}).get("__typename")
    if typename != "LaunchRunSuccess":
        pytest.fail(f"ingest launch failed: {resp}")
    return resp["data"]["launchRun"]["run"]["runId"]


def _wait_run(run_id: str, timeout_s: int = INGEST_TIMEOUT_S) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = _gql(
            f'{{ runOrError(runId: "{run_id}") {{ __typename ... on Run {{ status }} }} }}'
        )
        status = resp.get("data", {}).get("runOrError", {}).get("status")
        if status in ("SUCCESS", "FAILURE", "CANCELED"):
            return status
        time.sleep(5)
    return "TIMEOUT"


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )


def _weaviate_client():
    return weaviate.connect_to_custom(
        http_host=WEAVIATE_HTTP_HOST,
        http_port=WEAVIATE_HTTP_PORT,
        http_secure=False,
        grpc_host=WEAVIATE_GRPC_HOST,
        grpc_port=WEAVIATE_GRPC_PORT,
        grpc_secure=False,
    )


def _weaviate_get_uri(uri: str) -> dict | None:
    client = _weaviate_client()
    try:
        col = client.collections.get("OntologyClass")
        uuid = generate_uuid5(uri)
        if not col.data.exists(uuid):
            return None
        obj = col.query.fetch_object_by_id(uuid)
        return dict(obj.properties) if obj else None
    finally:
        client.close()


def _jena_triple_count(graph_uri: str) -> int:
    """COUNT triples in a Jena named graph via SPARQL."""
    query = f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
    url = f"{JENA_URL}/{JENA_DS}/sparql"
    body = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json",
        },
    )
    import base64
    if JENA_USER:
        creds = base64.b64encode(f"{JENA_USER}:{JENA_PASS}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    data = json.loads(urllib.request.urlopen(req, timeout=15).read())
    return int(data["results"]["bindings"][0]["n"]["value"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_explicit_domain_override_lands_at_intended_domain():
    """Pipeline guard: explicit ``extra_metadata.domain`` is honored.

    The probe is uploaded to ``s3://ontologies/PROBE/...`` (path-derived
    domain = ``PROBE``) but ingested with explicit ``domain=MAINTENANCE``.
    Class must appear in Weaviate at domain=MAINTENANCE, not PROBE.

    This is the regression guard for doc-tools 252c36f: a future
    refactor that accidentally drops the override would land mro
    extensions at the wrong domain (the bug we shipped to fix).
    """
    s3 = _s3_client()
    # Upload + verify
    s3.put_object(Bucket=ONTOLOGIES_BUCKET, Key=PROBE_S3_KEY, Body=PROBE_TTL.encode())
    try:
        run_id = _launch_ingest(f"s3://{ONTOLOGIES_BUCKET}/{PROBE_S3_KEY}",
                                domain="MAINTENANCE")
        status = _wait_run(run_id)
        assert status == "SUCCESS", f"ingest did not succeed: status={status}"

        props = _weaviate_get_uri(PROBE_URI)
        assert props is not None, (
            f"probe class {PROBE_URI} not found in Weaviate after ingest. "
            f"Pipeline either failed silently or Weaviate sync regressed."
        )
        assert props.get("domain") == "MAINTENANCE", (
            f"probe landed at domain={props.get('domain')!r}, expected "
            f"MAINTENANCE. The explicit-domain override regressed."
        )
    finally:
        # Cleanup
        client = _weaviate_client()
        try:
            col = client.collections.get("OntologyClass")
            uuid = generate_uuid5(PROBE_URI)
            if col.data.exists(uuid):
                col.data.delete_by_id(uuid)
        finally:
            client.close()
        try:
            s3.delete_object(Bucket=ONTOLOGIES_BUCKET, Key=PROBE_S3_KEY)
        except Exception:
            pass


def test_path_derived_domain_default_still_works():
    """Pipeline guard: backward compatibility for the path-derived
    default (no explicit ``extra_metadata.domain``).

    Existing sensor-fired ingestions rely on it. A regression that
    breaks the fallback would silently take down auto-sensed
    ontology ingests.
    """
    s3 = _s3_client()
    s3.put_object(Bucket=ONTOLOGIES_BUCKET, Key=PROBE_S3_KEY, Body=PROBE_TTL.encode())
    try:
        run_id = _launch_ingest(f"s3://{ONTOLOGIES_BUCKET}/{PROBE_S3_KEY}",
                                domain=None)
        status = _wait_run(run_id)
        assert status == "SUCCESS", f"ingest did not succeed: status={status}"

        props = _weaviate_get_uri(PROBE_URI)
        assert props is not None
        assert props.get("domain") == "PROBE", (
            f"path-derived default broke. Expected domain=PROBE "
            f"(from s3 path 'PROBE/...'), got {props.get('domain')!r}."
        )
    finally:
        client = _weaviate_client()
        try:
            col = client.collections.get("OntologyClass")
            uuid = generate_uuid5(PROBE_URI)
            if col.data.exists(uuid):
                col.data.delete_by_id(uuid)
        finally:
            client.close()
        try:
            s3.delete_object(Bucket=ONTOLOGIES_BUCKET, Key=PROBE_S3_KEY)
        except Exception:
            pass


@pytest.mark.parametrize(
    "ttl_key,domain,expected_classes",
    [
        (
            "maintenance/mro_extension.ttl",
            "MAINTENANCE",
            [
                "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/TechnicalManual",
                "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Diagram",
                "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/ProcedureStep",
            ],
        ),
        (
            "maintenance/maintenance_extension.ttl",
            "MAINTENANCE",
            [
                "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/WorkInstruction",
                "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Procedure",
                "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Symptom",
                "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Equipment",
            ],
        ),
    ],
    ids=["mro_extension", "maintenance_extension"],
)
def test_maintenance_ttls_round_trip(ttl_key: str, domain: str, expected_classes: list[str]):
    """Pipeline guard: the load-bearing TTLs ingest correctly.

    Re-ingest the canonical maintenance TTLs and assert each declared
    class appears in Weaviate at the expected full IRI + domain.

    These two TTLs (committed in doc-tools 252c36f) are what makes the
    rotor + manuals routing matrix path canonical. If either fails to
    round-trip, the rotor/manuals routing breaks the next time the
    substrate is rebuilt from MinIO.

    NOTE: this test does NOT clean up the Weaviate state because the
    same classes are the load-bearing substrate the routing matrix
    depends on. The Weaviate UPSERT (deterministic UUID) is idempotent,
    so re-running the test just re-writes the same record.
    """
    s3 = _s3_client()
    # Verify the TTL is in MinIO at the expected path
    try:
        s3.head_object(Bucket=ONTOLOGIES_BUCKET, Key=ttl_key)
    except Exception as e:
        pytest.fail(f"TTL {ttl_key} not in MinIO: {e}")

    # Fire ingest (no explicit domain — path-derived from 'maintenance/' is MAINTENANCE)
    run_id = _launch_ingest(f"s3://{ONTOLOGIES_BUCKET}/{ttl_key}", domain=None)
    status = _wait_run(run_id)
    assert status == "SUCCESS", f"ingest of {ttl_key} failed: status={status}"

    # Assert each expected class is in Weaviate at the right domain
    missing = []
    wrong_domain = []
    for uri in expected_classes:
        props = _weaviate_get_uri(uri)
        if props is None:
            missing.append(uri)
        elif props.get("domain") != domain:
            wrong_domain.append((uri, props.get("domain")))

    assert not missing, f"Classes missing from Weaviate after ingest: {missing}"
    assert not wrong_domain, (
        f"Classes at wrong domain (expected {domain}): {wrong_domain}"
    )


def test_jena_named_graph_populated_by_ingest():
    """Pipeline guard: ingest produces non-empty Jena named graphs.

    The Jena named graph is the canonical record (Weaviate is the
    runtime cache). If the Jena PUT silently regresses (e.g., bad
    GSP endpoint, missing auth), Weaviate might still be populated
    by some other path but the canonical record is gone — exactly
    the band-aid pattern we just eliminated.
    """
    expected_graphs = {
        "http://internal/maintenance",  # both mro/maintenance extensions
    }
    for graph in expected_graphs:
        n = _jena_triple_count(graph)
        assert n > 0, (
            f"Jena named graph {graph} is empty. Expected populated by "
            f"the canonical pipeline. Likely cause: GSP PUT regressed "
            f"or the wrong graph URI was used."
        )
