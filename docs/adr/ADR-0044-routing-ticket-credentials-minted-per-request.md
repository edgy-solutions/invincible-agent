# ADR-0044 — A routing ticket carries only credentials the broker minted for that request

**Status:** Accepted (2026-08-26). See **Amendment 2026-08-26** below — the decision stands unchanged;
the *mechanism* it named was corrected before implementation began.
**Date:** 2026-08-26
**Deciders:** Platform team
**Related:**
  - [ADR-0025](ADR-0025-instance-plane-access-control-as-provenance.md) — instance-plane access control.
    That ADR governs the **decision**: who may read an instance. This one governs **what the decision
    hands over**. An entitlement correctly computed and then satisfied with an over-broad credential is
    the same failure as no entitlement check, arriving one step later.
  - [ADR-0026](ADR-0026-persona-entitlement-topaz-authorization.md) — Topaz as the entitlement authority.
    The row/column narrowing this ADR moves server-side originates there.
  - [ADR-0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) — the data plane. The
    routing ticket is that plane's hand-off object; this constrains its contents.
  - Plan item `[[broker-advertises-unminted-credential]]` — the finding, the evidence, and the order of work.
  - Plan item `[[jupyter-user-token-data-access]]` — gated by this ADR, per backend.

## Context

The mesh's data plane hands a consumer a **routing ticket**: `source_type`, `physical_uri`,
`credentials`, plus any `allowed_columns` / `row_filters` Topaz grafted on. The consumer reads the
bytes itself. Nothing streams through the control plane, which is the property that makes the design
worth having.

The domain broker has **two paths** that produce a ticket, and they do not agree.

`resolve_asset`'s fallback path mints: `sts.assume_role` with an inline policy scoped to
`s3:GetObject` on `bucket/prefix/*`, `ListBucket` narrowed by `s3:prefix`, `DurationSeconds=3600`
(`dag_tools/domain_broker/main.py:700-735`). Temp key, one asset, one hour.

The **mesh-publishing protocol** path — `physical_coordinates()`, which every modern dag-tools IO
manager implements — short-circuits it. The broker stores the IO manager's ticket verbatim and
returns it before the STS code is reached (`main.py:680`):

```python
ticket = asset_info.get("_routing_ticket")
if ticket:
    return ticket          # everything below never runs
```

What those IO managers put in it is their own configured credential
(`arrow.py:358`, `sql.py:374`) — and **that credential necessarily writes**, because it is the one
the IO manager materializes assets with. So an authorized reader of one asset receives a
long-lived, write-capable credential to the store, and `allowed_columns` / `row_filters` are applied
afterwards **in the caller's own process**, where the caller may simply not apply them.

**This is a regression by convergence, not a design failure.** The scoping was designed, built, and
works. A newer, faster path bypassed it and never had it. Recording the distinction matters: read as
a design failure, the next contributor rebuilds what already exists.

A sibling defect on the same path made the constraint visible: the ticket relayed
`aws_endpoint_url` as a namespace-local hostname (`arrow.py:364`), resolvable where the producer
runs and nowhere else. Same missing idea — **a ticket is consumed somewhere else.**

Per-user notebook access makes this urgent rather than theoretical. Today the blast radius is
whoever can reach Engine DA; the JupyterHub work would hand tickets to every analyst.

## Decision

**A routing ticket may contain only credentials the broker minted for that request.**

**The broker mints. Producers advertise coordinates.** That division is part of the decision, not an
implementation detail — see the amendment below for why the original wording got it wrong.

Concretely, the credential in a ticket must be:

1. **minted by the broker, per request** — never an echo of a producer's configured credential;
2. **scoped to the asset** named in the ticket, not the store;
3. **expiring with the access window**, not a fixed default;
4. **incapable of writing.**

**Nothing about pipeline authoring changes.** IO managers keep their configured write credentials
and go on using them exactly as they do today — a pipeline materializing an asset needs write
access, and that is correct. What changes is only that those credentials stop appearing in a
ticket. Producers are not reconfigured; the authoring path is untouched.

**Minting authority stays in one component.** The broker already holds the authorization decision,
so it is already the right place to hold the power to mint against it. The alternative the original
wording implied — IO managers minting — would distribute STS-assume / role-grant privilege across
every user-deployment pod in the fleet, replacing one powerful credential with dozens. That is a
worse posture than the defect.

And the invariant that generates all four:

