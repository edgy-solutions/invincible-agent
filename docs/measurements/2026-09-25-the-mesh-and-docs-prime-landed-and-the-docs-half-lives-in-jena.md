# Lane 1, 2026-09-25 — the mesh and docs prime landed, and the docs half lives somewhere nobody looked

Item 3 of the architect's order, now step 2 of Chris's overnight order: put
`s3://ontologies/mesh/mesh_system.ttl` and `docs/docs_corpus.ttl` from master directly, compared by
content, embed probe first, re-launch both partitions, stop on a red seal.

**Every seal green. Both partitions landed. Nothing red.** The headline is not that, though — it is
that a report counting only `OntologyClass` would have concluded the docs partition landed
**nothing**, and would have been wrong for a reason the file itself states.

Run this in the prime-then-roll direction, which is the correct one: engines re-register only at
startup, so the roll's restart is what publishes primed state.

---

## 1. Before writing: the embed gateway, three times

The runbook's step 0. `('nomic-embed-text', 768)` on three consecutive fires — **three, not one**,
because a single live-endpoint observation has previously let me write up a regression that fires 2
and 3 refuted.

The first attempt failed with `exec: "C:/Program Files/Git/opt/venv/bin/python": no such file or
directory`, which reads exactly like a broken gateway and was **my own instrument**: Git Bash
rewrote the pod-side absolute path. Fixed with `MSYS_NO_PATHCONV=1` and `MSYS2_ARG_CONV_EXCL='*'`.
Worth naming because the failure accuses the subject.

## 2. The comparison, and a correction to my own credit

Both objects were **STALE**, decided on **content** (sha256 of body bytes), not on size:

| object | repo bytes | S3 bytes | verdict |
|---|---|---|---|
| `mesh/mesh_system.ttl` | 68293 | 63233 | STALE |
| `docs/docs_corpus.ttl` | 5573 | 5012 | STALE |

**Correction I owe the record:** both differed in *length* too, so on these two objects a size-only
check would **not** have been fooled. Content comparison is still the right rule — `head_object`
returns `ContentLength` and `ETag` in the same response as the routing metadata, and the
equal-length trap is real — but it was between two *repo revisions* of `docs_corpus.ttl`, not
between repo and S3. I am not crediting the instrument with catching something here that size
would have missed.

Metadata was **derived from the uploader's own code path** (`setup/prime_databases.py:875, 904`),
not typed: bare keys (boto3 prepends `x-amz-meta-`), `domain`, `source-url` as
`local:ontologies/…`, `canonical-name`. It is load-bearing — doc-tools' `ontology_assets` reads
`head["Metadata"]["domain"]` and raises *"Domain not declared for ontology"* without it, and
path-derivation was removed on 2026-06-16. The derived values were cross-checked against the live
objects' existing metadata (the prior upload ingested successfully, so it is the authority) and the
write would have **refused on a domain change**. Transfer into the pod was verified by hash before
the put; the put was round-tripped by reading back and hashing.

## 3. The sensor fired on its own, which is the part that needed catching

`ontology_sensor` fires `ingest_ontology_job` on a re-put, with both ops configured. It fired
**~35 seconds** after the upload, for both partitions. Partition keys are the s3 key with `/`→`__`.

I checked for in-flight runs **before** launching anything, and that is the only reason the Jena leg
was not doubled: it is a Graph Store Protocol **POST**, which appends, and a single-file prime skips
`clear_ontology_graphs`. Both sensor-launched runs reached **SUCCESS**; nothing was launched
manually and nothing was re-run.

**A figure I dropped rather than defended.** My first run-listing carried `UPLOAD_AT = 1758770209`
— a year off — so every run reported `AFTER MY UPLOAD: True`, including rows from 2026-09-19. A
matcher that answers the same way for every member is not a measurement. The figure is gone and the
boundary was re-derived from the run list's own timestamps.

## 4. The seals, verbatim

Paraphrase would erase the distinction that matters, so these are the runs' own lines:

```
[ingest_ontology_to_jena] Class labels: 75 authored (kept), 0 derived, 0 derived-opaque (fragment
is a bare code — the name is a placeholder and the meaning lives in a sibling triple), 0 blank
nodes skipped.

[ingest_ontology_to_jena] Retrievability seal green for domain 'MESH':
http://invincible-agent/mesh#AgentTask retrieves itself by its own stored vector. The grounding
pool is searchable, not merely populated.

[ingest_ontology_to_jena] Weaviate sync complete for domain 'MESH': 14 row(s) accepted, 0 rejected,
14 confirmed present on read-back, retrievability probed on http://invincible-agent/mesh#AgentTask.
61 declared class(es) excluded by reason: 0 meta_ontology_iri, 61 response_shape_weaviate_only.
Partition reconciles: 14 + 61 == 75 declared.
```

The docs run's equivalent line reads **`0 authored (kept) … 0 blank nodes skipped`** — see §6.

**The retrievability line settles an open disagreement.** 7f reported the code comment and the
standing warning answering differently on whether Fix D works in the pre-existing collection. It
does, on the write side: `mesh#AgentTask` retrieves itself by its own stored vector. So the seal is
not permanently red — while the legacy rows still need 74's backfill. Presence is not
retrievability, and this is the consuming operation, not a row count.

**`Partition reconciles: 14 + 61 == 75 declared` is a tautology in a seal's clothes.** It is the
tenth catalogued shape of a guard that cannot fire: the total is derived from the same parse as the
parts, so no input a parser silently drops can ever red it. Independent witness, from the file
rather than the run:

