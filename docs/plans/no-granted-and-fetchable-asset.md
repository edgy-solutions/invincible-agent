---
id:         no-granted-and-fetchable-asset
status:     open
owner:      human
blocked-on: A CHOICE BETWEEN TWO CHEAP PATHS, either of which closes it — (a) grant alice a read on `publog/p_cage` (a `policy/asset_grants.yaml` write plus sync; the live Topaz write is a human act), or (b) fix the HTTP 404 on the already-granted `mesh_demo_customers` (the queued `minio-svc` values change). (a) is minutes; (b) also retires a demo-day risk.
closed-by:
code-site:  policy/asset_grants.yaml, helm/invincible-agent/values.yaml
repo:       invincible-agent
summary:    NO ASSET ON SANDBOX IS BOTH GRANTED AND FETCHABLE — p_cage was materialized 2026-08-15 and has no read grant; the one granted asset returns HTTP 404 on read. So the data path cannot serve ANY query, which makes item 1's success arm unwitnessable and Tier-3 row 8 impossible. Discovered by the live witness, named on no board line, and it sits AHEAD of da-collects-before-filtering.
---

# There is no query the data path can serve

**Found 2026-08-18 by [[ui-renders-honest-failure-as-answer]]'s live witness**, which set out to
show three envelope outcomes rendering distinctly and could only show the failures — because the
success case has no substrate to succeed on.

| asset | granted? | fetchable? |
|---|---|---|
| `iagent-minio.publog-lake/publog/p_cage` | **NO** — materialized 2026-08-15T17:45Z, no grant exists | yes (data is in MinIO) |
| `mesh_demo_customers` | yes — `alice@example.com` | **NO** — read returns HTTP 404 |
| `gold.sales.customers_gold` | yes — `alice@example.com` | untested |

`policy/asset_grants.yaml` grants exactly **two** assets, both to alice. Neither is the one this
session materialized, and the one that was probed does not fetch.

## Why this is its own item rather than a note on another

**It is a precondition for two board items and appears in neither.**

* [[ui-renders-honest-failure-as-answer]]'s definition of done is *"a VALUE on the UI, for a query
  the data path can serve"*. There is no such query, so the packet cannot close however correct
  its code is.
* [[da-collects-before-filtering]] repairs **how** a table is read — `.collect()` pulling an
  entire dataset into RAM for a `LIMIT 2`. **There is no point fixing how a table is read while no
  table can be read at all**, which is why this sits ahead of it in the ordering.

It is also invisible to every existing check. Nothing goes red: the entitlement plane correctly
denies, the catalog correctly resolves, the data plane correctly 404s. Each component is right and
the composition serves nothing — the shape [[a-green-check-proves-only-its-scope]] describes, at
the level of a system rather than a guard.

## The two paths, and what each also buys

**(a) Grant alice a read on `p_cage`** — a `policy/asset_grants.yaml` write plus sync. Minutes.
Per the standing sandbox-entitlement finding the live Topaz write is a human act, and
`asset_grants.yaml`'s own header warns against *reactive* granting-on-denial: this is a
deliberate, authorized fixture grant for a demo asset, which is the shape the two existing rows
already take. Buys the success arm immediately.

**(b) Fix the 404 on `mesh_demo_customers`** — the queued `minio-svc` values change. Also retires
a demo-day risk, because a URN that resolves in the catalog and 404s on read is exactly
[[broker-endpoint-env-divergence]] / [[urn-reconciliation-guard]]: *"every identity defect this
week produced the same silent 404."* Slower, worth more.

**They are not exclusive and (a) does not substitute for (b)** — a granted `p_cage` proves the
path end to end while leaving the 404 live for whatever else hits it.

## A NEW ASSET IS BORN UNREADABLE, and that is the general fact worth keeping

`p_cage` was materialized through the sanctioned pipeline, landed in MinIO, and was emitted to
DataHub by the `datahub_sensor` — every step correct — and it is **still unreadable by anyone**,
because materialization does not grant. That is right (a pipeline should not mint authority), and
it means **every future demo asset carries the same silent step**. Worth a line in
[docs/demo-day-runbook.md](../demo-day-runbook.md): a freshly ingested asset needs a grant before
anyone can ask about it, and the failure mode is an `access_denied` that reads like the system
being broken.

## Acceptance

- One named identity asks one question about one asset and **gets rows** — which is also
  [[ui-renders-honest-failure-as-answer]]'s success arm, witnessed for the first time.
- The runbook records the born-unreadable step so the next materialized asset does not repeat it.
