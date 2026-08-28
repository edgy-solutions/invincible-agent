---
id:         broker-advertises-unminted-credential
status:     open
owner:      agent
blocked-on: 
closed-by:  
adr:        ADR-0044 — ACCEPTED 2026-08-26, amended same day (physical_coordinates() is load-time, so minting moves to resolve_asset; decision unchanged)
code-site:  dag_tools/io_managers/arrow.py:358, dag_tools/io_managers/sql.py:374, dag_tools/domain_broker/main.py:680
repo:       dag-tools
summary:    HIGH — the mesh-publishing protocol path advertises the PRODUCER'S WRITING CREDENTIAL verbatim, bypassing the scoped-STS minting the broker's own fallback already performs. An authorized reader of one asset receives a long-lived, write-capable key to the whole store. Sibling finding: the same path relays namespace-local hostnames. Both are one missing constraint. [[jupyter-user-token-data-access]] ships behind this, per backend.
---

# The routing ticket carries a credential the broker never minted

**Found 2026-08-26** while wiring per-user notebook access — a user asked whether the
debugging trick that prints a ticket could be used to read the object-store keys. It can.
It does not need the trick.

## FIRST — THIS IS NOT A DESIGN FAILURE. IT IS A REGRESSION BY CONVERGENCE

The framing matters more than the finding, because the finding reads as "nobody thought
about credential scoping" and that is **false**. Somebody did, and built it, and it works.

`resolve_asset` — the broker's fallback path — does exactly the right thing
(`domain_broker/main.py:700-735`): `sts.assume_role` with an **inline policy scoped to
`s3:GetObject` on `bucket/prefix/*`**, a `ListBucket` narrowed by `s3:prefix`, and
`DurationSeconds=3600`. That is a temp-key-per-access-window design, implemented,
committed, working.

What happened is that `physical_coordinates()` — the mesh-publishing protocol, the path
**every modern dag-tools IO manager now uses** — short-circuits it. The broker stores the
IO manager's ticket verbatim under `_routing_ticket` (`main.py:92`) and returns it
untouched before any of the STS code is reached (`main.py:680`):

```python
ticket = asset_info.get("_routing_ticket")
if ticket:
    return ticket          # <- everything below here never runs
```

**The scoping was not removed. It was bypassed by a newer, faster path that never had
it.** Two paths where one forgot. Cite it that way, or the next reader concludes the
original design was careless and rebuilds what already exists.

## The evidence, side by side

| | fallback path (`resolve_asset`) | protocol path (`physical_coordinates`) |
|---|---|---|
| credential | **minted** — `sts.assume_role` per request | **echoed** — the IO manager's configured credential |
| scope | inline policy, `bucket/prefix/*` | whatever the key can reach |
| verbs | `s3:GetObject` + narrowed `ListBucket` | whatever the key can do — **including write** |
| expiry | `DurationSeconds=3600` | none |
| reached when | IO manager does NOT implement the protocol | **every modern IO manager** |

The echo, in the two IO managers that matter:

```python
# arrow.py:358 — S3 / MinIO
common = self.fs.common
credentials = {
    "aws_access_key_id":     common.access_key_id,
    "aws_secret_access_key": common.secret_access_key,
    "aws_region":            common.region or "us-east-1",
}
if common.end_point:
    credentials["aws_endpoint_url"] = common.end_point
```

```python
# sql.py:374 — PostgreSQL / ClickHouse
"credentials": {
    "username": self._config.username,
    "password": self._config.password,
    "database": self._config.database,
},
```

**Note what those credentials necessarily are.** They are the IO manager's own — the ones
it *writes assets with*. They cannot be read-only; materialization would fail. So the
credential advertised to a reader is, by construction, write-capable.

## Severity — worse than the docs' own caveat

`docs/cortex-data-client.md` already names a limitation, honestly:

