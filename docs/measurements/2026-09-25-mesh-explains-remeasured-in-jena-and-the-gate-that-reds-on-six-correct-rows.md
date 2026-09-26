# mesh:explains re-measured in Jena, and the gate that reds on six correct rows

Date: 2026-09-25. Seat: `invincible-agent/master` (Lane 1 seat). Dispatch item 5 — "re-measure
`mesh:explain` in Jena now that `mesh_system.ttl` is primed; tell the worker."

Five SPARQL passes against the deployed Fuseki dataset, each run **inside** the docs engine pod
over stdin, so the Fuseki credential never left the pod and no shell layer could collapse the
SPARQL quoting. Nothing below is a grep of a TTL unless it says so, and where a TTL *is* the
instrument the matcher is controlled in both directions.

## 0. The name in the dispatch is not a term in the store

`mesh:explain` — the spelling the dispatch uses — **does not exist in this store, in any graph,
in any position.** The term is `mesh:explains`.

This was not decided on one spelling. A zero from one exact IRI is the weakest possible evidence
of absence, so pass 2 derived the population instead: every IRI anywhere in the store whose text
contains `explain`, case-insensitively, in subject, predicate **or** object position. One term
came back. Controls in the same breath: the identical `CONTAINS(LCASE(STR(?term)), …)` form
returned a non-zero count for `thing` and exactly zero for a nonsense token, so the form finds
what is there and not what is not.

Everything below is therefore about `mesh:explains`. The rename is the first thing the worker
needs, because a check written against `mesh:explain` cannot fail and cannot pass — it asks about
nothing.

## 1. The declaration is present and correct

In the MESH graph (333 triples; DOCS holds 81):

| predicate | object |
| --- | --- |
| `rdf:type` | `owl:ObjectProperty` |
| `rdfs:domain` | `mesh:DocPage` |
| `rdfs:range` | *(absent — deliberately unconstrained)* |

The predicates were not guessed. The pass dumped every predicate/object on the subject and let the
store say what the declaration is; a search for a mechanism by name matches prose *about* it.

`mesh:universalReferent true` on `mesh:Thing` is confirmed in Jena as well — the third surface,
after Neo4j and Weaviate were measured earlier today. It is spelled camelCase.

## 2. The edge set: 14 edges, 5 subjects, 14 targets, none shared

14 `mesh:explains` edges, from 5 distinct subjects, to 14 distinct targets. **No target is
reached by two subjects.**

That last clause is the one that matters downstream: an ordering step over shared targets has
nothing to choose between, so `order_pages` remains **UNWITNESSED** rather than wrong — unchanged
from the 2026-09-19 measurement. This is a gap in the evidence, not a defect in the code.

## 3. A recorded figure is stale

The standing note reads "5 of 8 pages, three declare `explains: none`". The store now says:

| | 2026-09-19 note | 2026-09-25 measured |
| --- | --- | --- |
| `mesh:DocPage` instances | 8 | **9** |
| pages carrying no `explains` edge | 3 | **4** |
| pages that can be answered | 5 | 5 |

The answerable count is unchanged, and it cross-checks: 9 pages minus 4 with no edge = 5, which
equals the 5 distinct subjects counted independently in §2. The corpus grew by one page and that
page declares nothing.

## 4. The finding: 6 of the 14 targets fail the vocabulary's own gate

`mesh:explains`' `rdfs:comment` declares a rule about itself, quoted here because the wording is
load-bearing: *every target must resolve in the deployed graph* — the invented-IRI rule, "the only
gate this vocabulary carries in one direction", and "the check is a SPARQL ASK against the deployed
graph and never a grep of a TTL".

Run as written, over all 14 targets, partitioned so every target lands in exactly one bucket:

| target | resolves |
| --- | --- |
| `cost:LotCostingReview` | yes |
| `cost:ProductionLot` | yes |
| `fin:Program` | yes |
| `mesh:Archetype` | yes |
| `mesh:DispositionReview` | yes |
| `mesh:InstanceEnumeration` | yes |
| `mesh:InstanceResolution` | yes |
| `mesh:StatefulSupportResponse` | yes |
| `mesh:costLotCostingReview` | **no** |
| `mesh:enumerateInstances` | **no** |
| `mesh:finProgramBrief` | **no** |
| `mesh:resolveInstance` | **no** |
| `mesh:seedCanvas` | **no** |
| `mesh:seedPortfolioCanvas` | **no** |

8 resolve, 6 do not, 8 + 6 = 14 accounted for. The split is total and it is not about spelling
luck: **all 8 that resolve are UpperCamelCase classes; all 6 that fail are lowerCamelCase verbs.**

