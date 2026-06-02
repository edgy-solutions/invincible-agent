# /// script
# requires-python = ">=3.10"
# dependencies = ["acryl-datahub>=0.15.0,<0.16"]
# ///
"""Seed DataHub with a small but realistic canned catalog.

What gets emitted (matches the question shapes the Engine D query suite
asks about):

    Datasets (in lineage chain — Postgres source → Bronze → Silver → Gold)
      postgres.prod.sales.orders_raw
      postgres.prod.sales.customers_raw
      snowflake.bronze.sales.orders                upstream: orders_raw
      snowflake.bronze.sales.customers             upstream: customers_raw
      snowflake.silver.sales.orders_fact           upstream: orders, customers
      snowflake.silver.sales.customers_silver      upstream: customers
      snowflake.gold.sales.revenue_summary         upstream: orders_fact
      snowflake.gold.sales.customers_gold          upstream: customers_silver

    Dashboards (Superset)
      Sales Performance Q1   - uses revenue_summary
      Revenue by Region      - uses revenue_summary, orders_fact
      Customer 360           - uses customers_gold

    Charts (Superset)
      Top Customers          - uses customers_gold
      Monthly Revenue        - uses revenue_summary
      Order Volume Trend     - uses orders_fact

    Tags
      pii on customers_raw, customers (bronze), customers_silver,
            customers_gold, Customer 360 dashboard

    Owners (CorpUsers)
      alice@company.com   — owns gold-layer + Customer 360
      bob@company.com     — owns silver-layer + Sales Performance Q1
      charlie@company.com — owns bronze-layer + Revenue by Region
      dave@company.com    — owns the postgres raw layer

    Last-updated timestamps on every dataset
      Set to a mix of "yesterday" and "stale" (>30 days ago).

Run via:
    kubectl -n sandbox port-forward svc/datahub-datahub-gms 18090:8080 &
    uv run scripts/seed_datahub_catalog.py
"""
from __future__ import annotations

import os
import sys
import time
from typing import Sequence

from datahub.emitter.mce_builder import (
    make_dataset_urn,
    make_dashboard_urn,
    make_chart_urn,
    make_user_urn,
    make_tag_urn,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    AuditStampClass,
    ChangeAuditStampsClass,
    ChangeTypeClass,
    ChartInfoClass,
    ChartTypeClass,
    DashboardInfoClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    DateTypeClass,
    GlobalTagsClass,
    NumberTypeClass,
    OperationClass,
    OperationTypeClass,
    OtherSchemaClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
    StringTypeClass,
    TagAssociationClass,
    UpstreamClass,
    UpstreamLineageClass,
)


GMS = os.getenv("DATAHUB_GMS_URL", "http://localhost:18090")
NOW_MS = 1780400000000  # fixed timestamp so the seed is deterministic
DAY_MS = 24 * 60 * 60 * 1000
STALE = NOW_MS - 45 * DAY_MS    # >30 days ago
RECENT = NOW_MS - 1 * DAY_MS    # yesterday


def make_postgres_urn(table: str) -> str:
    return make_dataset_urn(platform="postgres", name=table, env="PROD")


def make_snowflake_urn(table: str) -> str:
    return make_dataset_urn(platform="snowflake", name=table, env="PROD")


def make_superset_dashboard_urn(name: str) -> str:
    return make_dashboard_urn(platform="superset", name=name)


def make_superset_chart_urn(name: str) -> str:
    return make_chart_urn(platform="superset", name=name)