```
'a owl:Class' occurrences in setup/ontologies/mesh_system.ttl : 75
distinct subjects of those declarations                       : 75
NEGATIVE CONTROL, 'a owl:NoSuchClass'                         : 0
```

Two surfaces now agree on 75, and one of them never entered the run's parse.

## 5. The after-state, absolute

| read | value |
|---|---|
| `mesh#` OntologyClass nodes in Neo4j | **75** |
| `mesh#Thing.label` | `'Thing'` |
| `mesh#Thing.universal_referent` | **True** |
| `mesh#Thing.domain` / `synced_from` | `'MESH'` / `'s3://ontologies/mesh/mesh_system.ttl'` |
| fleet-wide carrying the flag **at all** | **1** |
| fleet-wide with the flag **TRUE** | **1** — `http://invincible-agent/mesh#Thing` |
| `mesh#SourceLedger` present | **1** (74 said the stale object predated it) |
| Weaviate `OntologyClass`, `domain=MESH` | **14** of **26240** all-domains |
| …control: the filter actually ran | MESH < total → **True** |
| …negative control, `domain=NO_SUCH_DOMAIN` | **0** |

**Scope, stated so a borrowed baseline is not read as my own observation.** The sensor fired 35
seconds after the put, so there was no window for a "before" snapshot. **The 73→75 delta is 7f's
recorded baseline, not this seat's measurement.** What is measured here is the absolute after-state.
The Neo4j reads were taken twice, in separate sessions, and agreed.

The `universal_referent` read is deliberately a **partition over all `OntologyClass` nodes with no
uri filter** — the arm that can actually fail, since a flag on many nodes recreates the
ratified-superclass widening it exists to refuse. It is a real two-surface check and I nearly
mis-reported why: grepping the TTL for `universal_referent` returns **nothing**, which briefly
looked like the flag being a code artifact. The file spells it camelCase —
`mesh:universalReferent true` at `setup/ontologies/mesh_system.ttl:736`, on exactly one class, with
the property declared at 728. **My matcher's spelling, not a finding** — the same prefix/spelling
trap as ever, and the tell was a zero where a zero made no sense.

The two spellings are an **explicitly declared pair**, which I checked rather than assumed after
first writing "the store's snake_case is the projection" as an inference. doc-tools' ontology-assets
module carries `UNIVERSAL_REFERENT_PREDICATE` (the IRI read from the TTL) and
`UNIVERSAL_REFERENT_PROPERTY` (the property written to the store) as separate named constants,
alongside `_universal_referent_value`, with a dedicated
`tests/test_ontology_assets_universal_referent.py`. So it is not a generic camelCase→snake_case
transform that happens to work here — it is a mapping someone declared, which is why grepping for
either spelling alone finds only one side of it.

## 6. The docs partition: zero in two stores, and correct

`OntologyClass` reads **0** for `domain=DOCS` in Weaviate, and Neo4j's single DOCS-domain node is
`http://invincible-agent/docs#DocExplanation`, `synced_from docs_extension.ttl` — **a different
object, not this prime's**. Counted that way, the docs partition landed nothing.

The file says otherwise, and the file is the authority on its own shape:

```
setup/ontologies/docs_corpus.ttl : 109 lines, 5573 bytes
'a owl:Class' declarations       : 0
typed instances                  : 9 × mesh:DocPage
```

**It declares no classes at all.** A class-shaped count over an instance-shaped file can only
return zero, and the run's own `0 authored (kept)` says exactly that. The surface that can tell
"landed perfectly" from "landed nowhere" is the triple store:

```
named graph http://internal/DOCS : 81 triples      (http://internal/MESH : 333)
mesh:DocPage instances           : 9
NEGATIVE CONTROL mesh:NoSuchTypeAtAll : 0
```

All nine named, not counted:

```
docs#runbook-adding-a-canvas-template   docs#runbook-adding-an-engine
docs#runbook-adding-a-graph             docs#runbook-backfilling-the-vector-space
docs#runbook-adding-a-task-kind         docs#runbook-pinning-the-fleet-sdk
docs#runbook-adding-an-archetype        docs#runbook-rolling-a-service
                                        docs#runbook-writing-a-walk-sheet
```

**Honest limit:** with no before-snapshot I cannot attribute these nine to *this* run rather than a
prior one. What I can say is why that matters less than it looks: the run reports **0 blank nodes
skipped**, so every subject is a named URI, and RDF graphs are sets — re-POSTing identical triples
about named subjects adds no content. Blank nodes are what a doubled append duplicates, and there
are none. That reduces the doubling hazard; it does **not** license re-running on a timeout, which
remains the runbook's rule and was followed.

## 7. One more instrument defect, named

The Weaviate leg first failed with a DNS error naming
`iagent-weaviate-grpc.sandbox.svc.cluster.local:50051:50051` — the pod's `WEAVIATE_*_HOST` env vars
carry `host:port`, and I passed one through as a bare host *and* appended a port. It reads as an
unreachable store. The env var is the authority on both halves, so it is now parsed rather than
assumed. Third time this session that a failure accused its subject and belonged to my tooling.

## 8. What is not closed

- **The legacy rows still need 74's backfill** — Chris's step 4, per
  `docs/runbooks/backfilling-the-vector-space.md`. Fix D is proven on the write side only.
- **No re-put on re-verification.** After the roll these objects get **compared**, not written:
  a re-put fires the sensor automatically and the Jena leg appends.
- **The 61 excluded classes** are `response_shape_weaviate_only`, by declared reason, with the
  partition reconciling. Not a gap; recorded so the 14 is never read as 14 of 75 having worked.