> the credentials in the ticket grant access to the **whole** object or table. The
> narrowing happens in your process. […] this is a data-plane convention, not a
> storage-enforced boundary. **Anyone holding a ticket holds credentials broader than
> their entitlement.**

That sentence is accurate **for the STS path** — bucket/prefix-scoped rather than
row/column-scoped, read-only, expiring, with masking applied client-side as an advisory
convention. It substantially understates the protocol path, which is broader in three
further dimensions at once:

* **verb** — read-write, because it is the authoring key;
* **scope** — everything that key reaches, not one prefix;
* **time** — no expiry at all.

At that point `allowed_columns`, `row_filters`, read-only, and the asset boundary are
**all advisory**. The client applies Topaz's filters in the caller's own polars session
(`cortex_data/client.py`), which the caller can simply not do. ClickHouse specifically
does *not* get the `apply_security = False` exemption Postgres gets, so its narrowing is
client-side today — and its ticket now also carries the writing DSN.

**Per-user auth makes this more pressing, not less.** Today the blast radius is whoever
can reach Engine DA. [[jupyter-user-token-data-access]] hands the ticket directly to every
analyst with a notebook.

## The sibling finding — the same missing constraint

From the same debugging session: the ticket relayed `aws_endpoint_url` as a
**namespace-local hostname** (`http://minio-svc:9000`, `arrow.py:364`). Resolvable in the
producer's namespace; meaningless from a JupyterHub pod in another one.

Same shape as the credential defect. A ticket is a thing **consumed somewhere else**.
Everything in it — hostname, credential, scope — must be valid and safe *there*, not
merely where it was minted. The endpoint must be an FQDN; the credential must be minted
for the holder.

Two instances of one missing constraint, so they belong in one writeup and one fix.

*(Verified safe: changing `end_point` does NOT move the URN. `physical_urn_for` derives
identity from the asset key and platform, not the endpoint, so the registered route and
the Topaz seeding are unaffected by the FQDN correction.)*

## THE PROTOCOL REQUIREMENT — the thing to approve

> **`physical_coordinates()` must return a credential the broker created for THIS
> request, valid only for this asset's scope and this access window — and never a
> credential that can write.**
>
> **The credential that writes assets and the credential advertised in a ticket must
> never be the same object.**

Stated as a protocol requirement rather than a MinIO patch, deliberately. MinIO is the
backend we happened to hit first; every store has the same two-path problem and a
different minting primitive. A fix written as "make MinIO mint STS" leaves four other
backends silently wrong and reads, later, as though the class was handled.

## Per-backend capability matrix

Minting is store-specific; the constraint is uniform. **Not every store can mint, and that
is a real constraint rather than a gap to paper over** — some backends only support
proxy-the-query. The protocol should let a backend **declare its mode** instead of every
backend pretending it can mint. A store that cannot mint says so, and gets the proxy path.

| backend | mode | primitive | narrowing enforced |
|---|---|---|---|
| MinIO / S3 | `mint-sts` | `AssumeRole` + inline policy; presigned URLs for pure reads | storage-side (prefix); row/col still client-side |
| ClickHouse | `mint-role` | role + `CREATE ROW POLICY`; token-bound role where supported | **server-side** — row policy + column grants |
| PostgreSQL | `mint-role` | `SET LOCAL ROLE` on a broker-held connection, or short-lived role (`VALID UNTIL`); native RLS. **Not gated on PG18** — see below | **server-side** — RLS/CLS |
| Snowflake | `mint-role` | key-pair JWT or OAuth token scoped to a role | **server-side** — row-access policies, secure views |
| Superset | `proxy-only` | not a store — a consumer holding its own connections | its own RLS; ticket ≈ a session, not a credential |

**For stores that can enforce, the ticket's filters stop being advisory.** The
client-side application in `cortex_data/client.py` becomes defense-in-depth redundancy
rather than the only boundary. That is a benefit worth naming: it is what the original
design wanted and could not get from an object store.

### ClickHouse — likely the second backend to light up

