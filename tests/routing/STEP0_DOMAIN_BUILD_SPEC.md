# Step 0 — Domain build spec (mro tonight, idp deferred to GMS recovery)

This is the requirements artifact for tonight's Layer 1 + Layer 2 + gateway
work. Each row is a real user-question shape from the stable routing harness
(`test_classify_route.py`), decomposed into the subject class that must
resolve, the verb that must cover it, the output class, and the engine that
serves it.

The two persistent failures in the matrix (rotor, manuals) are the first
entries. Everything else is matrix-grounded; nothing speculative.

---

## Verified substrate state (queried 2026-06-09)

### Subject classes that exist in Neo4j today

```cypher
MATCH (c:OntologyClass)
WHERE toLower(c.uri) CONTAINS 'workinstruction'
   OR toLower(c.uri) CONTAINS 'technicalmanual'
   OR toLower(c.uri) CONTAINS 'procedurestep'
   OR toLower(c.uri) CONTAINS 'diagram'
RETURN c.uri
```

Result:
| Class | Status |
|---|---|
| `mro:WorkInstruction` | EXISTS |
| `mro:TechnicalManual` | MISSING |
| `mro:ProcedureStep` | MISSING |
| `mro:Diagram` | MISSING |

### Registered verbs and their typings

| Verb | input_uri | output_uri | Backend endpoint |
|---|---|---|---|
| `mesh:queryKnowledgeGraph` | `mesh:GraphQuery` (pseudo) | `mesh:GraphExpertResponse` | Engine E (`neo4j-expert-svc:8086/query_graph`) |
| `mesh:retrieveKnowledge` | `mesh:KnowledgeQuery` (pseudo) | `mesh:KnowledgeRetrievalResponse` | Engine W (`weaviate-expert-svc:8088/query_knowledge`) |

**Two live Contract D pseudo-class violations.** Both inputs are plumbing
concepts, not real domain classes.

### Engine code reality (not just metadata)

- **Engine E** (`neo4j-expert` image) has BOTH Neo4j graph queries AND
  `search_manual_text` — a Weaviate semantic search over the
  `DocumentChunks` collection. Git history (commit `4ea5391`, `2807d0a`,
  2026-04-14) shows this was added as part of "Vector Version of Nirvana"
  / "GraphRAG pipeline" Schema-Drift fixes — i.e., a multihop hack to
  let Engine E grab a document chunk inline when a work-instruction
  query also needs manual text, rather than routing out to Engine W.
- **Engine W** (`weaviate-expert` image) was stood up `2026-04-01`
  (commit `32ad918`) as the standalone "specialized microservice for
  pure semantic knowledge retrieval." It has one tool —
  `search_knowledge_base` — over the same `DocumentChunks` collection.

The verb registry has only one verb per engine: graph on E, manuals on
W. **Engine E's `search_manual_text` was never registered as a verb.**
The hack stayed where it belongs (internal smolagents tool).

### Engine reachability

- Engine W: 1 replica, 12h uptime, listening on `0.0.0.0:8088`.
- Engine E: 1 replica, healthy.
- Doc-tools code-server: 10h uptime, no restarts, Dagster webserver
  actively syncing the location. `ingest_ontology_job` GraphQL launch
  accepted and validated config — no 60s code-server RPC timeout
  in effect today (the morning's transient cleared with the
  doc-tools restart).

---

## Build matrix — mro (tonight)

| # | Question shape (verbatim from `test_classify_route.py`) | Subject (S) | S status | Verb (P) | Output (O) | Backend |
|---|---|---|---|---|---|---|
| 1 | "Show me the maintenance steps for the rotor assembly" / "What is the work instruction for procedure 1234?" | `mro:WorkInstruction` | EXISTS | `mesh:queryKnowledgeGraph` **re-typed** | `mesh:GraphExpertResponse` (or `mro:ProcedureStep` if declared) | Engine E |
| 2 | "Describe procedure TEST-1234 and show me its diagram" (CONTROL — passes today) | `mro:WorkInstruction` | EXISTS | `mesh:queryKnowledgeGraph` re-typed | `mesh:GraphExpertResponse` (or `mro:Diagram` if declared) | Engine E |
| 3 | "Search the technical manuals for fuel system diagnostics" | `mro:TechnicalManual` | **MISSING — declare** | `mesh:retrieveKnowledge` **re-typed** | `mesh:KnowledgeRetrievalResponse` | Engine W |

