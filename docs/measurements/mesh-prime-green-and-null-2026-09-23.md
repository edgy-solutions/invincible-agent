# The MESH prime ran green and landed nothing: the ingest read a TTL two commits old

**Measured** 2026-09-23, Lane 1 seat (`invincible-agent/master`).
**Dagster run** `d81452a0-60c7-4167-8292-cf2c1f54cf03` — status **SUCCESS**.
**Job** `ingest_ontology_job`, code location `doc-tools`, partition `mesh__mesh_system.ttl`,
assets `ingest_ontology_to_jena` + `sync_jena_ontologies_to_neo4j`. Launched **once**; never re-run.
**Runbook followed** `sessions/2026-09-23-packet-to-01-the-mesh-prime-runbook-measured-before-it-runs.md`
(doc-tools/lane/7f), §1–§4.

## The one-line result

Every layer did its job correctly on the bytes it was given, both seals went green, and
**the class the prime existed to land was not in those bytes.** `mesh:Thing` is absent from
Neo4j after a successful run because it is absent from `s3://ontologies/mesh/mesh_system.ttl`.

## What the run reported, and what changed (§3, by identity — not by count)

A count cannot say *which* rows moved, so the before/after was taken as name sets.

| | before | after | delta |
| --- | --- | --- | --- |
| Weaviate `OntologyClass` rows, domain=MESH | 13 | 13 | **added: none · removed: none** |
| Neo4j nodes under `http://invincible-agent/mesh#` | 73 | 73 | **0** |
| `mesh:Thing` in Neo4j | absent | **absent** | — |
| Fleet-wide `universal_referent IS NOT NULL` | 0 | **0** | — |

Weaviate's 13 rows are `AgentTask, Archetype, CatalogAssetQuery, CatalogScopeQuery,
DatasetAnalysisRequest, DocPage, GraphQuery, InstanceClass, InstanceIdentifier, KnowledgeQuery,
Request, ResolvableReferent, Response`. Against 7f's predicted 12 groundable: `Thing` predicted
and **absent**; `Archetype` and `Response` present and **not predicted** — response-shape
contamination still in the grounding pool.

The writes were not skipped — they were **idempotent replacements of the same 13 URIs**.
`ontology_assets.py:539` keys rows by `generate_uuid5(uri)`, so re-writing an existing URI
replaces it. "13 accepted, 13 confirmed present on read-back" is true and means nothing changed.

## Both seal lines, verbatim (§4)

```
Class labels: 73 authored (kept), 0 derived, 0 derived-opaque, 0 blank nodes skipped.
```

```
Retrievability seal green for domain 'MESH': http://invincible-agent/mesh#AgentTask retrieves
itself by its own stored vector. The grounding pool is searchable, not merely populated.
```

```
Weaviate sync complete for domain 'MESH': 13 row(s) accepted, 0 rejected, 13 confirmed present
on read-back, retrievability probed on http://invincible-agent/mesh#AgentTask. 60 declared
class(es) excluded by reason: 0 meta_ontology_iri, 60 response_shape_weaviate_only.
Partition reconciles: 13 + 60 == 73 declared.
```

**The retrievability seal went genuinely green, not skipped.** That settles §4b in 7f's favour:
fix D works, and the index is confirmed searchable rather than merely populated. It is the one
thing this run does establish, and it is worth having.

## The 75-vs-73 gap, named

7f predicted 75 declared / 63 excluded / 12 groundable. The run reported **73 / 60 / 13**.
Per the runbook's own instruction — *"If the run disagrees with them, one of the two is wrong and
that is the finding — do not reconcile by adjusting the expectation afterwards"* — the gap was
resolved by naming members, not by arithmetic.

Diffing the TTL's declared names against Neo4j's `mesh#` local names:

- declared in the tree's TTL, absent from Neo4j: **`Thing`, `SourceLedger`** (exactly 2)
- in Neo4j, not declared in the tree's TTL: **none** (control, as expected)

No shape distinguishes them: `mesh:Thing` has no `rdfs:subClassOf`, but `mesh:SourceLedger` has
`rdfs:subClassOf mesh:Archetype` like dozens that landed. The shared property is not shape — it
is **recency**. They are the TTL's two most recent additions:

| class | added by | committed |
| --- | --- | --- |
| `mesh:Thing` | `f16e2cd` | 2026-09-19 12:17:31 -05:00 |
| `mesh:SourceLedger` | `f9eea84` (merged `301b485`) | 2026-09-19 12:47:32 -05:00 |

## Root cause: the prediction and the run were about two different files

`head_object` on the ingested object, then `get_object` and a re-count of its bytes:

```
s3://ontologies/mesh/mesh_system.ttl
  LastModified  : 2026-09-19 16:43:01 +00:00      (= 11:43:01 -05:00)
  ContentLength : 63233          local working tree: 68293
  ETag          : 059a9a3d5755bbbeb288fb9665deea9a
  local md5     : 34dc125f324c90644bfa67c659fe8ca5
  metadata      : {'canonical-name': 'mesh_system', 'domain': 'MESH',
                   'source-url': 'local:ontologies/mesh_system.ttl'}
  'a owl:Class' named declarations IN THE S3 BYTES : 73
    mesh:Thing         declared in S3 object: False
    mesh:SourceLedger  declared in S3 object: False
    mesh:AgentTask     declared in S3 object: True     <- positive control
```