> **The credential that writes assets and the credential advertised in a ticket must never be the
> same object.**

Everything else in the ticket inherits the same law. A hostname must be an FQDN, because a
namespace-local name is a coordinate that means different things depending on where the reader
stands.

**Minting is store-specific; the constraint is uniform.** A backend therefore **declares its mode**
in the ticket rather than every backend pretending it can mint:

| backend | mode | primitive | narrowing enforced |
|---|---|---|---|
| MinIO / S3 | `mint-sts` | `AssumeRole` + inline policy; presigned URLs for pure reads | storage-side (prefix) |
| ClickHouse | `mint-role` | role + `CREATE ROW POLICY`; token-bound role where available | **server-side** |
| PostgreSQL | `mint-role` | `SET LOCAL ROLE` on a broker-held connection, or short-lived role (`VALID UNTIL`); native RLS. Not gated on PG18 | **server-side** |
| Snowflake | `mint-role` | key-pair JWT / OAuth token scoped to a role | **server-side** |
| Superset | `proxy-only` | not a store — a consumer holding its own connections | its own RLS |

`proxy-only` is a first-class answer, not a failure: the broker executes and returns rows. **A store
that cannot mint says so, and gets the proxy path.** A backend that declares nothing does not
advertise.

## Amendment 2026-08-26 — `physical_coordinates()` cannot be where minting happens

Caught while planning the implementation, before any code was written. **The decision above is
unchanged. Decision points 1–4 and the invariant stand exactly as stated.** What was wrong is the
function this ADR named as the place to satisfy them.

`physical_coordinates()` is **not called per request.** It runs once, at broker startup, inside
`load_dagster_definitions()` (`domain_broker/main.py:90`, reached from `:464`), and its return value
is cached in `LOCAL_ASSETS`. `resolve_asset` serves that cached object on every subsequent request.

So a credential minted inside `physical_coordinates()` would be minted **once at startup**, shared
by every caller for the life of the process, and would expire an hour in — while the broker went on
serving it and reporting `{"status": "ok"}`. That is strictly worse than the defect this ADR exists
to fix: today's echoed credential is at least *functional*. Implementing the ADR literally would
have shipped a time bomb that passes every test written against a freshly started broker.

**The corrected mechanism — split the ticket by what is time-bound:**

| | produced by | when | contents |
|---|---|---|---|
| **coordinates** | `physical_coordinates()` | once, at load | `source_type`, `physical_uri` (FQDN), `mode`, and the **scope** a credential must be minted against (bucket/prefix, or schema/table + role) |
| **credential** | the broker, in `resolve_asset` | **per request** | minted against that scope, for this caller, expiring with this access window |

Caching the coordinates is correct — none of it is time-bound or caller-specific. Caching a
credential is the bug. The split is what makes "minted per request" true rather than aspirational.

**Consequence for the protocol contract:** `physical_coordinates()` returns **no credentials at
all**. Its current `credentials` key is removed rather than narrowed — an IO manager has no business
producing one, since it cannot know the caller or the window. This is a cleaner contract than the
original ADR implied and it removes the temptation that produced the defect: the IO manager stops
being asked for something only the broker can correctly supply.

### The wording implied the wrong owner, which is the more dangerous half of the error

"`physical_coordinates()` must return a minted credential" reads as **the IO manager must mint**.
An IO manager runs inside a Dagster pipeline pod. Teaching it to mint would put STS-assume or
role-grant privilege in **every user deployment in the fleet** — replacing one powerful credential
with dozens, and moving minting authority away from the only component that holds the
authorization decision it should be scoped to. The Decision section above now states the ownership
explicitly for that reason.

The fix this reframing produces is also **smaller**: "make the protocol path reach the minting code
that already exists in `resolve_asset`," rather than "teach every IO manager to mint."

### A second win the original draft did not claim

Because the ticket is built at load time and cached, **producer write credentials are currently
resident in the broker's process memory for its entire uptime** (`LOCAL_ASSETS`, `main.py:37`) and
re-transmitted on every resolve. Minting at issuance means that cache holds **coordinates only** —
there is no long-lived secret in the broker's memory to leak via a crash dump, a debug endpoint, or
a `/resolve` response replayed from logs.

*(Precisely: `LOCAL_ASSETS` is an in-process dict. The gateway's Redis holds only
`mesh_route:{urn} → broker_url` and never the ticket, so this is a process-memory exposure, not a
shared-store one.)*

