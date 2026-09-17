---
id:         fleet-write-census-store-classes
status:     in-flight
owner:      invincible-agent-28 [5401d7] - ia-eo / lane/eo
blocked-on: a ruling on whether a PROJECTION is rebuildable, and whether one-shot scripts are stores under ADR-0054 section 4
trigger:
closed-by:
repo:       invincible-agent
summary:    ADR-0054 section 7's named input - the fleet-wide write census, counted as STORES rather than writes. 88 write sites (not the 67 first reported; three instrument defects are shown), 17 stores, 6 classified and 11 UNCLASSIFIED because section 2's text does not decide them. Also the thirteen structural edge types mapped to their write interfaces: five are written by doc-tools, a third writer outside the two doors.
---

# The fleet write census — stores, not writes

**Lane:** ia-eo / `lane/eo` · **Derived at:** `3078cad` (lane/eo, master-based) · **Date:** 2026-09-17

ADR-0054 §7 names this document: *"The input is the eo lane's fleet-wide write census… the
classification of each store is the census's output."* §2 fixes what it must count: *"it gives the
census **one thing to count: stores, not writes**."*

---

## 0. THE NUMBER MOVED, AND THE OLD ONE WAS MY INSTRUMENT

**The census reported 67 write sites. It is 88.** The correction is reported first because the
dispatch called 67 *"the number the whole data-class ADR has been waiting to be measured against"*,
and a wrong number with a census's authority is worse than no number.

Three defects in the instrument, each found by the census contradicting itself:

| # | defect | effect | how it surfaced |
|---|---|---|---|
| 1 | keywords matched as **unanchored substrings** | a Postgres `CREATE TABLE … (payload JSONB)` filed as a **Jena** write — `payload` contains `LOAD ` | store derivation asked which named graph, and there wasn't one |
| 2 | `SQL_WRITE` spelled `INSERT `/`DELETE ` only | `CREATE TABLE`, `ALTER TABLE`, `ON CONFLICT`, `DELETE FROM` **never matched at all** — 19 writes invisible | the anchoring fix raised the count instead of lowering it |
| 3 | the method table knows **drivers, not verbs** | `jena` fell to **zero**, and a fleet whose prime loads ontologies into Fuseki cannot have zero Jena writes | a zero that could not be true |

Defect 1 is the blind spot this census **declared up front** — *parse, do not match* — obeyed by
the finder and violated by the classifier. Defect 3 is worse in kind: Jena is written over HTTP by
`_execute_sparql_update`, so **a store reached by a verb rather than by a driver is invisible to a
method census.** The substrate coverage was itself a sample.

> **A zero is the hardest reading to doubt, because it looks like a clean finding.** All three
> defects produced confident numbers. What caught them was the SECOND consumer — deriving store
> identity asked each site a question its substrate label had to survive, and three did not.

**Still a sample, and named as such:** doc-tools writes ontologies to Fuseki from a sibling repo,
so its writes are outside this tree and outside this count.

---

## 1. The store set — 17 resolved, 32 sites unresolved

| store | sites | ADR-0054 class | basis |
|---|---|---|---|
| `datahub:catalog` | 14 | **UNCLASSIFIED** | §2 names no catalog kind; authority is the open question |
| `neo4j:OntologyClass` | 8 | `rebuildable` | §2: *"ontology, vectors, registrations…"* |
| `weaviate:Predicate` | 8 | `rebuildable` | §2: *"vectors, registrations"* |
| `weaviate:OntologyClass` | 3 | `rebuildable` | §2, same clause |
| `neo4j:AnswerArtifact` | 2 | `stateful`, iagent-authored | §2: *"artifacts, lineage"* |
| `neo4j:Source` | 1 | `stateful`, iagent-authored | §2: lineage |
| `neo4j:Actor` | 2 | **UNCLASSIFIED** | §2 names no actor kind |
| `neo4j:` **one transaction, four labels** | 1 | **UNCLASSIFIED** | `Actor`+`AnswerArtifact`+`Source`+`WatermarkSequence` in one atomic write — see §3 |
| `sql:projector_cursor` | 3 | `stateful`, iagent-authored | §2: *"checkpoints"* |
| `sql:projector_skip_log` | 1 | `stateful`, iagent-authored | §2: checkpoints, same mechanism |
| `sql:human_task_projection` | 5 | **UNCLASSIFIED** | a projection is rebuildable *by replay*, which §2 does not say is `rebuildable` — see §2 below |
| `sql:answer_artifact_projection` | 1 | **UNCLASSIFIED** | same question |
| `sql:user_canvas` | 2 | **UNCLASSIFIED** | user-authored; §2 names no user-content kind |
| `sql:lots` / `sql:rates` / `sql:results` | 4 | **UNCLASSIFIED** | cost dataset; authority is upstream data, not this tree |
| `jena:http://internal/decision` | 1 | **UNCLASSIFIED** | a decision graph is neither ontology nor artifact |

**Classified: 6 stores / 25 sites. UNCLASSIFIED: 11 stores / 31 sites.**

**THE UNCLASSIFIED SET IS THE DELIVERABLE, NOT THE RESIDUE.** Every one of the eleven is a store
the ADR's §2 text does not decide, and §2 is explicit about what to do with them: *"A store that
fits none of the three shapes **declares its four fields anyway**, rather than being filed under
the nearest."* Filing `datahub:catalog` as `rebuildable` because a seed script re-emits it would be
the exact failure §2's worked example warns about — a schema making a claim nobody ruled.