Native primitives, stronger enforcement than the current convention, so `mint-role` is
genuinely available: `GRANT` at database/table/column granularity, `CREATE ROW POLICY ...
USING <expr> TO <role>`, `SETTINGS PROFILE` for quotas and read-only, and JWT/OAuth-bound
roles in recent versions.

Two shapes for the mint:

* **(a)** broker holds an admin connection, `GRANT`s a pre-existing per-entitlement role
  to a short-lived user. Works on every version. **Creates lifecycle work** — who drops
  the user, and what happens if the broker dies mid-request. Design the reaper; do not
  assume it. (Same question that bit Dagster this week.)
* **(b)** issue a token bound to a role whose row policy encodes the caller's filters.
  Cleaner, version-dependent.

Either way the role vocabulary should be **derived from Topaz's decision**, not
hand-maintained in two places.

**Caution specific to ClickHouse:** read-only is a settings-profile property
(`readonly=1`/`2`), separate from table grants. It is easy to mint a role with correct
grants and an inherited profile that permits writes or unbounded queries. **Grants and
profile are two independent claims; a ticket that gets one right and inherits the other is
the half-fixed-looking-whole shape.** Pin the profile explicitly.

ClickHouse's matrix row reads: **mint-role, server-side row/column enforcement, profile
pinned, cleanup owned.**

### PostgreSQL — NOT gated on a major-version upgrade

Stated explicitly because the row invites the opposite reading, and a stale premise about a
version prerequisite has cost sequencing time before.

PG18's native OAuth (`oauth` in `pg_hba.conf` + a validator module, built `--with-libcurl`)
is the *ergonomic* path. It is **not a prerequisite**, and today it is not even available
to us — `cortex_data/client.py`'s Postgres branch already tried it and recorded why:

> The intended pattern was PG18 OAUTHBEARER passing the JWT as the bearer token. libpq's
> OAUTHBEARER has no Python API to inject a pre-existing JWT (only device flow or
> `PQsetAuthDataHook` in C), and ADBC postgres doesn't expose the auth hook to Python.

So `SET LOCAL ROLE` on a broker-held connection, plus RLS, is not the fallback — on
current tooling it is **the workable path**, and it delivers the same server-side
enforcement on PG17. The Postgres column can go green without touching the database
version.

## Consequences worth deciding early

1. **Some backends change data path, not just credential.** `proxy-only` means the broker
   executes and returns rows. That is arguably better, but it is a different architecture
   for those stores and should be chosen deliberately.
2. **The notebook gate becomes per-backend, not global.** Per-user tokens are safe where
   minting works and unsafe everywhere else.

### `mode` does NOT leak into user code — checked, and it is why step 1 can ship fast

An earlier draft of this item claimed `proxy-only` imposes a different *client contract*
(no LazyFrame, no `scan_parquet` on a URI) and therefore that `CortexDataClient` needed a
mode-transparent API designed before step 1. **That was wrong, and the correction matters
because it removes the only real objection to shipping the mode declaration quickly.**

Polars has no lazy database scan — no `scan_postgres`, no pushdown into a SQL engine. The
client already materializes both SQL backends and wraps the result:

```python
df = pl.read_database_uri(query, uri=adbc_uri); lf = df.lazy()      # postgres
lf = pl.from_arrow(client.query_arrow(...)).lazy()                  # clickhouse
```

`docs/cortex-data-client.md` says so plainly: *"for the two database backends that is a
`.lazy()` wrapper around an **already-materialized** DataFrame."*

So for a SQL-backed asset, "client connects and runs the SQL" and "broker runs the SQL and
returns rows" are **indistinguishable in the return type** — both eager, both query-in,
rows-out. `mode` is a genuine transport detail. Nothing about it reaches a notebook.

**The distinction that DOES reach notebooks is file-backed vs table-backed, and it already
exists**, today, independent of this ADR: object-store assets get real pushdown; SQL assets
get a `.lazy()` wrapper around a full `SELECT *`. `get_dataframe()` papers over that under
one name and one return type. With dozens of analysts about to build against it, that is
worth making explicit — but it is **a separate item**, not a dependency of this one, and it
must not be bundled into this approval.