The S3 object was uploaded at **11:43:01 -05:00**; `mesh:Thing` was committed at **12:17:31**,
`mesh:SourceLedger` at **12:47:32** — 34 and 64 minutes *after* the upload. The run's `73 declared`
is the **correct** count for the object it was handed. The extraction has no defect. Neither does
the Weaviate filter, the Jena leg, the embed gateway, or PR #1's flag code — **PR #1's flag path was
never reached, because its input was not present.** A green run on a stale input.

Decided on **content**, not on a fingerprint convention: an ETag mismatch has innocent causes
(line endings), a missing class declaration has none. Both were checked, and `mesh:AgentTask`
reading `True` is the positive control that the matcher itself works.

## Census: one stale object is a sample, not a population

`CANONICAL_TTL_MANIFEST` (`setup/prime_databases.py:170`) has 22 entries; **17** carry a `path:`
source (vendored in this repo, so their S3 copy *can* be stale relative to this tree) and **5**
carry a `url:` source — fetched from upstream, excluded **with that reason**, not skipped.
Every one of the 17 lands in exactly one bucket:

```
MATCHES S3        : 15
DIFFERS FROM S3   :  2   mesh/mesh_system.ttl   S3=63233 local=68293  delta=+5060
                        docs/docs_corpus.ttl   S3= 5012 local= 5573  delta= +561
NOT IN S3 AT ALL  :  0
ERRORS            :  0
PARTITION: 15 + 2 + 0 + 0 = 17 of 17  ->  UNACCOUNTED: 0
```

**`docs/docs_corpus.ttl` is a second stale object**, and it would have been missed by fixing only
`mesh`. It went stale by `109c5d7` (2026-09-19 22:17:38 -05:00), *after* the same upload.

All 17 objects carry one upload timestamp (16:42:59–16:43:01 UTC): a single
`prime_databases.py` upload pass. So the cause is not per-file — it is that
**no upload pass has run since 2026-09-19 16:43 UTC**, and two TTLs were authored after it.

Two-directional control: the set of files differing from S3 is exactly the set of files under
`setup/ontologies/` committed after that instant — `git log --since` returns those same two and
no others. A file in one list and not the other would have refuted the cause; none is.

## Why the run could not detect this, and the seal that is missing

`Partition reconciles: 13 + 60 == 73 declared` is internally valid and structurally **incapable**
of catching this. Its total, `73 declared`, is derived from the same parse as its parts. A class
that never entered the parse cannot make the reconciliation fail — the check is self-consistent
over whatever population it was handed, and says nothing about whether that population is the
declared one.

The runbook's §2a read `x-amz-meta-domain` and stopped. **A stamp says how an object will be
routed, never what it contains.** `head_object` returns `ContentLength` and `ETag` in the same
response that carries the metadata; comparing either against the tree would have caught this
before the run, at zero extra cost.

So the gap is a comparison nobody makes: **no check anywhere asserts that the S3 object and the
repo TTL are the same bytes.** The ingest trusts S3; the uploader writes S3; nothing reads both.
That is the invariant *between* two declarations that every per-declaration check is blind to.

## What was NOT done, and why

- **No second ingest run.** The order's STOP branch was conditioned on the retrievability seal
  redding; it went green, so that branch did not trigger — but neither does a green seal authorize
  a re-run, and the runbook's §5 assigns recovery to 7f, not to this seat.
- **No `--upload-only`.** Refreshing `s3://ontologies/` changes what *every* domain's ingest reads,
  including the second stale object and the 15 current ones. That is a shared-substrate write
  outside this order's scope. Diagnosed here; not executed.

## The fix, for whoever is authorized to run it

Two steps, in this order, and the first is useless without the second:

1. `uv run setup/prime_databases.py --upload-only` **from a tree containing `f16e2cd` and
   `109c5d7`** — it reads `SCRIPT_DIR / ontologies/*.ttl` off the filesystem
   (`prime_databases.py:866`), so the tree it runs from *is* the input. A stale checkout re-uploads
   the stale bytes and reports `[OK]`.
2. Re-launch partition `mesh__mesh_system.ttl` (and `docs__docs_corpus.ttl`) — the ingest reads S3,
   never the repo, so step 1 alone changes nothing downstream.

Then the reads that decide it: `mesh:Thing` present in Neo4j, fleet-wide
`universal_referent IS NOT NULL` **count == 1** (a partition, not a presence check), and
`Thing` in the MESH grounding pool with `Archetype`/`Response` gone.

## Recommendation

Add the comparison to the uploader or to a test: for every `path:` entry in
`CANONICAL_TTL_MANIFEST`, the S3 object's bytes must equal the tree's. It is the census above,
run as a check. Without it, "the prime ran green" will keep being reported as "the ontology is
current" — which is what happened here.