# ---------------------------------------------------------------------------
# Dataset definitions (urn, description, columns, owner, last_updated, tags)
# ---------------------------------------------------------------------------
DATASETS = [
    # PG source-of-truth
    {
        "urn": make_postgres_urn("prod.sales.orders_raw"),
        "name": "orders_raw",
        "description": "Raw order events captured from the operational "
                       "Postgres database. Source-of-truth for all sales "
                       "data downstream.",
        "owner": "dave@company.com",
        "last_updated_ms": RECENT,
        "tags": [],
        "columns": [
            ("order_id", "STRING", "Primary key. Order identifier."),
            ("customer_id", "STRING", "FK to customers_raw.customer_id."),
            ("order_amount", "NUMBER", "Total order amount in USD."),
            ("order_date", "DATE", "When the order was placed."),
        ],
        "upstream": [],
    },
    {
        "urn": make_postgres_urn("prod.sales.customers_raw"),
        "name": "customers_raw",
        "description": "Raw customer records captured from the operational "
                       "Postgres database. Contains PII.",
        "owner": "dave@company.com",
        "last_updated_ms": RECENT,
        "tags": ["pii"],
        "columns": [
            ("customer_id", "STRING", "Primary key."),
            ("name", "STRING", "Customer full name. PII."),
            ("email", "STRING", "Customer email address. PII."),
            ("created_at", "DATE", "Account creation date."),
        ],
        "upstream": [],
    },
    # Bronze
    {
        "urn": make_snowflake_urn("bronze.sales.orders"),
        "name": "bronze.sales.orders",
        "description": "Bronze copy of orders_raw. Type-corrected, no business "
                       "logic yet.",
        "owner": "charlie@company.com",
        "last_updated_ms": RECENT,
        "tags": [],
        "columns": [
            ("order_id", "STRING", ""),
            ("customer_id", "STRING", ""),
            ("order_amount", "NUMBER", ""),
            ("order_date", "DATE", ""),
        ],
        "upstream": [make_postgres_urn("prod.sales.orders_raw")],
    },
    {
        "urn": make_snowflake_urn("bronze.sales.customers"),
        "name": "bronze.sales.customers",
        "description": "Bronze copy of customers_raw.",
        "owner": "charlie@company.com",
        "last_updated_ms": RECENT,
        "tags": ["pii"],
        "columns": [
            ("customer_id", "STRING", ""),
            ("name", "STRING", ""),
            ("email", "STRING", ""),
            ("created_at", "DATE", ""),
        ],
        "upstream": [make_postgres_urn("prod.sales.customers_raw")],
    },
    # Silver
    {
        "urn": make_snowflake_urn("silver.sales.orders_fact"),
        "name": "silver.sales.orders_fact",
        "description": "Fact table joining orders with customer attributes. "
                       "Used by dashboards.",
        "owner": "bob@company.com",
        "last_updated_ms": RECENT,
        "tags": [],
        "columns": [
            ("order_id", "STRING", "PK."),
            ("customer_id", "STRING", "FK to customers_silver.customer_id."),
            ("order_amount", "NUMBER", ""),
            ("order_date", "DATE", ""),
            ("region", "STRING", "Derived from customer billing address."),
        ],
        "upstream": [
            make_snowflake_urn("bronze.sales.orders"),
            make_snowflake_urn("bronze.sales.customers"),
        ],
    },
    {
        "urn": make_snowflake_urn("silver.sales.customers_silver"),
        "name": "silver.sales.customers_silver",
        "description": "Cleaned customer table with derived attributes "
                       "(tenure_days, lifetime_value). Contains PII.",
        "owner": "bob@company.com",
        "last_updated_ms": RECENT,
        "tags": ["pii"],
        "columns": [
            ("customer_id", "STRING", "PK."),
            ("name", "STRING", "PII."),
            ("email", "STRING", "PII."),
            ("tenure_days", "NUMBER", ""),
            ("lifetime_value", "NUMBER", ""),
        ],
        "upstream": [make_snowflake_urn("bronze.sales.customers")],
    },
    # Gold
    {
        "urn": make_snowflake_urn("gold.sales.revenue_summary"),
        "name": "gold.sales.revenue_summary",
        "description": "Daily revenue rollup by region. Powers the Revenue "
                       "by Region and Sales Performance Q1 dashboards.",
        "owner": "alice@company.com",
        "last_updated_ms": RECENT,
        "tags": [],
        "columns": [
            ("date", "DATE", "PK part."),
            ("region", "STRING", "PK part."),
            ("revenue_usd", "NUMBER", ""),
            ("order_count", "NUMBER", ""),
        ],
        "upstream": [make_snowflake_urn("silver.sales.orders_fact")],
    },
    {
        "urn": make_snowflake_urn("gold.sales.customers_gold"),
        "name": "gold.sales.customers_gold",
        "description": "Customer table with computed segments and PII masked "
                       "for analytics access.",
        "owner": "alice@company.com",
        "last_updated_ms": STALE,  # intentionally stale
        "tags": ["pii"],
        "columns": [
            ("customer_id", "STRING", "PK."),
            ("name_masked", "STRING", "Masked customer name."),
            ("region", "STRING", ""),
            ("segment", "STRING", "Computed segment (HIGH_VALUE, AT_RISK, ...)."),
            ("lifetime_value", "NUMBER", ""),
        ],
        "upstream": [make_snowflake_urn("silver.sales.customers_silver")],
    },
]