### Layer 1 — `mro_extension.ttl` nouns to declare

- `mro:TechnicalManual` — **REQUIRED.** Subclass of the IOF document /
  information-artifact upper class (verify exact parent IRI in the loaded
  graph before authoring). Without this, the resolver lands manuals queries
  on `mesh:GraphQuery` and tonight fails.
- `mro:Diagram` — optional. Only needed if we want #2's output strictly
  typed rather than the generic `mesh:GraphExpertResponse`.
- `mro:ProcedureStep` — optional. Same as `mro:Diagram` for #1.

Tonight's minimum: just `mro:TechnicalManual`. Optional classes can be added
later if output strictness becomes a real ask.

### Layer 2 — verb registrations

- **Re-type `mesh:queryKnowledgeGraph`**:
  `input_uri = mro:WorkInstruction`, `output_uri = mesh:GraphExpertResponse`,
  backend Engine E (no change). Kills the `mesh:GraphQuery` pseudo-class
  Contract D violation.
- **Re-type `mesh:retrieveKnowledge`**:
  `input_uri = mro:TechnicalManual`, `output_uri = mesh:KnowledgeRetrievalResponse`,
  backend Engine W (no change). Kills the `mesh:KnowledgeQuery` pseudo-class
  Contract D violation.

Both re-typings happen through the mesh-registrar gateway (option C), which
enforces Contract D at registration time — neither verb can register
against a pseudo-class because the gateway will reject it.

**No engine retirement.** Engine W stays — it's the intended owner of manual
search per design, and the spec's brief consideration of retiring it was
based on reading the code without knowing the history. Engine E's
`search_manual_text` stays as an internal smolagents tool (with ADR-0011
follow-up: replace it with `/find_path` composition).

---

## Manuals verb ownership — decision and rationale

The disambiguation question (Option A: "E graph, W manuals"; Option B:
"E owns both"; Option C: "two verbs on one subject, intent-split") was
mooted by two findings:

1. **The verb registry never duplicated the verb.** Engine W owns
   `mesh:retrieveKnowledge` as the manual-search verb. Engine E has no
   registered manual-search verb. The `search_manual_text` tool on E is
   purely an internal smolagents tool.
2. **Design history says W is the intended owner.** W stood up first
   (2026-04-01) as the standalone manuals/knowledge engine. E's manual
   tool was a later GraphRAG / multihop hack (2026-04-14).

So the resolution is: **W owns the routable manuals verb**, typed against
`mro:TechnicalManual`. E keeps `search_manual_text` as an internal
composition step for the multihop case (a work-instruction query that
also needs a chunk). The registry sees one verb per intent; the LLM
never has to disambiguate two predicates on the same subject.

Future architectural cleanup (ADR-0011): replace E's internal tool with
`/find_path` composition that routes the chunk-fetch through W rather
than embedding W's capability inside E. Not tonight's work.

---

## Predict-before-run table

Write these down **before** each step. A surprise is a finding, not a
failure. The intermediate check between Step 1 and Step 2 is the
highest-value test — it distinguishes "ontology landed but verb
missing" from "verb registered but ontology didn't take," which look
identical at end-state.

