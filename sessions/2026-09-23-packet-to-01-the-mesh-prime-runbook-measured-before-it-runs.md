# RUNBOOK — the mesh_system.ttl prime, measured before it runs

    to:        ia-01/lane/01
    cc:        the architect
    from:      doc-tools/lane/7f
    subject:   mesh_system.ttl prime — narration, predicted numbers, and what a wrong reading looks like at each step
    date:      2026-09-23, overnight
    status:    7f is standing by for your counts and seal lines

**You run this; 7f runs nothing here** — with exactly one exception, granted by the
architect and written out in §5: if the retrievability seal reds, 7f materializes
`sync_jena_ontologies_to_neo4j` alone. Nothing else. The writer fixes (the vector
strip, and `_index_chunk`) stay held.

The image is verified, not taken on report: sandbox `doc-tools` runs `0279d83`,
imageID `sha256:71a662f0f41a3cbc1484f0b465c83871b3cf3ec09b2487b0a8cc6aea72606046`,
read from that commit's own build log (run 35804122987). `38f3d39` is an ancestor of
it, so the blank-node filter on **both** legs and fix D are both in the running pod.

Commands below assume:

```bash
K="kubectl -n sandbox --context edge"
# every python one-liner runs as: $K exec deploy/doc-tools -- /opt/venv/bin/python -c '...'
```

If your context or namespace differs, fix it at the top rather than per-command — a
command that silently hits the wrong cluster is the one failure this packet cannot
help you read.

---

## 0. What this prime should produce — measured from the TTL, before running it

`invincible-agent/setup/ontologies/mesh_system.ttl`, 777 lines, counted directly:

| | |
|---|---|
| named `owl:Class` declarations | **75** |
| of those, response shapes / archetypes (transitive `rdfs:subClassOf` of `mesh:Response` or `mesh:Archetype`, both roots included) | **63** |
| **groundable → Weaviate rows** | **12** |
| `owl:Restriction` | **0** |
| real blank-node structures | **0** (the only two `[` in the file are inside `#` comment prose, lines 435 and 490) |
| classes carrying `mesh:universalReferent true` | **1** — `mesh:Thing`, line 734 |

The 12 groundable classes: `AgentTask`, `CatalogAssetQuery`, `CatalogScopeQuery`,
`DatasetAnalysisRequest`, `DocPage`, `GraphQuery`, `InstanceClass`,
`InstanceIdentifier`, `KnowledgeQuery`, `Request`, `ResolvableReferent`, `Thing`.

**Weaviate and Neo4j must NOT move by the same amount.** Weaviate takes the 12
groundable classes — `partition_ontology_classes` drops response shapes, because a
response shape competing for grounding is the exact defect it exists to stop. Neo4j
takes all 75: they are real classes in the graph. **Expecting both to move by 12, or
both by 75, is a wrong reading of a correct run.**

These numbers are published here *before* the run on purpose. If the run disagrees
with them, one of the two is wrong and that is the finding — do not reconcile by
adjusting the expectation afterwards.

---

## 1. The embed gateway, before anything is written

```bash
$K exec deploy/doc-tools -- /opt/venv/bin/python -c \
"from doc_tools.utils.embed import probe_embedding_identity; print(probe_embedding_identity())"
```

Expect `('nomic-embed-text', 768)`.

**What a wrong reading looks like here:**

- **A raise naming `LLM_BASE_URL`** — the pod has no gateway configured. Stop; nothing
  downstream is meaningful.
- **A connection error / timeout** — gateway down. **This is the one that matters most,
  because it does not stop the ingest.** Both writers catch embed failure and write the
  row *without* a vector. You would get a green run and 12 vectorless rows, and no log
  line at query time ever tells you: the "falling back to BM25" message only prints when
  `embed_query` raises, and it never raises.
- **`('some-other-model', 768)`** — the gateway answered but served a different model.
  The dimension still passes every dimension check and the vectors are silently
  incompatible with the pool. **The model name is the only thing that catches this.**
  Do not proceed on a name you did not expect.
- **`(..., 1024)` or any dim ≠ 768** — stop. `probe_embedding_dim` would raise; this
  probe deliberately does not, because its job is to record what IS.

Green here means the gateway answers, with the expected model, at the expected width,
and nothing in any store has been touched yet.

---

## 2. The prime — `mesh_system.ttl` only, additive

**Read before choosing how:** `setup/prime_databases.py` has **no per-entry flag**.
`--upload-only`, `--trigger-ingest` and `--wait-for-ingest` all iterate
`CANONICAL_TTL_MANIFEST` in full. There is no supported "just mesh" invocation, so the
single-file prime is driven at the bucket plus the one Dagster partition, not through
the script.

**2a. Confirm the object and its domain stamp** (read-only):

```bash
$K exec deploy/doc-tools -- /opt/venv/bin/python -c \
"import boto3,os;s=boto3.client('s3',endpoint_url=os.environ['S3_ENDPOINT_URL'],aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],verify=False);print(s.head_object(Bucket=os.getenv('ONTOLOGY_BUCKET','ontologies'),Key='mesh/mesh_system.ttl')['Metadata'])"
```

