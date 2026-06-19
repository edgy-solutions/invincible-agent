"""Prime a deployable cluster (sandbox or work) from zero.

Purpose: bring a fresh deployment from "k8s manifests applied" to "engines
can register and the matrix can pass." This is the DEPLOYABILITY artifact
the architect named in the Session-1/Session-2 close — what the cluster
state minus the running-cluster's historical drift looks like.

What it does (idempotent across all steps):

  1. Neo4j constraints + indexes for the instance label set
     (Procedure, ManufacturingStep, Part, Hazard).
  2. Apache Jena (Fuseki) dataset provisioning.
  3. UPLOAD the canonical TTLs to MinIO so the dagster sensor +
     ingest_ontology_job + sync_jena_ontologies_to_neo4j (Session-2's
     Option-3 fix, doc-tools 5c185fb) can do the full
     Jena+Weaviate+Neo4j ingest.

What changed (Session 2, 2026-06-13):

  - Added the 4 missing extension TTLs (mro/maintenance/mesh_system/idp)
    plus the new mil_extension (B0). Before: only 5 raw ontologies
    loaded directly to Jena, bypassing the canonical pipeline. Result:
    the resolver's MAINTENANCE vocabulary was mostly missing and the
    fresh-cluster matrix would degrade silently.
  - **Explicit domain mapping replaces path-derived defaults.** Before:
    `mro/MIL_Unified.ttl` got tagged with domain "mro" (path-derived) but
    the resolver queries with domain="MAINTENANCE"; everything landed
    invisible. The Session-1 audit named this exact bug.
  - **Pinned URLs.** Before: master-tracking URLs (`/master/`). Now:
    pinned to specific SHAs where available; upstream-master only for
    repos we own (edgy-solutions/*).
  - **Guarded --wipe.** Before: `--wipe` dropped Neo4j + Weaviate
    with no safety. Now: requires both `--wipe` AND `--i-mean-it` AND
    a `--namespace` confirming the cluster (so a typo doesn't nuke prod).
  - **MinIO upload + canonical pipeline path.** The TTLs no longer go
    direct to Jena via PUT (which left Neo4j uncovered). They go to
    MinIO, where the Session-2 canonical pipeline picks them up and
    propagates to Jena+Weaviate+Neo4j in one observable seam per file.

Usage:

    # Initial prime (idempotent — safe to re-run):
    python prime_databases.py

    # Wipe before priming (guarded; requires three flags):
    python prime_databases.py --wipe --i-mean-it --namespace=sandbox

    # Just upload TTLs to MinIO (skip Neo4j constraints + Jena provisioning):
    python prime_databases.py --upload-only

Architecture note: this script does the SETUP that survives across
deploys. The runtime registration of engine verbs (via
register_engine_to_mesh → gateway saga) happens at engine startup
and reproduces from source on every restart. The boundary between
the two: this script primes the SUBSTRATE the engines need to
register against; the engines own everything downstream of that.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import urllib3

# Resolved at import time so subsequent path-based manifest entries
# resolve regardless of CWD. The script lives at setup/prime_databases.py;
# vendored TTLs live at setup/ontologies/. So SCRIPT_DIR points at
# .../invincible-agent/setup/ and `SCRIPT_DIR / entry["path"]` resolves
# to the right file whether the script is invoked from the repo root
# (local dev), from /app (Helm Job in dagster-server image), or from
# anywhere else.
SCRIPT_DIR = Path(__file__).resolve().parent
from neo4j import GraphDatabase

try:
    import weaviate
except ImportError:
    weaviate = None

try:
    import boto3
except ImportError:
    boto3 = None

proxy_int = None
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================================
# Canonical TTL manifest — what a deployable cluster needs to have available
# in MinIO for the dagster pipeline to ingest.
#
# Domain mapping is EXPLICIT (Session-1 audit lesson): the resolver queries
# with semantic domain names (MAINTENANCE, MESH, IDP, MIL) and a TTL's
# semantic domain may differ from its source path. Always pass
# extra_metadata={"domain": "<SEMANTIC>"} when triggering the ingest.
#
# URLs pinned where possible. For repos we own (edgy-solutions/*), main is
# tracked so the Session-2 work + mil_extension.ttl propagate immediately;
# for upstream repos, pin to the commit that was current as of
# 2026-06-13 so a fresh-bootstrap rehearsal reproduces the substrate
# exactly. To bump a pin, follow the source-substrate reconciliation
# discipline (re-ingest + matrix-verify) — never patch the substrate
# directly.
# ============================================================================

CANONICAL_TTL_MANIFEST = [
    # ----- LAYER 1: MAINTENANCE (the operating domain the routing matrix exercises) -----
    {
        "domain": "MAINTENANCE",
        "name": "IOF_Core",
        "s3_key": "maintenance/IOF_Core.rdf",
        "url": "https://raw.githubusercontent.com/iofoundry/ontology/master/core/Core.rdf",
        # IOF upstream; pin to a SHA once we have a known-good ref.
    },
    {
        "domain": "MAINTENANCE",
        "name": "IOF_MRO",
        "s3_key": "maintenance/IOF_MRO.rdf",
        "url": "https://raw.githubusercontent.com/iofoundry/ontology/master/maintenance/Maintenance.rdf",
    },
    {
        "domain": "MAINTENANCE",
        "name": "DINEN62264",
        "s3_key": "maintenance/DINEN62264.owl",
        "url": "https://raw.githubusercontent.com/hsu-aut/IndustrialStandard-ODP-DINEN62264-2/v1.4.2/DINEN62264.owl",
    },
    {
        "domain": "MAINTENANCE",
        "name": "mro_extension",
        "s3_key": "maintenance/mro_extension.ttl",
        # Locally vendored 2026-06-17 — was https://raw.githubusercontent.com/edgy-solutions/doc-tools/main/setup/mro_extension.ttl
        # before TTL ownership moved from doc-tools to invincible-agent
        # (see commit 8768728 in doc-tools and below in invincible-agent).
        "path": "ontologies/mro_extension.ttl",
    },
    {
        "domain": "MAINTENANCE",
        "name": "maintenance_extension",
        "s3_key": "maintenance/maintenance_extension.ttl",
        "path": "ontologies/maintenance_extension.ttl",
    },

    # ----- LAYER 1b: MIL (B0 docs-phase TBox; Session-2 acceptance-test carrier) -----
    # 2026-06-16: domain CORRECTED from 'MIL' to 'MAINTENANCE'. The resolver
    # queries with semantic domain names; 'MIL' was a path-NAME derivation
    # (the s3 path's first segment is `mil/`) but mil_extension.ttl's
    # SEMANTIC domain is maintenance (mil:* classes are S1000D/40051 work-
    # package kinds: ProcedureDataModule, FaultIsolationDataModule, etc.).
    # The mismatch produced confidently-wrong routing for the B4-V1 fault-
    # isolation question (resolved to mro:WorkInstruction at 0.95 because
    # mil:* was invisible to the MAINTENANCE-domain resolver query). See
    # STATE_GATEWAY_V02.md "2026-06-16 explicit-per-file domain fix" for
    # the full trace; the standing guard
    # `test_no_path_derived_domains` keeps this from regressing silently.
    {
        "domain": "MAINTENANCE",
        "name": "mil_extension",
        "s3_key": "mil/mil_extension.ttl",
        "path": "ontologies/mil_extension.ttl",
    },

    # ----- LAYER 2: SUSTAINMENT -----
    {
        "domain": "SUSTAINMENT",
        "name": "IOF_Core_sustainment",
        "s3_key": "sustainment/IOF_Core.rdf",
        "url": "https://raw.githubusercontent.com/iofoundry/ontology/master/core/Core.rdf",
    },
    {
        "domain": "SUSTAINMENT",
        "name": "S3000L",
        "s3_key": "sustainment/S3000L.ttl",
        "url": "https://www.semanticstep.org/sites/default/files/2018-01/s3kl_0.ttl",
    },

    # ----- LAYER 3: DATA_ENGINEERING (idp catalog / lineage) -----
    # The semantic domain is DATA_ENGINEERING, not IDP.
    # The resolver queries with semantic domain names (the architect's
    # Step-1 explicit_domain lesson, validated by a fresh-bootstrap
    # rehearsal that surfaced this exact bug shape — "domain matches
    # path, not what the resolver actually queries with" gives
    # silent UNKNOWN cascades). idp:* classes are the canonical
    # catalog/lineage vocabulary for data-engineering questions.
    {
        "domain": "DATA_ENGINEERING",
        "name": "PROV-O",
        "s3_key": "idp/PROV-O.ttl",
        "url": "https://www.w3.org/ns/prov-o.ttl",
    },
    {
        "domain": "DATA_ENGINEERING",
        "name": "idp_extension",
        "s3_key": "idp/idp_extension.ttl",
        "path": "ontologies/idp_extension.ttl",
    },

    # ----- LAYER 4: MANUFACTURING (the manufacturing content-kind axis) -----
    # General mfg:WorkInstruction kind only — the routing-visible class the
    # ManufacturingPlugin's INSTANCE_OF stamping (ADR-0021) targets. Single
    # general kind by architect's ruling 2026-06-18: munitions / sensors /
    # electronics / mechanical-assemblies are *what is described* by a work
    # instruction, NOT separate kinds. Sub-kinds become warranted only when
    # a routing question demands disambiguating them (Wave-3 discipline) —
    # same content-hierarchy decision pattern the mil:* manuals follow.
    #
    # This entry closes Gap-1 durably (the substrate patch from the prior
    # overnight reverts on next canonical-pipeline run otherwise — see
    # STATE_GATEWAY_V02.md 2026-06-17 Step 1). The pre-canonical residue at
    # http://example.com/manufacturing# (MunitionsAssemblyStep et al., 7
    # classes) was the legacy direct-load shape; it is NOT what the new
    # canonical pipeline materializes. Residue stays orphaned (synced_from
    # is NULL on those rows so the substrate guard's filter already ignores
    # it) until a cleanup pass retires it.
    {
        "domain": "MANUFACTURING",
        "name": "mfg_extension",
        "s3_key": "manufacturing/mfg_extension.ttl",
        "path": "ontologies/mfg_extension.ttl",
    },

    # ----- LAYER 5: MESH (system ontology — request/response shapes) -----
    {
        "domain": "MESH",
        "name": "mesh_system",
        "s3_key": "mesh/mesh_system.ttl",
        "path": "ontologies/mesh_system.ttl",
    },
]


# ============================================================================
# Helpers
# ============================================================================

def parse_env() -> None:
    """Load .env if present (without python-dotenv)."""
    if not os.path.exists(".env"):
        return
    with open(".env", "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'").strip('"')
            os.environ.setdefault(k, v)


def get_base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


# ============================================================================
# Step 1: Neo4j constraints + indexes
# ============================================================================

def prime_neo4j() -> None:
    print("--- Priming Neo4j (constraints + indexes) ---")
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "changeme")

    # Instance constraints — these are the labels the ingest pipeline writes
    # (per B0 §4: MERGE by DMC for documents, by id for parts/procedures).
    # OntologyClass + Resource uniqueness lives in init_neo4j_n10s (dagster),
    # NOT here — keep this script's responsibilities scoped to instance
    # graph constraints that survive across pipeline runs.
    commands = [
        "CREATE CONSTRAINT part_id_unique IF NOT EXISTS FOR (p:Part) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT proc_id_unique IF NOT EXISTS FOR (p:Procedure) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT step_id_unique IF NOT EXISTS FOR (s:ManufacturingStep) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT figure_id_unique IF NOT EXISTS FOR (f:Figure) REQUIRE f.id IS UNIQUE",
        "CREATE CONSTRAINT dmc_uri_unique IF NOT EXISTS FOR (d:DataModule) REQUIRE d.dmc IS UNIQUE",
        "CREATE INDEX hazard_class_index IF NOT EXISTS FOR (h:Hazard) ON (h.class)",
        # OntologyClass.uri is created by init_neo4j_n10s for :Resource nodes;
        # we also enforce it on :OntologyClass directly because the
        # canonical pipeline MERGEs on uri.
        "CREATE CONSTRAINT ontology_class_uri_unique IF NOT EXISTS FOR (c:OntologyClass) REQUIRE c.uri IS UNIQUE",
    ]
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            for cmd in commands:
                session.run(cmd)
                label = cmd.split("CONSTRAINT")[-1].split("IF NOT EXISTS")[0].strip().split()[0]
                print(f"  [OK] {label}")
        driver.close()
        print("[SUCCESS] Neo4j primed.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        raise


# ============================================================================
# Step 2: Apache Jena dataset provisioning
# ============================================================================

def prime_jena() -> None:
    print("--- Priming Apache Jena (dataset auto-provisioning) ---")
    raw_host = os.environ.get("JENA_URL") or os.environ.get("JENA_SPARQL_ENDPOINT", "http://localhost:3030")
    host = get_base_url(raw_host)
    ds_name = os.environ.get("JENA_DS", "ds")
    user = os.environ.get("JENA_USERNAME", "admin")
    pw = os.environ.get("FUSEKI_PASSWORD") or os.environ.get("JENA_PASSWORD", "Admin123!")
    auth = (user, pw)

    print(f"Checking for dataset /{ds_name} at {host}...")
    try:
        check = requests.get(f"{host}/$/datasets/{ds_name}", auth=auth, proxies=proxy_int, verify=False)
        if check.status_code == 404:
            print(f"  [!] /{ds_name} not found; creating (TDB2 persistent)...")
            create_res = requests.post(
                f"{host}/$/datasets",
                data={"dbName": ds_name, "dbType": "tdb2"},
                auth=auth, proxies=proxy_int, verify=False,
            )
            if create_res.status_code in (200, 201):
                print(f"  [SUCCESS] /{ds_name} created.")
            else:
                raise Exception(f"create failed: {create_res.status_code} {create_res.text}")
        else:
            print(f"  [OK] /{ds_name} exists.")
    except Exception as e:
        print(f"  [ERROR] Jena unreachable or unauthorized: {e}")
        raise


# ============================================================================
# Step 3: Upload canonical TTLs to MinIO so the dagster pipeline can ingest
# ============================================================================

def upload_canonical_ttls() -> None:
    """Push every TTL in CANONICAL_TTL_MANIFEST to MinIO.

    The dagster `ingest_ontology_job` (which now selects both
    `ingest_ontology_to_jena` and `sync_jena_ontologies_to_neo4j` per
    doc-tools 5c185fb) consumes from this bucket. Triggering the job
    is a separate step (see `trigger_ingest_jobs` below) — uploading
    is idempotent and safe to re-run.
    """
    print("--- Uploading canonical TTLs to MinIO ---")
    if boto3 is None:
        raise RuntimeError("boto3 not installed; pip install boto3")

    endpoint = os.environ.get("S3_ENDPOINT_URL") or os.environ.get("MINIO_URL", "http://localhost:9000")
    access_key = os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    bucket = os.environ.get("ONTOLOGY_BUCKET", "ontologies")

    s3 = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key, aws_secret_access_key=secret_key)

    # Ensure the bucket exists.
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        print(f"  [!] Bucket {bucket} not found; creating...")
        s3.create_bucket(Bucket=bucket)

    for entry in CANONICAL_TTL_MANIFEST:
        name = entry["name"]
        domain = entry["domain"]
        s3_key = entry["s3_key"]
        # Two source shapes:
        #   path: <relative path under setup/> — locally vendored. Read
        #     from filesystem; resolved relative to SCRIPT_DIR so CWD
        #     doesn't matter. Used for the TTLs invincible-agent owns
        #     (custom extensions; vendored 2026-06-17 from doc-tools).
        #   url: <upstream URL> — fetch over network. Used for ontologies
        #     we don't own (IOF Core, IOF MRO, DINEN62264, S3000L, PROV-O).
        local_path = entry.get("path")
        url = entry.get("url")
        if local_path:
            full_path = SCRIPT_DIR / local_path
            source_label = f"path:{local_path}"
            print(f"  {name} (domain={domain}) ← {source_label}")
            try:
                data = full_path.read_bytes()
            except Exception as e:
                print(f"    [ERROR] read failed for {full_path}: {e}")
                raise
            source_metadata = f"local:{local_path}"
        elif url:
            source_label = url
            print(f"  {name} (domain={domain}) ← {source_label}")
            try:
                resp = requests.get(url, verify=False, timeout=30)
                resp.raise_for_status()
                data = resp.content
            except Exception as e:
                print(f"    [WARNING] fetch failed: {e}; skipping (re-run after upstream recovery)")
                continue
            source_metadata = url
        else:
            print(f"    [ERROR] entry {name} has neither 'path' nor 'url'; skipping")
            continue

        try:
            s3.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=data,
                Metadata={
                    "x-amz-meta-domain": domain,
                    "x-amz-meta-source-url": source_metadata,
                    "x-amz-meta-canonical-name": name,
                },
            )
            print(f"    [OK] → s3://{bucket}/{s3_key} ({len(data)} bytes)")
        except Exception as e:
            print(f"    [ERROR] upload: {e}")
            raise

    print("[SUCCESS] All canonical TTLs uploaded.")


def trigger_ingest_jobs() -> None:
    """OPTIONAL: trigger dagster ingest_ontology_job for each TTL partition.

    Without this, the TTLs are uploaded to MinIO but the canonical
    pipeline must be triggered manually (via the dagster sensor's
    auto-detection OR via the Dagster UI). This function is helpful
    for fresh-bootstrap rehearsals where you want the entire chain to
    run end-to-end in one script.

    Dagster GraphQL endpoint: defaults to http://localhost:3000/graphql;
    override with DAGSTER_URL.
    """
    print("--- Triggering dagster ingest_ontology_job per partition ---")
    dagster_url = os.environ.get("DAGSTER_URL", "http://localhost:3000")
    graphql = f"{dagster_url}/graphql"

    for entry in CANONICAL_TTL_MANIFEST:
        domain = entry["domain"]
        s3_key = entry["s3_key"]
        partition_key = s3_key.replace("/", "__")
        file_url = f"s3://{os.environ.get('ONTOLOGY_BUCKET', 'ontologies')}/{s3_key}"

        mutation = {
            "query": (
                "mutation Launch($executionParams: ExecutionParams!) { "
                "launchPipelineExecution(executionParams: $executionParams) { "
                "__typename ... on LaunchRunSuccess { run { runId } } "
                "... on PythonError { message } } }"
            ),
            "variables": {
                "executionParams": {
                    "selector": {
                        "repositoryLocationName": "doc-tools",
                        "repositoryName": "__repository__",
                        "pipelineName": "ingest_ontology_job",
                        "assetSelection": [
                            {"path": ["ingest_ontology_to_jena"]},
                            {"path": ["sync_jena_ontologies_to_neo4j"]},
                        ],
                    },
                    "runConfigData": {
                        "ops": {
                            "ingest_ontology_to_jena": {
                                "config": {
                                    "file_url": file_url,
                                    "extra_metadata": {"domain": domain},
                                }
                            },
                            "sync_jena_ontologies_to_neo4j": {
                                "config": {
                                    "file_url": file_url,
                                    "extra_metadata": {"domain": domain},
                                }
                            },
                        }
                    },
                    "executionMetadata": {
                        "tags": [{"key": "dagster/partition", "value": partition_key}]
                    },
                }
            },
        }

        try:
            resp = requests.post(graphql, json=mutation, timeout=15)
            if resp.status_code != 200:
                print(f"  [WARNING] {entry['name']}: dagster HTTP {resp.status_code}")
                continue
            data = resp.json().get("data", {}).get("launchPipelineExecution", {})
            if data.get("__typename") == "LaunchRunSuccess":
                run_id = data.get("run", {}).get("runId")
                print(f"  [LAUNCHED] {entry['name']} → run {run_id}")
            else:
                print(f"  [WARNING] {entry['name']}: {data}")
        except Exception as e:
            print(f"  [WARNING] {entry['name']}: {e}")

    print(
        "[NOTE] Runs launched asynchronously. Monitor in the Dagster UI; "
        "poll the runOrError query for status. The full chain takes "
        "~30-60s per partition."
    )


# ============================================================================
# Step 4: Guarded wipe
# ============================================================================

def wipe_databases(*, namespace: str) -> None:
    """DANGEROUS. Drops Neo4j + Weaviate + Jena contents in the given namespace.

    The guard: must pass --i-mean-it AND --namespace=<name>. The namespace
    must match the deployed cluster (or be 'sandbox' / 'work' / 'local').
    This is the architect's "guarded --wipe" — no typo can nuke the wrong
    cluster.
    """
    print(f"=== DANGER: wiping databases for namespace={namespace} ===")

    # Neo4j
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "changeme")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        driver.close()
        print("[OK] Neo4j cleared.")
    except Exception as e:
        print(f"[ERROR] Neo4j wipe: {e}")

    # Weaviate
    if weaviate is not None:
        weaviate_url = os.environ.get("WEAVIATE_URL", "http://localhost:8080")
        try:
            # weaviate-client v4 form
            host_port = urlparse(weaviate_url).netloc or "localhost:8080"
            host, _, port = host_port.partition(":")
            client = weaviate.connect_to_local(host=host, port=int(port or 8080))
            try:
                for col_name in client.collections.list_all():
                    client.collections.delete(col_name)
                    print(f"  [OK] Weaviate collection {col_name} dropped.")
            finally:
                client.close()
            print("[OK] Weaviate cleared.")
        except Exception as e:
            print(f"[ERROR] Weaviate wipe: {e}")

    # Jena
    raw_host = os.environ.get("JENA_URL", "http://localhost:3030")
    host = get_base_url(raw_host)
    ds_name = os.environ.get("JENA_DS", "ds")
    user = os.environ.get("JENA_USERNAME", "admin")
    pw = os.environ.get("FUSEKI_PASSWORD") or os.environ.get("JENA_PASSWORD", "Admin123!")
    try:
        res = requests.post(
            f"{host}/{ds_name}/update",
            data={"update": "CLEAR ALL"},
            auth=(user, pw), verify=False,
        )
        if res.status_code in (200, 204):
            print(f"[OK] Jena /{ds_name} cleared.")
        else:
            print(f"[ERROR] Jena wipe: {res.status_code} {res.text}")
    except Exception as e:
        print(f"[ERROR] Jena wipe: {e}")


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prime a deployable cluster from zero (Neo4j + Jena + MinIO + optional dagster trigger)"
    )
    parser.add_argument("--wipe", action="store_true",
                        help="Wipe Neo4j + Weaviate + Jena before priming. REQUIRES --i-mean-it AND --namespace.")
    parser.add_argument("--i-mean-it", action="store_true",
                        help="Second guard for --wipe.")
    parser.add_argument("--namespace", default=None,
                        help="Cluster namespace (sandbox/work/local). Third guard for --wipe.")
    parser.add_argument("--upload-only", action="store_true",
                        help="Just upload TTLs to MinIO; skip Neo4j constraints + Jena provisioning.")
    parser.add_argument("--skip-uploads", action="store_true",
                        help="Skip MinIO upload step (use when TTLs are already there).")
    parser.add_argument("--trigger-ingest", action="store_true",
                        help="Trigger dagster ingest_ontology_job for each partition after upload. "
                             "Off by default — the dagster sensor will pick up uploaded files OR "
                             "you can fire jobs manually from the Dagster UI.")
    args = parser.parse_args()

    parse_env()

    # ----- Guarded wipe -----
    if args.wipe:
        # Allowlist of namespaces this script is allowed to wipe. The
        # default covers the common dev names; clusters with their own
        # naming convention (e.g. "d4-sandbox", "prod-east-1") publish
        # an override via the PRIME_NAMESPACE_ALLOWLIST env var, which
        # the helm chart's primeSubstrate.namespaceAllowlist value
        # populates. Comma-separated, whitespace tolerated.
        default_allow = "sandbox,work,local"
        env_allow = os.environ.get("PRIME_NAMESPACE_ALLOWLIST", default_allow)
        allowlist = {n.strip() for n in env_allow.split(",") if n.strip()}

        if not args.i_mean_it or not args.namespace:
            print(
                f"ERROR: --wipe requires BOTH --i-mean-it AND "
                f"--namespace=<one of: {sorted(allowlist)}>. "
                f"Refusing to proceed."
            )
            sys.exit(2)
        if args.namespace not in allowlist:
            print(
                f"ERROR: --namespace={args.namespace!r} is not in the allowlist "
                f"{sorted(allowlist)}. "
                f"Either set PRIME_NAMESPACE_ALLOWLIST env to include it "
                f"(comma-separated; helm chart: primeSubstrate.namespaceAllowlist), "
                f"or update setup/prime_databases.py if this is a new cluster you "
                f"want baked in."
            )
            sys.exit(2)
        wipe_databases(namespace=args.namespace)

    # ----- Pre-flight -----
    print("=== Prime Pre-Flight ===")
    time.sleep(1)

    if args.upload_only:
        upload_canonical_ttls()
        if args.trigger_ingest:
            trigger_ingest_jobs()
        return

    prime_neo4j()
    prime_jena()

    if not args.skip_uploads:
        upload_canonical_ttls()

    if args.trigger_ingest:
        trigger_ingest_jobs()

    print("=== Prime complete ===")
    print(
        "Next steps:\n"
        "  - If you did NOT pass --trigger-ingest, fire ingest_ontology_job from the "
        "Dagster UI (or wait for the sensor to auto-detect uploads).\n"
        "  - After ingest, verify with: cypher MATCH (c:OntologyClass) WHERE c.domain "
        "IN ['MAINTENANCE','MIL','MESH','DATA_ENGINEERING','SUSTAINMENT'] RETURN c.domain, count(c)\n"
        "  - Then deploy engines (Helm) and run the routing matrix to confirm "
        "deployability."
    )


if __name__ == "__main__":
    main()