| Case | Now (verified) | After Step 1 (mro_extension landed) | After Step 2 (verbs re-typed via gateway) |
|---|---|---|---|
| Rotor (#1) | ❌ no verb for WorkInstruction | ❌ unchanged (Layer-2-only fix) | ✅ dispatches to Engine E |
| Diagram (#2, control) | ✅ passes today | ✅ unchanged | ✅ unchanged (regression check) |
| Manuals (#3) | ❌ subject → `mesh:GraphQuery` | subject now → `mro:TechnicalManual`; route still ❌ (verb not yet re-typed) | ✅ dispatches to Engine W |

### Step 1 intermediate gate (hard stop)

After ingesting `mro_extension.ttl`, run the stable harness and assert on
**subject resolution only** (not the route) for the manuals case:

```python
assert resp["subject_uri"] == "mro:TechnicalManual", \
    f"ontology didn't land; subject still {resp['subject_uri']}"
```

If this fails, stop. The ontology didn't land. Don't proceed to Step 2 —
fix Step 1 first. Registering verbs against a class that doesn't exist
is wasted motion and creates phantom edges.

---

## Tonight's order of operations

1. **Author + ingest `mro_extension.ttl`** via canonical
   `ingest_ontology_job`. Upload to MinIO at
   `s3://ontologies/mro/mro_extension.ttl`. Run with config:
   ```json
   { "ops": { "ingest_ontology_to_jena": { "config": { "file_url": "s3://ontologies/mro/mro_extension.ttl" } } } }
   ```
   Verify it shows up in Jena named graph `http://internal/mro` and
   propagates to Neo4j as `mro:TechnicalManual :OntologyClass`.

2. **Step 1 intermediate gate** — see above. Hard stop if subject doesn't
   move.

3. **Mesh-registrar gateway** (per `c:/tmp/plans/mesh_registrar_gateway.md`).
   Engines self-register against real subject classes; gateway enforces
   Contract D at registration time. Two registrations land:
   - Engine E: `mesh:queryKnowledgeGraph` typed to `mro:WorkInstruction`.
   - Engine W: `mesh:retrieveKnowledge` typed to `mro:TechnicalManual`.

4. **Step 3 verification**:
   - Stable routing harness 5x. Predict: **11/11 green** across all 5 runs
     (deterministic — temperature 0 ships with the gateway image rebuild).
   - Phantom-class scan. Predict: **0 phantom classes** (neither
     `mesh:GraphQuery` nor `mesh:KnowledgeQuery` should reappear as a
     verb input — Contract D enforcement at registration).
   - Abstention harness (`test_n1_abstention.py`). Predict: off-topic
     stays green, rotor on-topic stays green (no over-correction).

---

## Out of scope tonight

- **`idp` extension nouns** (`idp:Dataset`, `idp:Table`, `idp:Dashboard`).
  Layer 2 is GMS-blocked anyway — the catalog verbs (`traceLineage`,
  `lookupOwnership`, etc.) register through DataHub, and the matrix
  doesn't unblock idp until GMS is back. Sequence: idp after mro is
  green and after GMS recovers.
- **`sustainment` extension nouns.** No failing or uncovered query
  shape observed. Per ADR-0011 coverage discipline, don't build
  speculatively.
- **Retiring Engine E's `search_manual_text`.** Architectural cleanup
  via ADR-0011 `/find_path` composition. Not tonight.
- **Phase 2-5 of the validation campaign** (coverage, model swap,
  adversarial, regression injection). All deferred until tonight's
  gateway + mro extension lands and the matrix is 11/11 for the right
  reason.

---

## Why this sequence can't invert

The gateway can register a verb with `input_uri = mro:TechnicalManual`
only if that class exists in the substrate. Without Step 1, Step 2 either
fails Contract D validation (good, but no progress) or auto-MERGEs the
class into existence as a phantom edge (bad — exactly the ADR-0019
band-aid). Step 1 must precede Step 2 every time.

Similarly, Step 3's "rotor goes green" verification only means something
if Step 2 succeeded for the right reason — and that's only true if the
intermediate gate caught any Step 1 failures. Skipping the gate hides
which of the two legs broke when the matrix doesn't go all-green.
