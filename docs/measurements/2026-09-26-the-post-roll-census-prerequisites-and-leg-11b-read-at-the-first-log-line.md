# Lane 1, 2026-09-26 — the docs census: prerequisites measured, and leg 11b re-read at the first log line

**Status: prerequisites 1–3 GREEN, leg 11b GREEN strictly and PARTLY VACUOUS as written, census
rows firing.** Two corrections to my own prior record are in §4 and §5.

## 1. Re-derivation, because the sheet says to re-derive before walking

`docs/measurements/docs-walk-sheet.md` is dated 2026-09-19 against master `222fbf5` and states its
own assumption: "a page added since this was written changes the answerable set below." It has
changed, and the answerable set has not.

| | sheet (2026-09-19) | derived now |
| --- | --- | --- |
| `mesh:DocPage` instances in `setup/ontologies/docs_corpus.ttl` | 8 | **9** |
| pages carrying no `explains` edge | 3 | **4** |
| **pages that can be answered** | 5 | **5** |

The ninth page is `backfilling-the-vector-space`, added 2026-09-19, and it declares `explains: []`.
The five answerable subjects are unchanged and are exactly the sheet's five, derived from the TTL
rather than read off the sheet:

```
docs:runbook-adding-a-canvas-template   docs:runbook-adding-an-archetype
docs:runbook-adding-a-graph             docs:runbook-adding-an-engine
docs:runbook-adding-a-task-kind
```

So **Q1–Q4 are still the right four questions**, and this is a measurement rather than the
assumption it replaces. It independently agrees with the 2026-09-25 Jena remeasurement (5 distinct
`mesh:explains` subjects, 9 pages, 4 with no edge).

## 2. The three prerequisites the sheet gates the walk on

| prerequisite | measured |
| --- | --- |
| **1. engine-docs ROLLED, read at the served pod** | `GET /version` through the pod's own forward: `component: engine-docs`, `git_sha` **and** `image_tag` both `b5eeb408…`. Not the deployment's label — the process's own answer. |
| **2a. corpus PRIMED** | 9 `mesh:DocPage` in the `http://internal/DOCS` named graph (81 triples), measured 2026-09-25 with a negative control (`mesh:NoSuchTypeAtAll` → 0) |
| **2b. bodies UPLOADED** | engine-docs' own `/health`: `reader_wired: true`, **`body_store_wired: true`**, `ready: true`, `degraded_reason: null` |
| **2c. TTL agrees with the files on disk** | `tests/test_docs_corpus_drift.py` — **16 passed**. The route refuses on a `body_sha` mismatch, so a regenerated-but-unuploaded tree would answer nothing at every page. |
| **3. the pool leg reads `mesh:universalReferent`** | the flag is confirmed in Jena on `mesh:Thing` (camelCase, three surfaces, 2026-09-25), and the leg `tests/routing/test_the_pool_reaches_the_universal_referent.py` is at `bfb33b89`, **an ancestor of the deployed `b5eeb408`** by `merge-base --is-ancestor` |

**What 2b does NOT establish, said plainly:** `body_store_wired: true` is a claim that the client is
*configured*, not that an object exists at every key a row points at. It is the neighbour of "the
bodies are there". The state it cannot exclude is the one the sheet names — "a primed corpus with no
bodies answers `502` naming the locator" — which is why that outcome stays attributable to the prime
rather than to the engine if it appears in the rows.

## 3. The transport, positive-controlled before anything was believed

Both forwards were down at the start, so the census could not have run at all. After raising them,
each was checked against the failure the runner's own comment records — a **live forward to the
wrong process answers**, which is how this census once reported "keycloak refused a token" about a
request keycloak never saw:

- `:18083/realms/invincible-agent` returns a realm document carrying **both** `realm` and
  `public_key`, and does **not** name `cortex-bff` — the 2026-09-23 squatter's signature is absent.
- `:18090` answers `{"service":"cortex-orchestrator-proxy"}` and `/version` `component: cortex-bff`
  at `b5eeb408…`.

## 4. Leg 11b — green strictly, and the strict reading is partly vacuous

**No `Traceback` in the first 60 seconds: 17 of 17 pods, zero.** And the window as written measures
much less than it appears to.

The window was anchored on each pod's `status.startTime`, which is when the *kubelet* admitted the
pod. The processes do not log then. Measured offset from `startTime` to each pod's **own first log
line**:

```
+15s engine-cost   +17s engine-d, mesh-registrar   +18s engine-safety   +21s engine-f, engine-lg
+23s engine-docs   +24s engine-o   +33s engine-w   +46s engine-a, engine-e   +50s cortex-bff
+53s data-analyst  +60s dagster-user-code          +62s projector
```

So for `dagster-user-code` the 60s window contained **1 line**, and for `iagent-projector` it
contained **0** — which my own control flagged as "vacuous, not green" rather than passing it. The
projector is not silent; it writes 529 lines, the first at **+62s**, two seconds past the window.
An empty log read as a clean negative is a hazard already on this fleet's record, and here the leg
would have supplied one for free.

**Re-read with the window anchored on each pod's first log line, plus a strictly stronger read over
each whole log:** all 17 pods have ≥5 lines in the window, **0 Tracebacks in the window**, and **0
vacuous rows**.

### 4b. One Traceback exists, outside every window, and it is benign

`iagent-engine-a` (restate-analyst) carries exactly one, at `02:16:21` — about 65 minutes after
start, so no startup window of any definition would see it:

```
Exception ignored in: <function _ConnectionBase.__del__ …>
  File "…/weaviate/connect/v4.py", line 356, in __del__
AttributeError: 'ConnectionSync' object has no attribute '_client'
```

A destructor artifact in the weaviate client, on a connection that had just **succeeded** (the
preceding line logs a live HTTP+gRPC connection). It is not a crash and nothing failed because of
it. Recorded because leg 11b's text is literally "no `Traceback`", and a strict grep over a whole
log — which is the stronger read I ran — reds on it. The leg's *intent* is startup crashes; this is
neither startup nor a crash.

## 5. A correction to my own record: the count was 17, not 18

`…roll-3-fired-revision-150…md` states "**18 pods** at `b5eeb408`, all `Running`, all ready,
`restartCount == 0`". The population is **17**. Enumerated, so this figure can be reconciled in a
way the one it replaces cannot:

```
cortex-bff  dagster-user-code  data-analyst  engine-a  engine-cost  engine-d  engine-docs
engine-e  engine-f  engine-fin  engine-lg  engine-o  engine-p  engine-safety  engine-w
mesh-registrar  projector
```

All 17 at `restartCount 0`, all with `startTime` in a 3-second band (`01:10:13`–`01:10:16`), so
nothing was replaced or lost between the two reads and there is no evidence an 18th ever existed.
**I cannot prove which read was wrong**, and that is the finding: I recorded a *count* without
saving identities, so the earlier figure is unreconcilable by construction. A count is not a census.
The eighteen-services claim in that record's title and body should be read as **seventeen**; the
conclusion it supports — that the dagster pair did not move — is unaffected and independently
measured.