DASHBOARDS = [
    {
        "urn": make_superset_dashboard_urn("sales_performance_q1"),
        "title": "Sales Performance Q1",
        "description": "Quarterly sales performance dashboard. Owned by Bob.",
        "owner": "bob@company.com",
        "charts": [],
        "datasets": [make_snowflake_urn("gold.sales.revenue_summary")],
    },
    {
        "urn": make_superset_dashboard_urn("revenue_by_region"),
        "title": "Revenue by Region",
        "description": "Revenue rollup by region with drill-down to order "
                       "facts.",
        "owner": "charlie@company.com",
        "charts": [],
        "datasets": [
            make_snowflake_urn("gold.sales.revenue_summary"),
            make_snowflake_urn("silver.sales.orders_fact"),
        ],
    },
    {
        "urn": make_superset_dashboard_urn("customer_360"),
        "title": "Customer 360",
        "description": "Per-customer view with segment and lifetime value. "
                       "Contains PII.",
        "owner": "alice@company.com",
        "charts": [],
        "datasets": [make_snowflake_urn("gold.sales.customers_gold")],
        "tags": ["pii"],
    },
]


CHARTS = [
    {
        "urn": make_superset_chart_urn("top_customers"),
        "title": "Top Customers",
        "description": "Top 10 customers by lifetime value.",
        "owner": "alice@company.com",
        "datasets": [make_snowflake_urn("gold.sales.customers_gold")],
    },
    {
        "urn": make_superset_chart_urn("monthly_revenue"),
        "title": "Monthly Revenue",
        "description": "Monthly revenue trend, last 12 months.",
        "owner": "bob@company.com",
        "datasets": [make_snowflake_urn("gold.sales.revenue_summary")],
    },
    {
        "urn": make_superset_chart_urn("order_volume_trend"),
        "title": "Order Volume Trend",
        "description": "Daily order count.",
        "owner": "charlie@company.com",
        "datasets": [make_snowflake_urn("silver.sales.orders_fact")],
    },
]


def _audit_stamp(actor: str = "urn:li:corpuser:datahub", ms: int = NOW_MS) -> AuditStampClass:
    return AuditStampClass(time=ms, actor=actor)


def _datahub_type_for(coltype: str) -> SchemaFieldDataTypeClass:
    cls = {
        "STRING": StringTypeClass,
        "NUMBER": NumberTypeClass,
        "DATE": DateTypeClass,
    }.get(coltype, StringTypeClass)
    return SchemaFieldDataTypeClass(type=cls())


