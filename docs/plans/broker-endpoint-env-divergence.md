---
id:         broker-endpoint-env-divergence
status:     open
owner:      human
blocked-on: the source of the stuck PUBLOG_S3_BUCKET_URL is unfound — absent from `helm template`, absent from the image, present in the live Deployment. Removed by hand to unblock; will recur if a values layer still supplies it.
closed-by:
code-site:  helm/invincible-agent/values.yaml:603
repo:       invincible-agent
summary:    A domain broker re-loads the code location's Definitions in its OWN pod, so every env var that shapes an asset key must match between the two — and three did not, each producing an identical-looking 404. The asset key is assembled from env nobody owns, and identity silently follows any of it.
---

# The asset key is assembled from env vars, and nothing declares that

The domain broker does not reference the code location's configuration — it re-loads the same
`Definitions` in its own process (`domain_broker/main.py:145`). Every resource is constructed
twice, from two pods' env. Any divergence produces a different asset key, therefore a
different URN, therefore a routing key nothing can match.

Three variables feed one identity, and at work each was wrong independently:

| variable | feeds | was | should be |
|---|---|---|---|
| `AWS_ENDPOINT_URL` | platform instance, via `split_endpoint_instance` | `iagent-minio` (sandbox default) | `minio-svc` |
| `PUBLOG_S3_BUCKET_URL` | bucket, via `_full_key_prefix` | `s3://minio-svc.publog-lake` | `s3://publog-lake` |
| `AWS_ACCESS_KEY_ID` / `SECRET` | the credentials the broker MINTS INTO the ticket | sandbox literals | the work MinIO's |

Each was found separately, each cost a debugging cycle, each presented as the same 404.

## Three specific traps, all live

**The broker issues credentials it never uses.** It does not read data — `pl.scan_parquet`
runs in Engine DA — but `_ticket()` copies the broker's `aws_access_key_id` / `secret` /
`endpoint_url` into the ticket, and DA reads with exactly those. So the broker must be
configured as though it could read.

**`s3://minio-svc.publog-lake` is a natural mistake.** The DataHub name reads
`minio-svc.publog-lake`, which looks like a bucket and is already `<instance>.<bucket>`
joined. Putting it in the bucket URL applies the instance twice —
`minio-svc.minio-svc.publog-lake/publog/p_cage`.

**`PUBLOG_S3_BUCKET` is read by nothing.** The chart sets it in all four env blocks
(`values.yaml` 570, 613, 655, 703). pub-tools only ever reads `PUBLOG_S3_BUCKET_URL`. A
setting that looks configured and is not — same class as the `TOPAZ_URL` /
`TOPAZ_AUTHORIZER_URL` mismatch, and as `ENGINE_A_CLIENT_SECRET` declared-but-unwired.

## The unfound part — do not close without it

`PUBLOG_S3_BUCKET_URL=s3://minio-svc.publog-lake` was in the LIVE Deployment spec and in
neither `helm template` output, the rendered chart, nor the pub-tools image (whose Dockerfile
is generated in CI and sets no such var). The broker template has NO `envFrom` — its env comes
only from `userDeployments.<name>.broker.env` — so a values layer is the only path the chart
offers, and `helm get values -a` did not show it.

Removed by hand to unblock. **Unresolved: whether a values layer still supplies it**, in which
case the next `helm upgrade` reinstates it. The read that settles it is
`helm get manifest <release> -n <ns> | grep -B40 PUBLOG_S3_BUCKET_URL` — present means Helm
rendered it and the source is in the values layering; absent means something applied it
outside Helm (which Helm's three-way merge then preserves indefinitely, because it manages
only keys its own manifests mention).

## The durable repair

Not "copy the values into a second place" — that is a second truth that drifts, which is how
all three of these happened. One source per setting, referenced by both pods: a Secret for the
credentials, one values key for the endpoint and bucket URL. The
[[bootstrap-state-debt]] one-master rule, applied to a resource config instead of a store.

[[urn-reconciliation-guard]] catches all three of these identically — a registered URN that
does not resolve in DataHub is the same alarm for an endpoint drift, a bucket drift, or a
platform bug — without anyone having to enumerate which env vars matter.
