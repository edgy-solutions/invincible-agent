---
id:         broker-catalog-urn-derivation
status:     closed
owner:      agent
blocked-on:
closed-by:  a99779f
code-site:  dag_tools/domain_broker/main.py
repo:       dag-tools
summary:    CLOSED — the broker keyed its Redis routes from a derivation forcing platform="dagster", which also flipped the NAME LAYOUT to dotted, so one asset had two irreconcilable identities and every data read 404'd against a routing table that looked fully populated. Proven end-to-end at work 2026-08-15.
---

# The broker and the catalog named the same table differently

    registered   ...(dagster, minio-svc.publog-lake.publog.p_cage, PROD)   ← broker/Redis
    catalogued   ...(s3,      minio-svc.publog-lake/publog/p_cage, PROD)   ← DataHub

`inventory/extractors.py:_derive_urn` forces `platform="dagster"`. That argument does not only
set the platform segment — `asset_keys_to_dataset_urn_converter` selects the NAME LAYOUT from
it, and `dagster` is absent from `FILESYSTEM_PLATFORMS`, so it takes the `".".join(asset_key)`
branch. The dotted form is LOSSY: it destroys the boundary between platform instance, bucket
and key prefix, and that boundary is load-bearing — one S3 path on two servers is two tables,
and only the instance segment tells them apart.

## The fix

`physical_urn_for()` mirrors the catalog's own resolution instead of adding a third
derivation. The DataHub sensor reads the platform an asset DECLARED via `destination_name`;
the broker reads `source_type` off the routing ticket the IO manager already publishes — the
same string by construction, as every IO manager states: *"used for BOTH the mesh routing
ticket and the destination_name the catalog sensor reads, so the two cannot drift."* Same
`resolve_platform` table, same `FILESYSTEM_PLATFORMS` list.

The IO manager is now resolved BEFORE identity; it used to be fetched three lines after the
URN was decided, so the one object that knows what an asset physically is sat in scope,
unused. Precedence: explicit `datahub/urn` tag → physical URN → `record.urn`/dagster fallback.
`_derive_urn` keeps its dagster default — that is the right identity for an asset with no
physical location, which is exactly when the physical derivation declines.

## Verification

The central pin asserts the AGREEMENT between the two derivations, not either side's output,
because two independent derivations of one identity is the defect itself. Mutation-tested:
forcing dagster (3 pins fail), removing the derivation (2), inverting precedence (1). 748
dag-tools tests pass; 50 pub-tools tests pass against the bumped dependency.

**Proven at work 2026-08-15**, which is what actually closes this: the registered key became
`...(s3,minio-svc.publog-lake/publog/p_cage,PROD)`, character-identical to the URN the
resolver hands the agent, and the query returned real rows (`['00000','00001']`).

## What this did NOT fix, and what that taught

The derivation was only one of the inputs to identity. The same asset key is assembled from
env vars — `AWS_ENDPOINT_URL` supplies the platform instance, the bucket URL supplies the
bucket — and each of those diverged separately, each producing an identical-looking 404. See
[[broker-endpoint-env-divergence]], which is the live residual and outlived this fix by two
more debugging cycles.

Two gaps stay documented at the call site: the broker resolves platforms without the
component's `platform_mappings` overrides, and nothing reconciles a registered URN against a
real DataHub entity — [[urn-reconciliation-guard]].
