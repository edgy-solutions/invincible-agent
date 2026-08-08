"""iagent sandbox Domain Broker.

Tracked source for the broker that runs in ``iagent-domain-broker``.
Previously this code lived inline in a kubectl-applied ConfigMap
(``iagent-domain-broker-code``), which meant the chart couldn't
reproduce the broker on a fresh bootstrap and any change drifted
out-of-band. Per the architecture corrected in dag-tools/f55b284,
this is a *transitional* broker — it serves iagent's hardcoded
URN list (digital twin / sales_customers) while we work on
migrating those URNs into proper Dagster assets in
``iagent.definitions``. Once that migration lands, this file
retires in favor of ``hypercorn dag_tools.domain_broker.main:app``
from the iagent image (which already has ``dag-tools`` available
as a dependency).

Pattern (post-migration): each broker loads its own Dagster
Definitions module via ``DAGSTER_DEFS_MODULE`` and registers with
the mesh-level ``central-gateway``. See
[[project-sidecar-registry-pattern]] memory for the full
architecture.
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict

import httpx
from fastapi import Depends, FastAPI, HTTPException
from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("broker")

CENTRAL_GATEWAY_URL = os.environ["CENTRAL_GATEWAY_URL"]
BROKER_URL = os.environ["BROKER_URL"]
PG_HOST = os.environ.get("PG_HOST", "iagent-postgresql")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_USER = os.environ["PG_USER"]
PG_PASSWORD = os.environ["PG_PASSWORD"]
PG_DATABASE = os.environ["PG_DATABASE"]
# ClickHouse
CH_HOST = os.environ.get("CH_HOST", "iagent-clickhouse")
CH_PORT = int(os.environ.get("CH_PORT", "8123"))
CH_USER = os.environ.get("CH_USER", "iagent")
CH_PASSWORD = os.environ.get("CH_PASSWORD", "")
CH_DATABASE = os.environ.get("CH_DATABASE", "iagent")
# MinIO (S3-compatible)
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "http://iagent-minio:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")

# iagent-owned URN → physical-credentials map.
#
# IMPORTANT (ADR-0014): only register URNs that actually exist in
# the DataHub catalog this sandbox advertises. Earlier versions kept
# "sales_customers_parquet/delta/iceberg" and "clickhouse,
# sales_customers" URNs around from yesterday's backend-coverage
# tests; once Engine DA started routing catalog-Q&A queries to
# itself, those leftover entries hallucinated as "real datasets"
# through the smolagent's prompt. The trimmed list below is the
# only authoritative iagent-owned set.
#
# Future state (post-migration to dag-tools/domain_broker): these
# entries become @asset definitions in iagent.definitions with the
# appropriate IO manager classes, and the broker reads them via
# dag_tools.inventory.extract_records the same way pub-tools'
# broker reads pub_tools.definitions.
LOCAL_ASSETS: Dict[str, Dict[str, Any]] = {
    # Test 1 baseline — postgres sales_customers (still actively used).
    "urn:li:dataset:(urn:li:dataPlatform:postgres,sales_customers,PROD)": {
        "io_manager_type": "postgres",
        "schema": "public",
        "table": "customers",
    },
    # Digital twin test — postgres instance_state telemetry.
    "urn:li:dataset:(urn:li:dataPlatform:postgres,instance_state,PROD)": {
        "io_manager_type": "postgres",
        "schema": "public",
        "table": "instance_state",
    },
}


class ResolveRequest(BaseModel):
    urn: str


async def _register_once(c: httpx.AsyncClient) -> None:
    """Push our URN list to central-gateway so it knows which broker
    serves them. The gateway's Redis route entries TTL at 5 min, so
    a single hiccup past TTL drops every URN this broker serves —
    that's why ``_re_register_loop`` re-pushes every 2 min.
    """
    urns = list(LOCAL_ASSETS.keys())
    r = await c.post(
        f"{CENTRAL_GATEWAY_URL}/api/v1/internal/register",
        json={"broker_url": BROKER_URL, "asset_urns": urns},
    )
    r.raise_for_status()


async def _re_register_loop() -> None:
    """Re-register every 2 min. Non-fatal per-iteration failures —
    we keep serving /resolve even when the gateway is temporarily
    unreachable; the next push recovers automatically.
    """
    import asyncio
    while True:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                await _register_once(c)
                log.info("re-registered %d assets with gateway", len(LOCAL_ASSETS))
        except Exception as e:
            log.error("re-register failed: %s", e)
        await asyncio.sleep(120)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            await _register_once(c)
            log.info("initial register: %d assets", len(LOCAL_ASSETS))
    except Exception as e:
        log.error("initial register failed (will retry in loop): %s", e)
    task = asyncio.create_task(_re_register_loop())
    try:
        yield
    finally:
        task.cancel()


# Inbound transport auth (OBSERVE by default) — the SDK's ONE implementation, app-level so it
# covers every route. Imported HARD, not behind a try/except: a guarded import is exactly the
# "importable-but-unapplied" softness that let core/authz.py read as a gate for months. If the
# module is missing the broker must fail loudly at start, not serve unauthenticated and silent.
#
# CORRECTED 2026-08-08 — the previous note here claimed this file "EXECUTES in the iagent
# image". IT DOES NOT. This pod runs STOCK `python:3.12-slim` and pip-installs its dependencies
# at start (see the pip line in templates/domain-broker.yaml). Rebuilding the iagent image
# would therefore never have satisfied the hard import above, and rolling this pod on that
# belief would have CrashLoopBackOff'd it permanently. The roll litany's pre-roll
# image-carries check caught it before any restart.
#
# `iagent-mesh` is installed from the GitHub TAG TARBALL, pinned by
# `.Values.domainBroker.meshSdkVersion` and asserted equal to the engines' pyproject pin by
# tests/test_lock_coherence.py. Not `git+https://` — this image ships no `git`.
#
# The general form, which is why the note was wrong in a way worth recording: A COMMENT
# ASSERTING A DEPLOYMENT FACT IS AN UNTESTED CLAIM. This one was written from the shape of the
# neighbouring services and never checked against the pod it described.
_announce_transport_auth(component="domain-broker")

app = FastAPI(

    **_docs_kwargs(),  # /docs,/redoc,/openapi.json OFF in deployment (Starlette-bypass class)
    lifespan=lifespan,
    title="iagent Sandbox Domain Broker",
    dependencies=[Depends(_transport_auth("domain-broker"))],
)


@app.get("/health")
async def health():
    return {"status": "ok", "assets": len(LOCAL_ASSETS)}


@app.post("/api/v1/internal/resolve")
async def resolve(req: ResolveRequest):
    info = LOCAL_ASSETS.get(req.urn)
    if not info:
        raise HTTPException(404, f"URN not registered: {req.urn}")
    io_type = info["io_manager_type"]
    if io_type == "postgres":
        return {
            "source_type": "postgres",
            "physical_uri": (
                f"postgres://{PG_HOST}:{PG_PORT}/{info['schema']}/{info['table']}"
            ),
            "credentials": {
                "username": PG_USER,
                "password": PG_PASSWORD,
                "database": PG_DATABASE,
            },
        }
    if io_type == "clickhouse":
        return {
            "source_type": "clickhouse",
            "physical_uri": (
                f"clickhouse://{CH_HOST}:{CH_PORT}/{info['schema']}/{info['table']}"
            ),
            "credentials": {
                "username": CH_USER,
                "password": CH_PASSWORD,
                "database": CH_DATABASE,
            },
        }
    if io_type in ("s3_parquet", "s3_delta", "s3_iceberg"):
        bucket = info["bucket"]
        prefix = info["prefix"]
        creds = {
            "aws_access_key_id": S3_ACCESS_KEY,
            "aws_secret_access_key": S3_SECRET_KEY,
            "aws_session_token": "",
            "aws_endpoint_url": S3_ENDPOINT_URL,
            "aws_region": S3_REGION,
        }
        # Iceberg needs more than S3 access — also the catalog reference.
        if io_type == "s3_iceberg":
            if "catalog_uri" in info:
                creds["catalog_uri"] = info["catalog_uri"]
            if "table_identifier" in info:
                creds["table_identifier"] = info["table_identifier"]
            creds["warehouse_uri"] = f"s3://{bucket}/{prefix}"
            creds["catalog_type"] = info.get("catalog_type", "sql")
        return {
            "source_type": io_type,
            "physical_uri": f"s3://{bucket}/{prefix}",
            "credentials": creds,
        }
    raise HTTPException(400, f"unsupported io_type={io_type}")