### It does not depend on my reading of "resolve"

"Must resolve" does not say in which position, so both readings were measured. Reading A: the IRI
appears as a **subject** — the graph says something about it. Reading B: the IRI appears
**anywhere**.

Reading B carries a trap that would have made it useless: every target is the object of its own
`mesh:explains` edge, so a naive any-position ASK is TRUE for all 14 **by construction** and
cannot fail. That was demonstrated before it was avoided, then the DOCS graph was excluded.

Both readings: **6 of 14 fail, the same six.** Controls held under B as well — an invented IRI in
the same namespace answered False, `mesh:Thing` answered True. The finding does not turn on the
reading.

### The six are not invented — they are the fleet's verbs

This is the check that decides the conclusion, because if the six existed nowhere the gate would
simply be right and they would be invented IRIs. Files in this repo naming each (venvs, caches and
generated clients excluded; `DocPage` as a positive control at 37 files and a nonsense name at 0):

`resolveInstance` 102 · `enumerateInstances` 36 · `finProgramBrief` 19 ·
`seedPortfolioCanvas` 18 · `seedCanvas` 16 · `costLotCostingReview` 9

They are real, heavily used verbs. The gate, implemented literally, reds on six **correct** rows.

### Why they cannot resolve, and why no prime can fix it

**No TTL declares any of the six as a subject.** The matcher for this was wrong on its first
attempt and is worth recording: `^\s*mesh:<name>` matched *indented object continuation lines* of
the multi-line `mesh:explains a , b , c .` lists in `docs_corpus.ttl` — three false positives that
would have reversed the conclusion into "the TTL does declare them". The corrected predicate is
column 0 followed by whitespace and a predicate; its positive control found the 8 resolving
targets declared across three TTLs (5 + 2 + 1) and its negative control found 0.

That 5 + 2 + 1 = **8 is an independent cross-check of §4's 8**: a grep over repo sources and a
SPARQL query over the deployed store, two instruments over two stores, agreeing on the same eight.

Every occurrence of the six in any TTL is one of exactly two things:

- an **object** of `mesh:explains` in `docs_corpus.ttl` (lines 28, 29, 38, 39, 70, 71);
- **prose inside an `rdfs:comment` string literal**, or one `#` comment, in `mesh_system.ttl`
  (lines 78, 82, 83, 88, 98, 103). Four of the six appear in no TTL at all.

So the answer to the question as the dispatch framed it: **priming `mesh_system.ttl` is not the
variable.** That file never put these verbs in subject position, so no prime of it could ever make
them resolve. The prime is not at fault and re-priming will not move this number.

The ingest reads an **S3 copy** of the TTL, not the repo file, and a two-commit-stale object has
already made one prime run report success while landing nothing (packet to `doc-tools/lane/7f`,
2026-09-23). So the repo file is the wrong subject for a claim about the store unless the two are
shown to agree. They agree: the distinct subject-name set of the repo's `mesh_system.ttl` and the
distinct subject set of the deployed MESH graph are **both 82 and their difference is empty in both
directions**, compared as sorted identity sets rather than counts.

## 5. What this means for whoever implements the gate

The gate as written is **mis-specified, not unmet**. Its own comment permits a page to explain a
verb or a class — narrowing that "would refuse one of the two things the corpus is for" — and then
demands the target resolve by SPARQL ASK. Verbs have no graph identity: they live in Python
registries, routing tables and the mesh registrar, not as RDF subjects. The two halves of the
comment cannot both be satisfied.

This is the identical argument **R-014** used to strike the reverse rule (every named thing must
carry an edge), on the grounds that "a seal is a test function name and a registry site is a Python
frozenset, neither has a graph identity". R-014 struck the reverse direction and left this one
standing; the same reasoning applies to it unchanged.

Consequence, stated plainly: anyone implementing this comment literally gets a red on 6 of 14 rows,
all six of them correct, and the honest options are to scope the ASK to class-kind targets (with
verb targets checked against the registry that actually holds them), or to strike the resolution
clause the way R-014 struck its mirror. Exempting the six by name is the option to refuse — a
by-name exemption over a population nobody derived is a guard that cannot fire.

## Method, and what is excluded

Five passes, all inside the docs engine pod over stdin. The Fuseki credential was read from the
pod's own environment, never printed and never left the pod; this file names no credential, no IP
and no cluster context. Every count above is either an enumerated identity set or a partition whose
buckets sum to a total derived separately from them — no figure here is the sum of its own parts.