*Why this is an amendment and not a new ADR: the decision, the invariant, and the acceptance criteria
are untouched. Only the implementation seam and the ownership wording moved. A superseding ADR would
imply the ruling changed.*

## Consequences

**Wins.**

For every `mint-role` backend the row/column narrowing moves **server-side**, where the caller
cannot remove it. Topaz's `allowed_columns` / `row_filters` stop being an advisory convention
applied by a cooperating client and become an enforced boundary; the client-side application in
`cortex_data/client.py` degrades to defense-in-depth. That is what ADR-0025's decision always
implied and what an object store could not deliver.

A leaked ticket expires. A stolen ticket reads one asset. Neither can write.

**Costs we accept.**

Minting is per-request work on the broker's hot path — an STS call or a role grant before the
consumer sees a ticket. Ticket issuance stops being a pure lookup.

`mint-role` backends acquire **lifecycle work**: short-lived users and roles must be reaped, and the
broker dying mid-request must not leak them. This is designed, not assumed.

`proxy-only` backends change the **data path**, not merely the credential — bytes flow through the
broker for those stores. Chosen deliberately per backend.

**`mode` is invisible to the consumer, and that is a deliberate property of this decision, not an
accident.** Polars has no lazy database scan, so `CortexDataClient` already materializes both SQL
backends and wraps the result in `.lazy()`. For a table-backed asset, "client runs the SQL" and
"broker runs the SQL" are indistinguishable in the return type — both eager, query-in, rows-out. The
mode field therefore stays a transport detail between broker and client and never reaches a
notebook. **If a future backend's mode would change what a caller writes, that is a signal the mode
vocabulary has outgrown this ADR** — see indicators below.

(The distinction that *is* visible to callers — file-backed assets pushing down lazily versus
table-backed assets materializing a full `SELECT *` behind a `.lazy()` wrapper — predates this ADR
and is out of its scope.)

The rollout is **per backend, not global**. Notebook access lights up backend by backend as each
column goes green — MinIO in weeks rather than everything waiting on Snowflake.

**A trap this creates, named so it is not discovered.** For ClickHouse, read-only is a settings-
profile property (`readonly=1`/`2`) *separate* from table grants. A minted role with correct grants
and an inherited permissive profile satisfies half this ADR and looks whole. Grants and profile are
two independent claims; pin both.

## Alternatives considered

- **Patch MinIO to mint STS and stop there.** Rejected: MinIO is the backend we hit first, not the
  scope of the defect. A MinIO-shaped fix leaves four backends silently wrong and reads later as
  though the class was handled.
- **Keep echoing, and rely on client-side filters.** Rejected: that is the status quo, and it makes
  read-only, row masking, column masking, and the asset boundary all advisory against a caller who
  holds a write-capable key.
- **Narrow the IO manager's own credential so echoing is safe.** Rejected: the IO manager must write
  to materialize. A credential that is safe to advertise cannot be the one that authors.
- **Route all reads through the broker (proxy everything).** Rejected as the default: it discards
  the direct-read property the data plane exists for. Retained as the honest mode for backends that
  cannot mint.
- **Presigned URLs everywhere.** Kept for pure-read S3 cases — tightest option, no credential in the
  consumer at all — but it does not generalize to the SQL backends.

## Indicators for revisiting

- A backend arrives whose minting primitive fits none of `mint-sts` / `mint-role` / `proxy-only`,
  suggesting the mode vocabulary is too narrow.
- **A backend's mode becomes visible in the client's return type or in what a caller must write.**
  The mode is transport today only because Polars materializes SQL reads anyway; a backend offering
  genuine lazy pushdown, or a proxy path that cannot be made eager, would break that and force the
  mode-transparency question this ADR currently gets for free.
- **Per-request minting meets real concurrency.** Dozens of analysts scanning object-store assets
  means many `AssumeRole` calls per hour; `mint-role` backends face the equivalent as role-churn
  contention. Measure the store's limits *before* the load arrives. The mitigation — short-lived
  caching of minted credentials keyed by (caller, asset, window) — is **a deliberate weakening of
  decision point 1** and must be decided explicitly with a stated window, not drifted into under
  load.
- Reaper complexity for `mint-role` backends exceeds the value over `proxy-only` for those stores.
- The mesh gains a consumer that cannot hold a credential at all, making `proxy-only` the default
  rather than the exception.