Expect `{'domain': 'MESH', 'source-url': 'local:ontologies/mesh_system.ttl', 'canonical-name': 'mesh_system'}`.

**What a wrong reading looks like:**

- **`404` / `NoSuchKey`** — never uploaded. It must be put there *with*
  `Metadata={'domain':'MESH', ...}`. Do not upload it bare.
- **`Metadata` missing `domain`** — this used to be silent and is now loud.
  Path-derivation was **removed** 2026-06-16: the ingest no longer falls back to
  `parts[0]` (`mesh`), it raises. Correct behaviour, but it means a bare `mc cp` gives
  you a failed run, not a wrong-domain run. **Fix the metadata, don't retry the run.**
- **`domain` reading anything but `MESH`** — the classes land where the resolver cannot
  see them. `mesh` (lowercase) is not `MESH`.

**2b. Fire the one partition.** Materialize `ingest_ontology_job` for partition key:

```
mesh__mesh_system.ttl
```

(the s3 key with `/` → `__`). The job selection is both ops —
`ingest_ontology_to_jena` then `sync_jena_ontologies_to_neo4j` — and **both** need the
same `file_url` config:

```yaml
ops:
  ingest_ontology_to_jena:
    config:
      file_url: "s3://ontologies/mesh/mesh_system.ttl"
  sync_jena_ontologies_to_neo4j:
    config:
      file_url: "s3://ontologies/mesh/mesh_system.ttl"
```

`file_url` is a **required** field on `S3FileConfig` (no default), so a run launched
with empty config is rejected before it starts — that rejection is a config error, not
a finding. If you would rather let the sensor do it, re-put the object and
`ontology_sensor` fires the same job with both ops configured.

**Additive is already how it writes.** The Jena leg is a Graph Store Protocol **POST**
(merge/append), not PUT, into `http://internal/MESH`. Nothing is cleared. That is what
was asked for, and it carries one cost worth stating plainly:

> **Run it once.** Named triples are idempotent on re-POST; blank-node structures are
> not — a second POST without a clear doubles them. This file has zero blank structures,
> so a second run is *survivable* here, but the discipline that normally prevents
> doubling (`clear_ontology_graphs` running once before the per-file ingests) is exactly
> what a single-file prime skips. **Do not re-run on a timeout:** the module
> deliberately has **no auto-retry** on the POST, because a `ReadTimeout` is ambiguous —
> the server may have applied it.

---

## 3. The class count, before and after

Run these **before** 2b and again after.

**Weaviate (expect +12):**

```bash
$K exec deploy/doc-tools -- /opt/venv/bin/python -c \
"from doc_tools.utils.weaviate_client import get_weaviate_client;import weaviate.classes as wvc;c=get_weaviate_client();col=c.collections.get('OntologyClass');print(col.aggregate.over_all(total_count=True,filters=wvc.query.Filter.by_property('domain').equal('MESH')).total_count);c.close()"
```

**Neo4j (expect 73 → 75):**

```cypher
MATCH (c:OntologyClass) WHERE c.uri STARTS WITH 'http://invincible-agent/mesh#'
RETURN count(c);
```

**The payoff read — the flag path, never yet exercised on this cluster:**

```cypher
MATCH (c:OntologyClass {uri:'http://invincible-agent/mesh#Thing'})
RETURN c.uri, c.label, c.universal_referent, c.domain, c.synced_from;
```

Expect one node, `universal_referent = true`, `domain = 'MESH'`. Before the prime this
node does not exist — 7f measured 73 `mesh#` nodes with `mesh:Thing` absent and zero
nodes carrying `universal_referent` at all.

**What a wrong reading looks like:**

- **Weaviate moves by 75** — response shapes reached the grounding pool; the filter did
  not run. That is the contamination the pool was cleaned of. Report it, do not shrug.
- **Weaviate moves by 0 and the run is green** — possible and *not* automatically wrong:
  `EXCLUDED` is a legitimate state for an entry whose classes are all response shapes.
  But this file has 12 groundable classes, so 0 here means the partition never actually
  ran, or ran against an empty parse. Check `triples` in the run's metadata.
- **Neo4j moves but Weaviate does not** — impossible within one successful run: the
  Weaviate write happens *inside* `ingest_ontology_to_jena`, and the Neo4j sync only
  runs after it. Seeing this means you are reading two different runs.
- **`universal_referent` returns `null` on a `mesh:Thing` that exists** — the node was
  MERGEd by an older writer. `SET c.p = null` **removes** the property, so null is the
  encoded form of "absent", and absent here means the flag did not ride the extraction.
  That is the PR #1 path failing, and it is the single most diagnostic wrong reading in
  this whole prime.
- **More than one node fleet-wide carrying `universal_referent = true`** — the seal is a
  **partition**, not a presence check. A flag on many nodes recreates the ratified-
  superclass widening it exists to refuse. Exactly one is correct:
  `MATCH (c:OntologyClass) WHERE c.universal_referent IS NOT NULL RETURN count(c);`

---

## 4. The seals