## Sequencing — written down, not carried in anyone's head

> **Per-user notebook tokens ship after the broker mints per-request credentials, backend
> by backend, as each column of the matrix goes green.**

[[jupyter-user-token-data-access]] gains this item as a `blocked-on:` dependency —
**per backend**, not wholesale. MinIO going green unblocks notebook access to
MinIO-backed assets in weeks rather than blocking everything on Snowflake. Nobody has to
remember which stores are safe: **the matrix says.**

Note this item is *independent* of [[dag-tools-gateway-unverified-subject]]. That one
governs whether the mesh knows **who** is asking; this one governs **what they are handed
once it decides**. Both gate the notebook work, for different reasons, and neither
substitutes for the other.

## Order of work

| # | step | why this position | status |
|---|---|---|---|
| 0 | **approve the protocol requirement** | it is a protocol change, not a patch; approving the sentence is the decision | **DONE 2026-08-26** |
| 1 | split the ticket: `physical_coordinates()` returns coordinates + `mode` + **scope**, no credentials | per the ADR amendment — minting cannot live in a load-time call | |
| 2 | FQDN constraint on advertised hostnames | same class, one line, unblocks cross-namespace reads immediately | |
| 3 | MinIO/S3 `mint-sts` **in `resolve_asset`**, per request, from the ticket's scope | the existing STS construction is already in the right function | |
| 4 | ClickHouse `mint-role` + pinned profile + reaper | strongest enforcement gain; second column green | |
| 5 | notebook access enabled per green column | [[jupyter-user-token-data-access]] | |
| 6 | Postgres / Snowflake / Superset | remaining columns | |

**Step 3 got easier, not harder, from the amendment.** The STS construction already lives in
`resolve_asset` — the correct function — and has since the fallback path was written. Step 3 is
largely *deleting the short-circuit* and feeding the existing minting code the ticket's declared
scope instead of a placeholder bucket/prefix.

Refinements to build in at step 3 rather than retrofit: derive the policy from **the
ticket's own scope** rather than a broad default, and set expiry to **the access window**
rather than a fixed hour.

## The transitional period's END, stated as a measurable gate

The broker currently **ignores** echoed credentials rather than refusing tickets that carry
them. That is deliberate — DA's pinned `dag_tools-0.1.0` is already behind this repo, and a
hard break would land on a fleet that is not uniformly upgraded, discovering that fact by
taking every read down at once. Ignoring protects the fleet immediately; refusing waits.

A transitional period without a stated end becomes permanent, so:

> **HARD BREAK CONDITION.** The broker refuses any ticket carrying producer credentials once
> `/health.adr0044.echoed_credentials_dropped` reads **zero for every producer class**, held
> for **N days spanning at least one full materialization cycle of every scheduled asset**.

**The cycle qualifier is the load-bearing half, not padding.** A weekly-materialized asset's
producer does not appear in that counter for six days. "Zero for three days" would retire the
transition against a population that simply had not run yet — enumerate-don't-remember,
failing in the one direction that looks like success. N is chosen from the *longest* schedule
in the fleet, not a round number.

**Why the counter is the gate rather than a list of IO managers:** the counter enumerates
producers that actually ran, including out-of-tree ones nobody remembers implementing the
protocol. A remembered list would retire the transition against five known IO managers and
break the sixth.

## Live verification — run 2026-08-26 against sandbox MinIO

`scripts/verify_adr0044_minting.py`, against `iagent-minio` in the `sandbox` namespace
(port-forwarded), bucket `dag-lake`, prefix `mesh_demo`. This exercised the REAL
`_mint_s3`, not a reimplementation — the point being that this code path had **never
executed against a live store**, because the short-circuit meant nothing reached it.

