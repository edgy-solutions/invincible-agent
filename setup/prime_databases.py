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


def _minio_compat_config():
    """Return a botocore Config that keeps boto3 1.36+ MinIO-compatible.

    boto3 1.36 switched the default request-checksum algorithm from
    Content-Md5 (sent as a header) to x-amz-checksum-crc32 (sent as a
    trailer). MinIO's DeleteObjects still requires Content-Md5 and
    rejects the new shape with:

        MissingContentMD5 — Missing required header for this request: Content-Md5.

    Setting request_checksum_calculation="when_required" restores the
    pre-1.36 behavior: boto3 sends Content-Md5 on the requests that
    historically needed it (DeleteObjects, PutBucketLifecycle, etc.).

    Apply to every boto3 S3 client pointed at MinIO. Cheap and safe
    against real AWS too — AWS accepts both shapes.
    """
    if boto3 is None:
        return None
    from botocore.config import Config
    return Config(request_checksum_calculation="when_required")


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
    # PCN/PDN subject vocabulary. The class IRIs (pcn:ProductDiscontinuationNotice /
    # pcn:ProcessChangeNotification / pcn:Component) are EXACTLY the instance types
    # doc-tools' SustainmentPlugin writes, so declaring them here lights up /classes +
    # the SPO-interview operable-subjects menu over the parts doc-tools already extracts.
    # Classes + RDF data-properties ONLY — actionable disposition VERBS wake per-endpoint.
    {
        "domain": "SUSTAINMENT",
        "name": "pcn_extension",
        "s3_key": "sustainment/pcn_extension.ttl",
        "path": "ontologies/pcn_extension.ttl",
    },
    # PCN/PDN disposition rules — POLICY AS DATA (the condition->disposition decision table the
    # proposer consumes). Ingested here so it is versioned, reproducible, owner-ratifiable, and
    # covered by the drift-check like every other standards artifact. SEED = the agent's reading of
    # domain convention; every rule's prov:wasDerivedFrom is empty pending domain-owner ratification.
    {
        "domain": "SUSTAINMENT",
        "name": "pcn_disposition_rules",
        "s3_key": "sustainment/pcn_disposition_rules.ttl",
        "path": "ontologies/pcn_disposition_rules.ttl",
    },

    # M3.1 — canonical PRODUCT STRUCTURE (ADR-0035 data plane). S3000L-derived where the
    # standard covers the need (Breakdown/BreakdownElement for structure, ApplicabilityStatement
    # for effectivity — the standard's OWN names, found by reading it rather than inventing
    # Assembly/Component/Effectivity and silently forfeiting three citations). The approved-source
    # bridge is HOUSE CONVENTION, labelled as such and NOT carrying a derivedFrom, because S3000L
    # models manufacturer part numbers as identifier variants and that shape cannot express the
    # many-to-many, provenance-bearing, lifecycle-carrying relationship the disposition process
    # manipulates. Every citation is verified present in the live S3000L graph — a cited-but-
    # invented IRI is worse than an empty slot, because it looks like compliance and cannot be
    # traced. See docs/adr/ADR-0035 and setup/queries/product_structure_acceptance.sparql.
    {
        "domain": "SUSTAINMENT",
        "name": "product_structure_extension",
        "s3_key": "sustainment/product_structure_extension.ttl",
        "path": "ontologies/product_structure_extension.ttl",
    },
    # M3.1 — QUALIFICATION STATUS vocabulary (ADR-0035 §6). A SEED MENU, not an enum: statuses are
    # policy vocabulary, so the writer validates against THIS FILE and an unrecognized status is a
    # loud ingest-time refusal. A state nobody uses sits inert; a state that turns out to be needed
    # arrives as one more entry through this same path — which is why a wrong seed costs nothing
    # and why `qualifying` ships flagged in-file as the split most likely to be wrong.
    {
        "domain": "SUSTAINMENT",
        "name": "qualification_status_vocabulary",
        "s3_key": "sustainment/qualification_status_vocabulary.ttl",
        "path": "ontologies/qualification_status_vocabulary.ttl",
    },

    # ----- LAYER 3: DATA_ENGINEERING (idp catalog / lineage) -----
    # The semantic domain is DATA_ENGINEERING, not IDP.
    # The resolver queries with semantic domain names (the architect's
    # Step-1 explicit_domain lesson, validated by a fresh-bootstrap
    # rehearsal that surfaced this exact bug shape — "domain matches
    # path, not what the resolver actually queries with" gives
    # silent UNKNOWN cascades). idp:* classes are the canonical
    # catalog/lineage vocabulary for data-engineering questions.
    #
    # PROV-O was REMOVED 2026-07-01 per
    # [[ontology-class-pool-prov-contamination]]. PROV-O is used as a
    # design-reference vocabulary throughout the system (our
    # AnswerArtifact writer produces produced_by / produced_for /
    # derived_from_artifact_id / valid_as_of shapes that mirror
    # prov:wasAttributedTo / prov:wasInformedBy / prov:wasDerivedFrom /
    # prov:generatedAtTime — same semantics, our own namespace so we
    # can extend without touching W3C), but its CLASSES are corpus-
    # noise when they enter the routable OntologyClass pool. Their
    # W3C-quality definitions vector-outcompete domain classes with
    # weaker definitions (a user asking "who authorized this?" would
    # route to prov:Bundle before AuthorizationDecision). The
    # meta-ontology filter in doc_tools/assets/ontology_assets.py
    # (_META_ONTOLOGY_IRI_PREFIXES) already drops every one of PROV-O's
    # URIs; ingesting the TTL just to filter it out was wasted work
    # AND caused sync_jena_ontologies_to_neo4j to fail with the
    # confusing "zero classes extracted" exception (SPARQL DID find
    # them; filter dropped them all; the zero-check couldn't tell
    # the difference). Removing at the seed source is the durable
    # fix; doc-tools' cc79098 handles accidental future meta-ontology
    # uploads gracefully.
    {
        "domain": "DATA_ENGINEERING",
        "name": "idp_extension",
        "s3_key": "idp/idp_extension.ttl",
        "path": "ontologies/idp_extension.ttl",
    },

    # ----- LAYER 3b: PORTFOLIO_PLANNING (Engine P's subject nouns) -----
    # The INPUT end of Contract D for all twelve planning verbs. The output end
    # (the mesh:Plan* response types) rides in mesh_system.ttl, which is exactly why
    # the output half landed and the input half did not: only one of the two was ever
    # authored. Measured 2026-08-22 — twelve registrations, twelve 422s naming these
    # five URIs, while the engine served /health normally throughout.
    #
    # DOMAIN IS PORTFOLIO_PLANNING, matching what Engine P registers its verbs under
    # (agent_fleet/planning_agent/main.py). The resolver queries by semantic domain
    # name, and a class whose domain does not match what the resolver asks for gives a
    # silent UNKNOWN cascade — the same shape the DATA_ENGINEERING note above records
    # from a fresh-bootstrap rehearsal.
    {
        "domain": "PORTFOLIO_PLANNING",
        "name": "portfolio_planning_extension",
        "s3_key": "planning/portfolio_planning_extension.ttl",
        "path": "ontologies/portfolio_planning_extension.ttl",
    },

    # ----- LAYER 3c: PROGRAM_FINANCE (Engine F's subject nouns AND its outputs) -----
    # BOTH ENDS OF CONTRACT D IN ONE FILE, deliberately. The planning entry above authored
    # only the INPUT end — the mesh:Plan* output types ride in mesh_system.ttl — and that
    # split is exactly why the input half went missing unnoticed: twelve registrations, twelve
    # 422s, engine healthy throughout. finance_extension.ttl carries its eight fin: subject
    # nouns and its six fin: response shapes together, so there is one file to seed and one
    # file to verify.
    #
    # DOMAIN IS PROGRAM_FINANCE, matching what Engine F registers its verbs under
    # (agent_fleet/finance_agent/main.py). Same warning as the planning entry: the resolver
    # queries by semantic domain name, and a class whose domain does not match what the
    # resolver asks for gives a silent UNKNOWN cascade.
    {
        "domain": "PROGRAM_FINANCE",
        "name": "finance_extension",
        "s3_key": "finance/finance_extension.ttl",
        "path": "ontologies/finance_extension.ttl",
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

    THE UNATTENDED PATH HAS EXACTLY ONE DOMAIN SOURCE, AND IT IS THE
    METADATA THIS FUNCTION WRITES. doc-tools' `ontology_sensor` (an
    `S3SensorComponent` over this bucket, RUNNING in sandbox) picks up
    new objects on its own and launches the job with both ops — so no
    `--trigger-ingest` is needed. But the sensor builds run config
    containing ONLY `file_url` (dag-tools `sensor_component.py`), so
    `S3FileConfig.extra_metadata` is empty and
    `ontology_assets`' domain resolution falls through to priority 2:
    the object's `x-amz-meta-domain`. Set here; set nowhere else on
    that path.

    Consequence for anyone uploading BY HAND: `mc pipe` writes no user
    metadata, so a hand-piped TTL reaches a running sensor with no
    declared domain and the asset REFUSES ("Domain not declared for
    ontology ..."). That refusal is the design working — the path's
    first segment is deliberately NOT used to infer a domain, per the
    domain-fix era — but it only reads as correct if you knew the
    interlock. Use this function, or `mc cp --attr "domain=<DOMAIN>"`.

    `--trigger-ingest` is immune to the trap for a specific reason
    worth knowing rather than cargo-culting: it passes the domain
    explicitly in the GraphQL run config (priority 1), so it does not
    depend on the object metadata at all. That makes it the right
    fallback when a hand-uploaded object is already in the bucket
    without metadata, or when the sensor's cursor is misbehaving.
    """
    print("--- Uploading canonical TTLs to MinIO ---")
    if boto3 is None:
        raise RuntimeError("boto3 not installed; pip install boto3")

    endpoint = os.environ.get("S3_ENDPOINT_URL") or os.environ.get("MINIO_URL", "http://localhost:9000")
    access_key = os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    bucket = os.environ.get("ONTOLOGY_BUCKET", "ontologies")

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=_minio_compat_config(),
    )

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
            # Boto3 PREPENDS "x-amz-meta-" to every key in Metadata={...}
            # when constructing the actual S3 headers — so passing keys
            # that already contain "x-amz-meta-" produces double-prefixed
            # headers like "x-amz-meta-x-amz-meta-domain". The reader in
            # doc-tools' ontology_assets does head.get("Metadata").get("domain")
            # (boto3 strips the single prefix on read), so the
            # double-prefixed key is invisible to it and every ingest
            # raises "Domain not declared for ontology '<path>'" even
            # though the upload reported [OK]. Observed at work-cluster
            # ingest 2026-06-19.
            #
            # Pass the bare keys; boto3 adds the one prefix; reader finds them.
            s3.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=data,
                Metadata={
                    "domain": domain,
                    "source-url": source_metadata,
                    "canonical-name": name,
                },
            )
            print(f"    [OK] → s3://{bucket}/{s3_key} ({len(data)} bytes)")
        except Exception as e:
            print(f"    [ERROR] upload: {e}")
            raise

    print("[SUCCESS] All canonical TTLs uploaded.")


def _compact_jena(host: str, ds_name: str, auth) -> None:
    """Compact the TDB2 dataset so DROP/DELETE actually RETURN disk.

    TDB2 reclaims space ONLY via compaction; DROP just marks data dead. Without
    this, a re-prime grows the store every run (clear-then-re-append) until the
    PVC fills and TDB2 wedges on msync ("No space left on device") — at which
    point even a DROP can't commit and the prime hangs at clear_ontology_graphs.
    deleteOld=true removes the pre-compaction copy (else Fuseki keeps BOTH
    generations, transiently DOUBLING on-disk size — the opposite of what a
    pressured PVC needs). Poll the async task so reclaim finishes before the
    re-ingest re-appends. Best-effort: a compaction failure is logged, not
    fatal — the prime's job is to populate; a missed compaction only defers
    reclaim to the next run. (First-fill of an ALREADY-full PVC still needs a
    manual volume reclaim/expand; this keeps it from re-filling thereafter.)"""
    # TIMEOUTS ARE LOAD-BEARING: compact is fired against a store that may be
    # under disk pressure — the very condition this exists to relieve. Without a
    # timeout the POST/poll could hang FOREVER on a wedged Fuseki, turning a
    # "best-effort, non-fatal" maintenance step into the prime's new hang. Kick
    # off (POST returns the task id quickly, it runs async) and poll bounded.
    try:
        r = requests.post(
            f"{host}/$/compact/{ds_name}", params={"deleteOld": "true"},
            auth=auth, proxies=proxy_int, verify=False, timeout=30,
        )
        r.raise_for_status()
        task_id = (r.json() or {}).get("taskId")
        print(f"  [compact] TDB2 compaction started (task {task_id}); waiting for reclaim…")
        for _ in range(90):  # ~3 min ceiling
            time.sleep(2)
            try:
                t = requests.get(
                    f"{host}/$/tasks/{task_id}", auth=auth, proxies=proxy_int,
                    verify=False, timeout=15,
                )
            except requests.RequestException as pe:
                print(f"  [warn] compaction poll failed ({pe}); reclaim continues in background.")
                return
            if t.status_code != 200:
                break
            if (t.json() or {}).get("finished"):
                print("  [compact] finished — dead space reclaimed.")
                return
        print("  [compact] still running past budget — reclaim will finish in the background.")
    except Exception as e:
        print(f"  [warn] TDB2 compaction skipped ({e}); disk reclaim deferred to next prime.")


def clear_ontology_graphs() -> None:
    """Append-idempotency guard: DROP the MANIFEST-listed domain graphs BEFORE the
    per-file ingests POST-append into them.

    doc-tools ``ontology_assets.py`` now POSTs (merges) each TTL into its domain
    graph instead of PUT (replace) — because MANY files map to ONE domain and PUT
    collapsed them to the last file (found 2026-07-22: MAINTENANCE held only
    mil_extension, IOF core destroyed). POST accumulates them; but append-only would
    DOUBLE blank-node structures (owl:Restriction etc.) on every re-prime. Clearing
    the graphs once here makes a re-prime a clean rebuild — the reproducible,
    idempotent home for the reset (bootstrap-state-debt: no hand-run DROP).

    CRITICAL INVARIANT (2026-07-23): drop ONLY graphs the manifest can REPRODUCE — the
    per-domain vocabulary graphs ``http://internal/{DOMAIN}`` for each distinct domain
    in ``CANONICAL_TTL_MANIFEST``. Do NOT glob ``http://internal/*``. Runtime producers
    (e.g. doc-tools' PCN/PDN extraction) write NON-reproducible INSTANCE data into their
    own graphs (``http://internal/{DOMAIN}_INSTANCES``), and DROP-first is only safe for
    data the manifest can re-land — an earlier glob would have wiped real extracted parts
    on the very prime run meant to enable the pcn dogfood. Producers with different
    reproducibility must not share a graph, and the clearer enforces the split (not just
    convention). Consequence: a stale exact-name graph from the pre-domain-fix era is no
    longer auto-swept here — clear any such legacy graph manually, once.

    DEAD SPACE: pre-GRAPH-fix PCN/PDN instances (written before doc-tools scoped its INSERT
    DATA) still sit in Jena's DEFAULT graph — permanent, invisible orphans. Harmless, but they
    inflate a triple count someday. This clearer does NOT touch the default graph (dropping it
    wholesale is too broad to automate safely); run a one-time ``DROP DEFAULT`` by hand if a
    store audit shows it non-empty.
    """
    print("--- Clearing manifest ontology graphs (append-idempotency; instance graphs untouched) ---")
    raw_host = os.environ.get("JENA_URL") or os.environ.get("JENA_SPARQL_ENDPOINT", "http://localhost:3030")
    host = get_base_url(raw_host)
    ds_name = os.environ.get("JENA_DS", "ds")
    user = os.environ.get("JENA_USERNAME", "admin")
    pw = os.environ.get("FUSEKI_PASSWORD") or os.environ.get("JENA_PASSWORD", "Admin123!")
    auth = (user, pw)
    update_url = f"{host}/{ds_name}/update"
    # The reproducible set: one vocabulary graph per distinct manifest domain. Instance
    # graphs (…_INSTANCES) are deliberately absent from this set, so they are never dropped.
    manifest_graphs = sorted({f"http://internal/{e['domain']}" for e in CANONICAL_TTL_MANIFEST})
    try:
        for g in manifest_graphs:
            # DROP SILENT: a manifest graph may not exist yet on a fresh store.
            up = requests.post(
                update_url, data={"update": f"DROP SILENT GRAPH <{g}>"},
                auth=auth, proxies=proxy_int, verify=False,
            )
            up.raise_for_status()
            print(f"  [clear] DROP SILENT GRAPH <{g}>")
        # RECLAIM: DROP is a logical delete — return the freed space to disk so
        # the store doesn't grow monotonically across re-primes and fill the PVC.
        # Runs after the drop, before trigger_ingest_jobs re-appends.
        _compact_jena(host, ds_name, auth)
    except Exception as e:
        # Fail loud — a half-cleared store would silently under-populate the menu.
        print(f"  [ERROR] clear_ontology_graphs failed: {e}")
        raise


def trigger_ingest_jobs(*, wait: bool = False, wait_timeout: int = 1800) -> None:
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
    # Clear the domain graphs ONCE before the per-file POST-appends, so a re-prime
    # rebuilds cleanly (append-idempotency; pairs with ontology_assets.py PUT->POST).
    clear_ontology_graphs()
    # Backward-compat: DAGSTER_URL was the original env name; the helm
    # chart emits DAGSTER_HOST (matches the engineering convention used by
    # most fleet services). Read both, prefer DAGSTER_URL when explicitly
    # set so callers can override.
    dagster_url = (
        os.environ.get("DAGSTER_URL")
        or os.environ.get("DAGSTER_HOST")
        or "http://localhost:3000"
    )
    graphql = f"{dagster_url}/graphql"

    # ontology_files is a DynamicPartitionsDefinition. Partition keys must
    # be REGISTERED with Dagster (via addDynamicPartition) BEFORE they can
    # be used in a run. Normally the ontology_sensor in doc-tools'
    # definitions.py does this on the next tick after MinIO upload — but
    # --trigger-ingest runs synchronously RIGHT after the upload, faster
    # than the sensor's poll interval, so we call addDynamicPartition
    # ourselves. Idempotent: if the sensor has already registered the
    # partition the mutation succeeds with no-op.
    #
    # Dagster's GraphQL schema requires repositorySelector on this mutation
    # (1.5+; 1.13.7 in use at the work cluster). Omitting it returns HTTP
    # 400 with a validation error "Field 'addDynamicPartition' argument
    # 'repositorySelector' of type 'RepositorySelector!' is required" —
    # that's what was producing the per-partition WARNING lines (the runs
    # then launched anyway because launchPipelineExecution auto-registers
    # the partition on launch in this version). Adding the selector makes
    # the warning go away and gives us a real success/duplicate ack.
    add_partition_mutation_q = (
        "mutation AddPartition($repositorySelector: RepositorySelector!, "
        "$partitionsDefName: String!, $partitionKey: String!) { "
        "addDynamicPartition(repositorySelector: $repositorySelector, "
        "partitionsDefName: $partitionsDefName, partitionKey: $partitionKey) { "
        "__typename "
        "... on AddDynamicPartitionSuccess { partitionsDefName partitionKey } "
        "... on PythonError { message } "
        "... on DuplicateDynamicPartitionError { __typename } "
        "} }"
    )
    add_partition_repo_selector = {
        "repositoryLocationName": "doc-tools",
        "repositoryName": "__repository__",
    }

    launched: list[tuple[str, str]] = []
    for entry in CANONICAL_TTL_MANIFEST:
        domain = entry["domain"]
        s3_key = entry["s3_key"]
        partition_key = s3_key.replace("/", "__")
        file_url = f"s3://{os.environ.get('ONTOLOGY_BUCKET', 'ontologies')}/{s3_key}"

        # Register the partition key first. Errors here are non-fatal —
        # the sensor may have beaten us to it, and DuplicateDynamicPartitionError
        # is exactly that case.
        try:
            ap_resp = requests.post(
                graphql,
                json={
                    "query": add_partition_mutation_q,
                    "variables": {
                        "repositorySelector": add_partition_repo_selector,
                        "partitionsDefName": "ontology_files",
                        "partitionKey": partition_key,
                    },
                },
                timeout=15,
            )
            if ap_resp.status_code == 200:
                ap_data = ap_resp.json().get("data", {}).get("addDynamicPartition", {})
                t = ap_data.get("__typename")
                if t == "AddDynamicPartitionSuccess":
                    pass  # registered cleanly
                elif t == "DuplicateDynamicPartitionError":
                    pass  # sensor beat us to it; fine
                else:
                    print(f"  [WARNING] {entry['name']} addDynamicPartition: {ap_data}")
            else:
                # Surface the GraphQL error body so the next mismatch
                # (schema changes in future Dagster bumps) is diagnosable
                # at first sight instead of opaque "HTTP 400".
                body_preview = ap_resp.text[:400].replace("\n", " ")
                print(
                    f"  [WARNING] {entry['name']} addDynamicPartition "
                    f"HTTP {ap_resp.status_code}: {body_preview}"
                )
        except Exception as e:
            print(f"  [WARNING] {entry['name']} addDynamicPartition: {type(e).__name__}: {e}")

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
                launched.append((entry["name"], run_id))
                print(f"  [LAUNCHED] {entry['name']} → run {run_id}")
            else:
                print(f"  [WARNING] {entry['name']}: {data}")
        except Exception as e:
            print(f"  [WARNING] {entry['name']}: {e}")

    if not wait:
        print(
            "[NOTE] Runs launched asynchronously. Monitor in the Dagster UI; "
            "poll the runOrError query for status. The full chain takes "
            "~30-60s per partition."
        )
        return

    # WAIT FOR WHAT WE LAUNCHED.
    #
    # Without this, "Prime complete" means "twelve runs were enqueued", and the
    # helm hook chain -- prime(10) -> ontologySeed(15) -> reregister(20), which
    # the chart calls "a correctness invariant, not a tunable" -- sequences the
    # JOBS while the actual ingest escapes the ordering entirely. Engines then
    # re-register against classes that do not exist yet and Contract D refuses
    # the triples SILENTLY.
    #
    # The reregister job's sentinel was supposed to cover this, and cannot: with
    # wipe=false the sentinel class is still present from the PREVIOUS prime, so
    # `class exists` is satisfied by leftover state on the first poll and the
    # wait is a no-op. Observed 2026-08-21: reregister logged `[ready] sentinel
    # present` immediately and completed in 47s while the mesh ingest was still
    # QUEUED. Existence cannot prove freshness; only the run status can.
    _await_ingest_runs(launched, graphql, wait_timeout)



def _await_ingest_runs(
    launched: "list[tuple[str, str]]",
    graphql: str,
    wait_timeout: int,
) -> None:
    """Block until every launched ingest run reaches a terminal state.

    Raises SystemExit if any run failed or is still unfinished at the deadline.
    Extracted from ``trigger_ingest_jobs`` so the failure arms are testable
    without a cluster: the LOUD path is the whole point of this function, and a
    path that has never been exercised is not known to work.
    """
    print(f"--- Waiting for {len(launched)} ingest run(s) ---", flush=True)
    pending = {rid: name for name, rid in launched if rid}
    done, failed = {}, {}
    deadline = time.time() + wait_timeout
    while pending and time.time() < deadline:
        for rid in list(pending):
            try:
                q = ('{runOrError(runId:"%s"){__typename ... on Run{status}}}' % rid)
                r = requests.post(graphql, json={"query": q}, timeout=15)
                st = (r.json().get("data", {}).get("runOrError", {}) or {}).get("status")
            except Exception:
                continue  # transient; retry on the next sweep
            if st in ("SUCCESS", "FAILURE", "CANCELED"):
                name = pending.pop(rid)
                (done if st == "SUCCESS" else failed)[rid] = name
                print(f"  [{st}] {name}", flush=True)
        if pending:
            time.sleep(10)

    for rid, name in pending.items():
        print(f"  [TIMEOUT] {name} still running after {wait_timeout}s (run {rid})")

    print(f"--- Ingest: {len(done)} ok, {len(failed)} failed, {len(pending)} unfinished ---")
    if failed or pending:
        # Loud, not advisory. A downstream step that re-registers against a
        # half-ingested ontology produces confidently-wrong routing, which is
        # far more expensive to find than a failed upgrade.
        raise SystemExit(
            "[ERROR] ontology ingest did not complete cleanly; refusing to report "
            "success. Downstream reregistration would run against a partial class "
            "graph. Re-run prime after resolving the failures above."
        )

# ============================================================================
# Step 4: Guarded wipe
# ============================================================================

def wipe_databases(*, namespace: str, nuclear: bool = False) -> None:
    """DANGEROUS. Resets the substrate for the given namespace.

    TWO TIERS — the default preserves user/durability data so a routine
    wipe+reprime can NEVER break the environment; --nuclear blows it all
    away CONSISTENTLY.

      DEFAULT (routing-substrate). Clears only the reproducible ROUTING/
      ontology substrate — Neo4j `OntologyClass` nodes (and the verb +
      subClassOf edges that hang off them), every Weaviate collection,
      the Jena dataset, the MinIO TTLs. The ingest rebuilds all of it.
      PRESERVED, untouched: the answer-durability graph in Neo4j
      (`AnswerArtifact` / `Actor` / `Source` / `WatermarkSequence`) AND
      the derived Postgres projection stores (answer_artifact_projection,
      human_task_projection, projector_cursor). This is what a wipe+reprime
      SHOULD do. The blanket `MATCH (n) DETACH DELETE n` this replaced
      deleted `WatermarkSequence`, resetting the monotonic answer-watermark
      sequence to 1 while the projector's Postgres cursor stayed parked at
      its old high value — so every new answer landed BELOW the cursor and
      never projected to the UI (the stranded-cursor bug, work 2026-07-18).
      A routing wipe has no business touching answer history or the
      sequence, so it no longer does.

      NUCLEAR (--nuclear). Everything the default clears, PLUS the
      durability graph (blanket `DETACH DELETE`) AND a reset of the derived
      Postgres stores (truncate the projections, rewind the cursor to 0).
      The source and its projection reset TOGETHER, so a scorched-earth
      wipe still leaves a consistent empty state — never a stranded cursor.

    The guard (both tiers): --i-mean-it AND --namespace=<name> in the
    allowlist. --nuclear additionally requires --wipe. No typo can nuke the
    wrong cluster; no default wipe can silently eat answer history.
    """
    tier = "NUCLEAR" if nuclear else "routing-substrate"
    print(f"=== DANGER: {tier} wipe for namespace={namespace} ===")

    # Neo4j
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "changeme")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            if nuclear:
                session.run("MATCH (n) DETACH DELETE n")
                print("[OK] Neo4j cleared (NUCLEAR — includes answer history "
                      "+ WatermarkSequence).")
            else:
                # Routing substrate only. `OntologyClass` is the sole routing
                # node label — the registrar / ingest MERGE it, and the verb
                # (r.iri) + subClassOf edges are relationships between
                # OntologyClass nodes, so DETACH removes them with it. The
                # answer-durability labels (AnswerArtifact / Actor / Source /
                # WatermarkSequence) are deliberately SPARED: deleting
                # WatermarkSequence resets the answer-watermark sequence and
                # strands the projector's Postgres cursor (see docstring).
                # If a NEW routing node label is ever introduced, add it here.
                session.run("MATCH (n:OntologyClass) DETACH DELETE n")
                print("[OK] Neo4j routing substrate cleared (OntologyClass + "
                      "its edges); answer-durability nodes preserved.")
        driver.close()
    except Exception as e:
        print(f"[ERROR] Neo4j wipe: {e}")

    # Weaviate — connect via the SAME split HTTP/gRPC form the chart
    # publishes (WEAVIATE_HTTP_HOST + WEAVIATE_GRPC_HOST) that the fleet's
    # create_weaviate_client() uses.
    #
    # PRE-FIX BUG (2026-07-18): this read WEAVIATE_URL — which the chart
    # NEVER sets, so it defaulted to http://localhost:8080 — and used
    # connect_to_local (single host). Against a split/external Weaviate
    # (work: weaviate.<ns>:80 HTTP + weaviate-grpc.<ns>:50051 gRPC) that
    # connection failed, the failure was caught NON-FATALLY, and the wipe
    # SKIPPED WEAVIATE ENTIRELY while Neo4j/Jena cleared. Result: stale
    # OntologyClass phantoms + a mis-configured Predicate collection
    # survived every "wipe", and the operator had no way to know (a quiet
    # [ERROR] line that read like the other non-fatal warnings).
    #
    # A wipe that silently skips a store is worse than one that errors, so
    # a failure here now RAISES: the operator explicitly passed
    # --wipe --i-mean-it, and a store that didn't clear must NOT be
    # mistaken for success.
    if weaviate is None:
        raise RuntimeError(
            "--wipe requested but the `weaviate` client isn't importable in "
            "this image — refusing to report a partial wipe as complete."
        )

    def _weaviate_host_port(env_val, default_port):
        clean = env_val.replace("http://", "").replace("https://", "").replace("grpc://", "")
        host, _, port = clean.partition(":")
        try:
            return host, int(port) if port else default_port
        except ValueError:
            return host, default_port

    http_h, http_p = _weaviate_host_port(
        os.environ.get("WEAVIATE_HTTP_HOST", "weaviate:8080"), 8080)
    grpc_h, grpc_p = _weaviate_host_port(
        os.environ.get("WEAVIATE_GRPC_HOST", "weaviate-grpc:50051"), 50051)
    try:
        client = weaviate.connect_to_custom(
            http_host=http_h, http_port=http_p, http_secure=False,
            grpc_host=grpc_h, grpc_port=grpc_p, grpc_secure=False,
        )
        try:
            cols = list(client.collections.list_all())
            for col_name in cols:
                client.collections.delete(col_name)
                print(f"  [OK] Weaviate collection {col_name} dropped.")
            print(f"[OK] Weaviate cleared ({len(cols)} collection(s)) "
                  f"at {http_h}:{http_p} / grpc {grpc_h}:{grpc_p}.")
        finally:
            client.close()
    except Exception as e:
        # FATAL — see the block comment above. A skipped Weaviate wipe is
        # exactly the failure that hid stale phantoms across many wipes.
        raise RuntimeError(
            f"Weaviate wipe FAILED at http {http_h}:{http_p} / grpc "
            f"{grpc_h}:{grpc_p}: {e}. The wipe is INCOMPLETE — Neo4j/Jena "
            f"may already be cleared but Weaviate is NOT. Fix connectivity "
            f"(WEAVIATE_HTTP_HOST / WEAVIATE_GRPC_HOST) and re-run; do not "
            f"treat this prime as a clean wipe."
        ) from e

    # Jena
    raw_host = os.environ.get("JENA_URL", "http://localhost:3030")
    host = get_base_url(raw_host)
    ds_name = os.environ.get("JENA_DS", "ds")
    user = os.environ.get("JENA_USERNAME", "admin")
    pw = os.environ.get("FUSEKI_PASSWORD") or os.environ.get("JENA_PASSWORD", "Admin123!")
    try:
        # timeout is load-bearing: a TDB2 left WEDGED by a prior disk-full
        # (msync failure corrupts the mmap/journal) blocks CLEAR ALL forever on
        # a stuck write lock — expanding the PVC gives space but not a healthy
        # store. Bound it so the wedge surfaces as a LOUD error the operator can
        # act on (recreate the TDB2), not an invisible hang. A hung CLEAR ALL
        # means the store needs recreating, not retrying.
        res = requests.post(
            f"{host}/{ds_name}/update",
            data={"update": "CLEAR ALL"},
            auth=(user, pw), verify=False, timeout=120,
        )
        if res.status_code in (200, 204):
            print(f"[OK] Jena /{ds_name} cleared.")
        else:
            print(f"[ERROR] Jena wipe: {res.status_code} {res.text}")
    except requests.Timeout:
        print(
            "[ERROR] Jena wipe: CLEAR ALL timed out after 120s — TDB2 is likely "
            "WEDGED from a prior disk-full (msync). Expanding the PVC does NOT "
            "heal it; RECREATE the store: scale the fuseki StatefulSet to 0, "
            "delete its PVC (or `rm -rf /fuseki-base/databases/*` in the pod), "
            "scale back up for a fresh TDB2, then re-run prime."
        )
    except Exception as e:
        print(f"[ERROR] Jena wipe: {e}")

    # MinIO ontologies bucket.
    #
    # Why this is in --wipe: the canonical TTL manifest's s3_key list can
    # change between releases (e.g. mro/IOF_Core.rdf was renamed to
    # maintenance/IOF_Core.rdf when the path-derived-domain fallback was
    # retired 2026-06-16). Without clearing, the bucket accumulates
    # orphan keys from PRIOR manifests — the dagster ontology_sensor
    # enumerates the whole bucket and tries to ingest those orphans
    # alongside the current canonical set. The orphans lack
    # x-amz-meta-domain (it's only written for current manifest entries)
    # so ingest_ontology_to_jena raises:
    #
    #   Exception: Domain not declared for ontology '<orphan path>'.
    #
    # Wiping here makes the bucket reproduce the manifest exactly. The
    # subsequent upload_canonical_ttls() repopulates it from scratch.
    endpoint = os.environ.get("S3_ENDPOINT_URL") or os.environ.get("MINIO_URL", "http://localhost:9000")
    access_key = os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    bucket = os.environ.get("ONTOLOGY_BUCKET", "ontologies")
    try:
        import boto3
        from botocore.exceptions import ClientError
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=_minio_compat_config(),
        )
        bucket_exists = True
        try:
            s3.head_bucket(Bucket=bucket)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket", "NotFound"):
                print(f"[OK] MinIO bucket {bucket} doesn't exist; nothing to wipe.")
                # Don't return — the NUCLEAR Postgres reset below still needs
                # to run. A missing bucket is a no-op, not a reason to abort
                # the rest of the wipe.
                bucket_exists = False
            else:
                raise

        # Delete PER-OBJECT, not via batch DeleteObjects. Batch DeleteObjects
        # REQUIRES a Content-MD5 (or the new x-amz-checksum trailer) that
        # boto3 1.36+ and MinIO negotiate inconsistently across versions:
        # _minio_compat_config()'s request_checksum_calculation="when_required"
        # fixes it on SOME botocore builds, but the work image still 400'd with
        # `MissingContentMD5 — Missing required header ... Content-Md5`, which
        # silently SKIPPED the wipe (stale non-canonical objects survived).
        # Single-object delete_object carries no such requirement, so it is
        # version-proof. The ontologies bucket is tiny (~a dozen keys); the
        # extra round-trips are negligible against never-wiping.
        deleted = 0
        for page in ([] if not bucket_exists else s3.get_paginator("list_objects_v2").paginate(Bucket=bucket)):
            for obj in (page.get("Contents") or []):
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
                deleted += 1
        if bucket_exists:
            print(f"[OK] MinIO bucket {bucket} cleared ({deleted} objects, per-object).")
    except Exception as e:
        print(f"[ERROR] MinIO wipe: {e}")

    # NUCLEAR only, and DELIBERATELY LAST: reset the derived Postgres
    # projection stores after every substrate store has been cleared, so a
    # Postgres hiccup can't abort the Neo4j/Weaviate/Jena/MinIO wipes (an
    # earlier version ran this right after Neo4j and a missing-driver crash
    # left Neo4j empty while the rest stayed stale). A nuclear that skipped
    # this would delete WatermarkSequence (sequence → 1) yet leave the
    # Postgres cursor parked high — recreating the exact stranded-cursor bug
    # this whole change exists to kill. RAISES on failure. The default
    # (routing) tier never runs this — it preserves the projections outright.
    if nuclear:
        _reset_projection_postgres()


def _reset_projection_postgres() -> None:
    """NUCLEAR only. Rewind the Electric-replicated projection stores so the
    derived Postgres resets TOGETHER with the Neo4j source.

    Truncates ``answer_artifact_projection`` + ``human_task_projection`` and
    rewinds ``projector_cursor.last_applied_watermark`` to 0. Without this, a
    nuclear Neo4j wipe (which deletes ``WatermarkSequence``, resetting the
    answer-watermark sequence to 1) leaves the projector cursor parked at its
    old high value; every new answer then lands below the cursor and never
    projects to the UI (the stranded-cursor bug, work 2026-07-18).

    RAISES on any failure — a nuclear wipe that silently skips the projection
    reset would recreate exactly that stranding, so it must NOT report clean.
    Tables that don't exist yet (fresh cluster, pre-migration) are skipped
    individually; that is not a failure.
    """
    dsn = os.environ.get("PROJECTOR_POSTGRES_DSN")
    if not dsn:
        raise RuntimeError(
            "--nuclear requested but PROJECTOR_POSTGRES_DSN is not set — "
            "refusing to report a nuclear wipe as complete while the derived "
            "projection store (answer_artifact_projection / projector_cursor) "
            "is left stranded. Wire PROJECTOR_POSTGRES_DSN into the prime Job "
            "(same DSN the projector Deployment uses)."
        )
    # psycopg2 (NOT psycopg v3): psycopg2-binary is a MAIN [project] dependency
    # so it is present in the slim prime image (uv sync --no-dev, no --extra);
    # psycopg v3 lives only in the agent-fleet extra and is ABSENT here. The
    # projector itself uses psycopg2 — match it. (A --nuclear run on an image
    # that imported psycopg v3 crashed with ModuleNotFoundError after Neo4j was
    # already cleared; work 2026-07-18.)
    try:
        import psycopg2
    except Exception as e:
        raise RuntimeError(
            f"--nuclear requested but psycopg2 isn't importable in this image "
            f"({e}) — cannot reset the projection store. Refusing to report a "
            f"partial nuclear wipe as clean. psycopg2-binary is a main "
            f"dependency; a prime image predating it is stale and must be rebuilt."
        )
    conn = None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
        with conn.cursor() as cur:
            def _exists(table: str) -> bool:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = %s",
                    (table,),
                )
                return cur.fetchone() is not None

            for tbl in ("answer_artifact_projection", "human_task_projection"):
                if _exists(tbl):
                    cur.execute(f"TRUNCATE {tbl}")
                    print(f"  [OK] {tbl} truncated.")
                else:
                    print(f"  [skip] {tbl} not present (fresh cluster).")
            if _exists("projector_cursor"):
                cur.execute(
                    "UPDATE projector_cursor "
                    "SET last_applied_watermark = 0, apply_count = 0"
                )
                print("  [OK] projector_cursor rewound to 0.")
            else:
                print("  [skip] projector_cursor not present (fresh cluster).")
        conn.commit()
        print("[OK] Projection Postgres reset (NUCLEAR).")
    except Exception as e:
        raise RuntimeError(
            f"NUCLEAR projection-store reset FAILED: {e}. The substrate stores "
            f"are cleared but the Postgres projections are NOT reset — the "
            f"projector cursor would strand new answers. Fix PROJECTOR_POSTGRES_DSN "
            f"connectivity and re-run; do not treat this as a clean nuclear wipe."
        )
    finally:
        if conn is not None:
            conn.close()


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
    parser.add_argument("--wait-for-ingest", action="store_true",
                        help="After launching ingest runs, BLOCK until each reaches a "
                             "terminal state and exit non-zero if any failed. Without "
                             "this, 'Prime complete' means only that runs were enqueued, "
                             "and the helm hook chain's documented ordering "
                             "(prime -> ontologySeed -> reregister) does not actually "
                             "hold for the ingest.")
    parser.add_argument("--ingest-timeout", type=int, default=1800,
                        help="Seconds to wait with --wait-for-ingest (default 1800). "
                             "Serialized ingests on arm64 nodes are slow; size this to "
                             "the SLOWEST full chain, not the median.")
    parser.add_argument("--trigger-ingest", action="store_true",
                        help="Trigger dagster ingest_ontology_job for each partition after upload. "
                             "Off by default — the dagster sensor will pick up uploaded files OR "
                             "you can fire jobs manually from the Dagster UI.")
    parser.add_argument("--nuclear", action="store_true",
                        help="Strongest form of --wipe. In addition to the routing "
                             "substrate, DELETES answer-durability nodes "
                             "(AnswerArtifact/Actor/Source/WatermarkSequence) AND resets "
                             "the Postgres projection stores (answer_artifact_projection / "
                             "human_task_projection truncated, projector_cursor rewound). "
                             "Requires --wipe. WITHOUT --nuclear, --wipe preserves all of "
                             "that so the projector is never stranded and answer history "
                             "survives a routine reprime.")
    args = parser.parse_args()

    parse_env()

    # --nuclear is a modifier ON --wipe, never a standalone. Reject it early
    # so an operator can't think they nuked when they passed nothing.
    if args.nuclear and not args.wipe:
        print("ERROR: --nuclear requires --wipe (it is the strongest form of "
              "--wipe). Refusing to proceed.")
        sys.exit(2)

    # ----- Guarded wipe -----
    if args.wipe:
        # Allowlist of namespaces this script is allowed to wipe. The
        # default covers the common dev names; clusters with their own
        # naming convention (e.g. "app-cluster", "prod-east-1") publish
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
        if args.nuclear:
            print("=== NUCLEAR: answer-durability nodes + Postgres projections "
                  "WILL be destroyed, not just the routing substrate ===")
        wipe_databases(namespace=args.namespace, nuclear=args.nuclear)

    # ----- Pre-flight -----
    print("=== Prime Pre-Flight ===")
    time.sleep(1)

    if args.upload_only:
        upload_canonical_ttls()
        if args.trigger_ingest:
            trigger_ingest_jobs(wait=args.wait_for_ingest,
                                wait_timeout=args.ingest_timeout)
        return

    prime_neo4j()
    prime_jena()

    if not args.skip_uploads:
        upload_canonical_ttls()

    if args.trigger_ingest:
        trigger_ingest_jobs(wait=args.wait_for_ingest,
                            wait_timeout=args.ingest_timeout)

    print("=== Prime complete ===")
    print(
        "Next steps:\n"
        "  - If you did NOT pass --trigger-ingest, fire ingest_ontology_job from the "
        "Dagster UI (or wait for the sensor to auto-detect uploads).\n"
        "  - After ingest, verify with: cypher MATCH (c:OntologyClass) WHERE c.domain "
        "IN ['MAINTENANCE','MIL','MESH','DATA_ENGINEERING','SUSTAINMENT','PORTFOLIO_PLANNING'] RETURN c.domain, count(c)\n"
        "  - Then deploy engines (Helm) and run the routing matrix to confirm "
        "deployability."
    )


if __name__ == "__main__":
    main()