def emit_dataset(emitter: DatahubRestEmitter, ds: dict) -> None:
    urn = ds["urn"]
    platform = "postgres" if "postgres" in urn else "snowflake"
    # Properties (description, custom props with lastModified)
    props = DatasetPropertiesClass(
        description=ds["description"],
        customProperties={
            "lastUpdatedMs": str(ds["last_updated_ms"]),
            "owner": ds["owner"],
        },
        lastModified=_audit_stamp(make_user_urn(ds["owner"]),
                                  ds["last_updated_ms"]),
        name=ds["name"],
    )
    emitter.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=urn, aspect=props,
        changeType=ChangeTypeClass.UPSERT,
    ))

    # Ownership
    owner_urn = make_user_urn(ds["owner"])
    emitter.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=OwnershipClass(owners=[OwnerClass(
            owner=owner_urn,
            type=OwnershipTypeClass.DATAOWNER,
        )], lastModified=_audit_stamp()),
    ))

    # Schema (columns)
    fields = [
        SchemaFieldClass(
            fieldPath=col_name,
            type=_datahub_type_for(col_type),
            nativeDataType=col_type,
            description=col_desc,
        )
        for (col_name, col_type, col_desc) in ds["columns"]
    ]
    emitter.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=SchemaMetadataClass(
            schemaName=ds["name"],
            platform=f"urn:li:dataPlatform:{platform}",
            version=0,
            hash="",
            platformSchema=OtherSchemaClass(rawSchema=""),
            fields=fields,
        ),
    ))

    # Tags
    if ds["tags"]:
        emitter.emit_mcp(MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=GlobalTagsClass(tags=[
                TagAssociationClass(tag=make_tag_urn(t)) for t in ds["tags"]
            ]),
        ))

    # Lineage
    if ds["upstream"]:
        emitter.emit_mcp(MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=UpstreamLineageClass(upstreams=[
                UpstreamClass(
                    dataset=u,
                    type=DatasetLineageTypeClass.TRANSFORMED,
                    auditStamp=_audit_stamp(),
                )
                for u in ds["upstream"]
            ]),
        ))

    # Last-update Operation aspect — what makes "stale" queries work
    emitter.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=urn,
        aspect=OperationClass(
            timestampMillis=ds["last_updated_ms"],
            operationType=OperationTypeClass.UPDATE,
            lastUpdatedTimestamp=ds["last_updated_ms"],
            actor=owner_urn,
        ),
    ))


def emit_dashboard(emitter: DatahubRestEmitter, d: dict) -> None:
    owner_urn = make_user_urn(d["owner"])
    stamp = AuditStampClass(time=NOW_MS, actor=owner_urn)
    info = DashboardInfoClass(
        title=d["title"],
        description=d["description"],
        charts=d.get("charts", []),
        datasets=d.get("datasets", []),
        lastModified=ChangeAuditStampsClass(created=stamp, lastModified=stamp),
        lastRefreshed=NOW_MS,
        customProperties={"owner": d["owner"]},
    )
    emitter.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=d["urn"], aspect=info,
    ))
    emitter.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=d["urn"],
        aspect=OwnershipClass(owners=[OwnerClass(
            owner=make_user_urn(d["owner"]),
            type=OwnershipTypeClass.DATAOWNER,
        )], lastModified=_audit_stamp()),
    ))
    if d.get("tags"):
        emitter.emit_mcp(MetadataChangeProposalWrapper(
            entityUrn=d["urn"],
            aspect=GlobalTagsClass(tags=[
                TagAssociationClass(tag=make_tag_urn(t)) for t in d["tags"]
            ]),
        ))


def emit_chart(emitter: DatahubRestEmitter, c: dict) -> None:
    owner_urn = make_user_urn(c["owner"])
    stamp = AuditStampClass(time=NOW_MS, actor=owner_urn)
    info = ChartInfoClass(
        title=c["title"],
        description=c["description"],
        inputs=c.get("datasets", []),
        type=ChartTypeClass.LINE,
        lastModified=ChangeAuditStampsClass(created=stamp, lastModified=stamp),
        lastRefreshed=NOW_MS,
        customProperties={"owner": c["owner"]},
    )
    emitter.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=c["urn"], aspect=info,
    ))
    emitter.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=c["urn"],
        aspect=OwnershipClass(owners=[OwnerClass(
            owner=make_user_urn(c["owner"]),
            type=OwnershipTypeClass.DATAOWNER,
        )], lastModified=_audit_stamp()),
    ))


def main() -> int:
    print(f"[seed] connecting to GMS at {GMS}")
    emitter = DatahubRestEmitter(gms_server=GMS, retry_max_times=2, retry_status_codes=[429, 502, 503, 504])
    emitter.test_connection()
    print("[seed] connection OK")

    for ds in DATASETS:
        print(f"  -> dataset: {ds['name']}")
        emit_dataset(emitter, ds)
    for d in DASHBOARDS:
        print(f"  -> dashboard: {d['title']}")
        emit_dashboard(emitter, d)
    for c in CHARTS:
        print(f"  -> chart: {c['title']}")
        emit_chart(emitter, c)

    print(f"[seed] emitted {len(DATASETS)} datasets, "
          f"{len(DASHBOARDS)} dashboards, {len(CHARTS)} charts")
    print("[seed] giving the search indexer 8s to catch up")
    time.sleep(8)
    print("[seed] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