| prediction | confidence | outcome |
|---|---|---|
| **P1** — `assume_role` fails on the placeholder `AWS_ASSUME_ROLE_ARN` | high | **FALSIFIED** — MinIO accepted it |
| **P2** — dropping `RoleArn` succeeds | med-high | not exercised (P1 did not fail) |
| **P3** — read succeeds, write refused | high | **CONFIRMED** — `AccessDenied` on `PutObject` |
| **P4** — another bucket refused | high | **CONFIRMED** — `AccessDenied` on `publog-lake` |

**P1 was wrong, and it was the high-confidence one.** MinIO does not validate a `RoleArn`
it has no configuration for; it derives the session from the caller's own identity
intersected with the inline session policy, and ignores the ARN. The placeholder is
therefore harmless *on MinIO* — which is exactly the kind of thing that would never have
been discovered by reasoning, and is the argument for pre-registering rather than
rationalising afterwards.

**It does not follow that the placeholder is fine.** On real AWS S3 an unresolvable role
ARN fails, so `AWS_ASSUME_ROLE_ARN`'s placeholder default remains a live defect for any
AWS-backed deployment — it is merely *dormant* on MinIO. Left as an open item rather than
closed by a green run against the one backend that tolerates it.

### The positive control is what makes the refusals mean anything

A "write is refused" result proves nothing if the *caller* cannot write either — the same
observation for the opposite reason, which is the false-witness shape. So the caller
credential was exercised on the same two operations:

| operation | caller (`minio-sandbox`) | minted ticket credential |
|---|---|---|
| `PutObject` to `dag-lake/mesh_demo/` | **succeeds** | **AccessDenied** |
| `ListObjects` on `publog-lake` | **succeeds** | **AccessDenied** |

The minted credential is demonstrably narrower than the identity it was minted from. That
is the ADR's acceptance criterion, executed rather than asserted.

### STS ceiling — measured 2026-08-26, and the result is INCONCLUSIVE

`scripts/measure_adr0044_sts_ceiling.py`, same store, via port-forward.

| concurrency | ok | rate/s | p50 ms | p95 ms | errors |
|---:|---:|---:|---:|---:|---|
| 1 | 20/20 | 27.1 | 30.1 | 90.3 | none |
| 4 | 20/20 | 49.6 | 68.8 | 126.8 | none |
| 8 | 40/40 | 52.8 | 137.3 | 182.6 | none |
| 16 | 80/80 | 56.8 | 253.1 | 393.5 | none |
| 32 | 160/160 | 49.0 | 572.6 | 925.5 | none |

- **P1 held** — zero throttle codes at any concurrency; 100% success throughout.
- **P2 held** — 30.1 ms p50 at concurrency 1, inside the 100 ms prediction.
- **P4 held** — throughput peaked at concurrency 16 and *fell* at 32 while latency more
  than doubled, with no errors. That is a saturating proxy, not a store refusing work.
- **P3 did NOT hold as written.** The prediction was "exceeds a 33/sec target **by a wide
  margin**." 1.7× is not a wide margin.

**The number is a FLOOR, not a ceiling.** The `kubectl port-forward` is a single userspace
TCP proxy and it is what saturated. What was measured is "MinIO does *at least* 57 mints/s
through a bottleneck"; its actual capacity is unknown and higher. **Nothing should be
designed against 57.**

**A methodological catch worth keeping.** The script's automated verdict printed *"P3 held
at this scale"* because its check was `rate < target` — cruder than the prediction it was
checking, which said *wide margin*. A pass/fail coarser than the registered claim will
report success for a result the claim does not cover. The registered wording governs, not
the assertion that happened to be coded. Left as-is with this note rather than quietly
tightened, since the discrepancy is the finding.

**Open:** re-run in-cluster (a pod in `sandbox`, no forward) for a number worth designing
against, and against `d4-sandbox` for the cluster users are actually on. Until then the
credential-cache question is **unanswered**, not answered in the negative.