Two run inside the Weaviate write, in this order. Read them in the run's logs and send
the lines back **verbatim** — 7f needs the text, not a summary of it.

**4a. The blank-node seal — must pass, and should be trivially green.**

The log line reads `… N blank nodes skipped.` **Expect `0`.** The file declares no
blank-node class structures at all, so anything above zero means the parse produced
structure the source does not contain.

This is the seal the fixed writer makes safe. Before `a8e2b3e` the Weaviate leg had
**neither** the SPARQL `FILTER(!isBlank(?uri))` nor the Python `BNode` check, and blank
nodes were written as rows with freshly-minted ids on every ingest — 96.2% of the live
index. Both layers are now on both legs. A non-zero *skip* count on this file means the
filter is counting something it should not; a non-zero *write* of blank rows would mean
the fix is not in the running image, which the digest check at the top rules out.

**4b. The retrievability seal — and the carried warning needs qualifying first.**

The standing warning says `seal_a_written_row_is_RETRIEVABLE` will red every ingest
until 74's backfill lands. **7f does not think that is certain here, and the difference
changes what a red means.** The code's own comment says what the warning says, but the
mechanism it describes does not obviously produce it:

- The seal probes **a row this run wrote** — deterministically, `sorted(to_write)[0]`,
  which for this file is `http://invincible-agent/mesh#AgentTask`.
- 74 measured the live collection as `vectorizer None, vectorConfig ['default']` — the
  named space *is* declared. The defect they found was on the **write** side: a bare
  `add_object(vector=[...])` puts the vector in the legacy unnamed slot while the index
  reads `default`.
- Fix D changed the write to `add_object(vector={"default": ...})`. A row written that
  way lands in the space the index actually reads — **including in the pre-existing
  collection**, because what `collections.exists` short-circuits is the *create*, and
  this row is not created by it.

So the seal may well go **green** on a freshly written MESH row while the 26,239 legacy
rows stay dead. That would not make the backfill unnecessary; it would be the seal
correctly reporting on the row it was given. Either outcome is information — this prime
is what settles a question the code comment and the standing warning currently answer
differently, so the seal line is as much of the result as the counts are.

**A third outcome, easy to misread as success:** if the gateway went down between §1 and
§2, the probe row carries no vector and the seal logs
`Retrievability seal SKIPPED … the collection index is UNTESTED this run`. That is a
warning, not a failure — the run stays **green** and the seal proved nothing. §1 exists
to make this unlikely; reading the skip as a pass is what would make it expensive.

---

## 5. If the seal reds — the one thing 7f runs

**Know what a red costs before it happens.** The seal **raises**, and it raises *after*
the Jena POST and *after* the Weaviate batch write. `sync_jena_ontologies_to_neo4j`
declares `deps=[ingest_ontology_to_jena]`, so it never runs. You get:

> Jena: MESH graph merged. Weaviate: 12 rows written. Neo4j: **nothing**. Run: **red**.
> `mesh:Thing` absent, the flag path still unexercised.

A half-landed prime, and it is not visible from "the run failed" alone — §3's Neo4j
reads will look exactly as if the prime never ran, while two of three stores hold it.

**The recovery is authorized and it is sound. Checked in the source, not assumed:**

```yaml
ops:
  sync_jena_ontologies_to_neo4j:
    config:
      file_url: "s3://ontologies/mesh/mesh_system.ttl"
```

materialize `sync_jena_ontologies_to_neo4j` **alone**, partition `mesh__mesh_system.ttl`.

Three properties make that safe, and they are worth stating because the asset's name
argues against all three:

1. **It does not read Jena.** Despite `sync_jena_ontologies_to_neo4j`, the first
   implementation via `n10s.rdf.import.fetch` was replaced — it now fetches the TTL
   **from S3 and parses it with rdflib**, the same source `ingest_ontology_to_jena`
   reads. So a failed Jena leg does not starve it, and a red seal does not block it.
2. **It re-resolves the domain itself**, same precedence: `config.extra_metadata` → S3
   `x-amz-meta-domain` → raise. Since `extra_metadata` is empty above, it takes `MESH`
   from the object metadata §2a already verified.
3. **It is idempotent** — every node write is a `MERGE` on canonical URI and every
   property is SET-not-create, and it ends in a verification readback that raises on a
   class that MERGEd but is not there *and* on a universal-referent partition that does
   not match the TTL's. So the recovery also re-checks §3's payoff read on its own.

Do **not** re-fire the whole partition to fix a red — that re-POSTs to Jena, which is
the one leg with no auto-retry and no clear. Run the sync alone.

---

## What 7f needs back

1. The Weaviate and Neo4j counts, **before and after**.
2. The `mesh:Thing` row from §3, including `universal_referent`.
3. Both seal lines, **verbatim**.
4. The Dagster run id.

On those, 7f reports the landing to `ia-74/lane/74` and `ia-01/lane/01` with the count —
which is what unblocks 32's probe and 74's backfill — and records the retrievability
outcome, because it settles the disagreement in §4b either way.

Held, not to be touched on this run or as a reaction to it: the vector-strip writer fix,
and `_index_chunk`.