---

## 2. The question the census cannot answer: is a projection `rebuildable`?

Nine sites across three projection tables turn on one unruled word. §2 defines `rebuildable` as
*"the prime may drop and re-land it"* — from **seed and overlay**. A projection is reproducible too,
but from **a durable event log**, which is a different claim: it survives a prime, and it does not
survive losing the log.

Reading it either way is defensible and they lead opposite places:

- **`rebuildable`** — the projector may drop and rebuild, and §5's enforcement would permit that.
- **`stateful`** — the table is preserved, and a rebuild is an operation with its own authorization.

**Not decided here.** The four-field schema has room for the honest answer — reproducibility
`rebuildable`, authority `upstream` (the log decides what the value is) — and that combination is
precisely the kind §2 says must declare its fields rather than take a shape name. Flagged for the
architect as the first ruling this census demands.

---

## 3. Three findings about the writes themselves

**One TRANSACTION writes four node kinds, and the first version of this line was wrong.** I wrote
*"one statement writes four labels"* from my own tool's output; the statement at
`answer_artifact_writer.py:452` writes only `WatermarkSequence`, and the four came from my store
derivation falling back to the enclosing function. Measured properly, it is stronger:
`session.execute_write(self._tx_merge, …)` runs **six statements across `Actor`, `AnswerArtifact`,
`Source` and `WatermarkSequence` in one atomic transaction**.

That matters for §4's third enforcement point — *the write interface refuses a store whose class it
may not write*. **An atomic transaction has one fate and four stores.** If any two of those four
ever carry different classes, the interface has no single store to check and no way to refuse half
a transaction. It is the first concrete case where per-store classing meets a write that does not
respect store boundaries, and it was nearly reported as something weaker because **a derived
artifact of my instrument read exactly like a finding.**

**32 of 88 sites could not have their store derived**, and they are listed in the appendix rather
than assigned. The largest group is Cypher that `MATCH`es and `DELETE`s without a `MERGE`/`CREATE`
label — migration scripts, mostly — where the store is real but the label is not in the statement.

**The `scripts/` tree holds 45 of 88 sites — MORE THAN HALF.** (`src/` 22, `agent_fleet/` 16,
`setup/` 5.) Whether one-shot migration and seed scripts are stores under §4's enforcement, or a
category the ADR does not govern, is unruled — and it is the ruling with the widest blast radius in
this document, because it decides whether §4's interface check governs 51% of the fleet's writes or
none of them. They are counted here because excluding them would have been a decision made by the
instrument rather than by the architect.

---

## 4. The second consumer — which of the thirteen edge types belongs to which write interface

| edge type | written by | interface |
|---|---|---|
| `CITES` · `DERIVED_FROM` · `PRODUCED_BY` · `PRODUCED_FOR` | `src/iagent/answer_artifact_writer.py` (also named in `gateway.py`) | **the artifact writer** |
| `PARAMETERISED_BY` | `agent_fleet/mesh_registrar/v2_substrate.py` | **the registrar** |
| `GOVERNED_BY` · `HAS_CHILD` · `REPLACED_BY` · `REQUIRES_TOOL` · `SUBJECT_TO` | **doc-tools** — `plugins/{compliance,maintenance,sustainment,training}.py`, `parsers/{mil_40051,s1000d}_ingest.py` | **A THIRD WRITER, IN A SIBLING REPO** |
| `HAS_PART` · `REFERENCES` | named in this tree, `MERGE`d by nothing in it | **no writer found** |
| `INSTANCE_OF` | named only in ADR-0021's prose here | **no code writer found** |

**FIVE OF THIRTEEN ARE WRITTEN BY NEITHER DOOR.** ADR-0054 §4 puts enforcement at *the write
interface*, and the artifact writer and the registrar are the two this repo has. The five above are
`MERGE`d by doc-tools plugins and parsers — a third writer, in a different repository, reaching the
same Neo4j. An enforcement point placed on the two doors here **cannot see 38% of the structural
edge types**, and the graph will not look any different for it.

> **Their absence from this tree reads exactly like absence from the fleet.** Grepping here returns
> zero files for all five — a clean, confident, wrong negative. It took a search in the sibling repo
> to turn that zero into a writer, which is the same shape §1 of this document is about.

`HAS_PART`, `REFERENCES` and `INSTANCE_OF` are a different case and are **not** being reported as
doc-tools' — they are named in this tree and written by nothing found in either repo. Whether they
are aspirational vocabulary, written by a third party, or written through a path neither search
covers is **unresolved**, and filing them under doc-tools to complete the table would be inventing
the tidy answer.

---

## 4. What this does not establish

- **Not the thirteen edge types.** That mapping is the second consumer and is reported separately;
  the edge-type scan is unchanged by these corrections, since it never used the write classifier.
- **Not doc-tools.** A sibling repo writes ontologies to Fuseki; those sites are not in this tree.
- **Not the four unresolved substrates' real stores** — a MinIO bucket bound to a variable and a
  Weaviate collection bound to a loop variable are determinate at runtime and undetermined here.
- **Not a ruling on any class.** §7: *"No store is reclassified by this ADR."* This is the input.

---

## Appendix — the 32 unresolved sites

Regenerate with `scratchpad/write_census.py` then `scratchpad/store_identity.py`. Both carry their
blind spots in their module docstrings, and the alias-resolution positive control (199 aliases
resolved) is asserted on every run — *"0 aliased" is indistinguishable from "alias resolution is
broken" without it.*