## mint-role SHIPPED and verified live — 2026-08-27 (steps 4 and 6)

ClickHouse and PostgreSQL 17 now mint short-lived database roles.
`dag_tools/domain_broker/sql_minting.py`; verified with
`scripts/verify_adr0044_sql_minting.py` against `iagent-clickhouse` and
`iagent-postgresql` in the sandbox.

**A protocol change was required first, and it was the real blocker.** The
gateway called Topaz, resolved the ticket, then **grafted `allowed_columns` /
`row_filters` on afterwards** — so the broker minted without ever knowing what
the caller was entitled to, and server-side enforcement was structurally
impossible. `ResolveRequest` now carries the authorization decision. Both fields
are optional, so an older gateway still gets a read-only, single-table, expiring
credential; it just cannot get row/column narrowing.

| prediction | outcome (ClickHouse / PostgreSQL) |
|---|---|
| **P1** engines accept the DDL | **CONFIRMED** both |
| **P2** minted credential reads its own table | **CONFIRMED** both |
| **P3** cannot write | **CONFIRMED** — `DatabaseError` / `InsufficientPrivilege` |
| **P4** cannot read a second table | **CONFIRMED** both |
| **P5** row policy is *enforced*, not merely created | **CONFIRMED** — admin sees 3 rows, minted sees 2, on both |

**P5 is the one that matters.** It is the claim that separates `mint-role` from
`mint-sts`: the narrowing is in the database, so **a caller who declines to
apply the client-side filters still sees only their entitled rows.** Topaz's
filters stop being an advisory convention for these backends. That is what
ADR-0025 always implied and an object store cannot deliver.

Positive controls passed on both — admin *can* write and *can* read the second
table — so the refusals are the minting working, not a weak admin.

### Two things worth keeping from the implementation

**PostgreSQL REFUSES to mint when a row filter is required and RLS is off.** A
policy on a table without RLS is inert: the role would see every row while
appearing constrained. That is a silently-wider grant, which is the exact defect
being fixed, so it raises with the `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`
fix in the message rather than issuing a credential.

**No reaper is needed for safety.** Both engines support `VALID UNTIL`, so the
database enforces expiry: a leaked credential dies whether or not anything
cleaned up, and a broker that dies mid-request leaves an already-harmless role.
Cleanup is hygiene. Putting correctness in a background task that has to keep
running would have been the weaker design.

**Not gated on PG18.** `SET LOCAL ROLE`-style short-lived roles plus RLS deliver
the same enforcement on 17 — verified on the sandbox instance.

### Confirmed live: the FQDN defect

`iagent-domain-broker`'s env carries `S3_ENDPOINT_URL=http://iagent-minio:9000` — a bare
service name. The sibling finding is not hypothetical; it is the sandbox's current
configuration, and it is what a consumer in another namespace would receive.

## Acceptance

- **A ticket cannot write.** Take any advertised credential, attempt a write to its own
  asset's location, and be refused by the *store*. This is the only acceptance that
  matters; every other check passes while the credential is the authoring key.
- A ticket's credential is **expired** when replayed after its window.
- A ticket's credential **cannot read a second asset** it was not issued for.
- For `mint-role` backends: a caller who declines to apply the client-side filters still
  sees only their entitled rows and columns — narrowing survives a hostile client.
- Every advertised hostname resolves **from a pod in a different namespace**.
- No backend advertises without declaring a `mode`.

## The ADR

Filed as **[ADR-0044](../adr/ADR-0044-routing-ticket-credentials-minted-per-request.md)** —
*A routing ticket carries only credentials the broker minted for that request.* This is a
change to a **contract between components**, not a bug fix inside one, so the decision
belongs in the record rather than in a plan item's closing sentence. Approving step 0
above means accepting that ADR.

> **A routing ticket is consumed somewhere else, so everything in it must be valid and
> safe there: the hostname global, the credential minted for the holder, scoped to the
> asset, expiring with the request, and never able to write.**
