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
| ~~`datahub:catalog`~~ **two stores, not one** | 14 | **UNCLASSIFIED** | see §3d — this label was a hardcoded constant, never a derivation |
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

## 3c. What the census REFUSES under `fold, do not hand-run` — **nothing, and that took two fixes to learn**

The ruling: *"a script that is the ONLY bootstrap for a store is `fold, do not hand-run`'s debt,
refused by the census until it's folded."* Applied to the 17 resolved stores:

| verdict | stores | meaning |
|---|---|---|
| **REFUSED** | **0** | no store's only writers are unfolded hand-run scripts |
| ingest door | 2 | `neo4j:OntologyClass`, `weaviate:OntologyClass` — folded writer is doc-tools |
| mixed | 3 | `datahub:catalog`, `sql:human_task_projection`, `weaviate:Predicate` — a folded writer exists here, so their scripts are ordinary writes |
| folded | 12 | no hand-run debt |

**THE FIRST RUN REFUSED TWO STORES AND BOTH WERE WRONG.** `neo4j:OntologyClass` and
`weaviate:OntologyClass` are written by doc-tools' ingest — folded, and invisible from this tree.
The prime's own comment says it: *"the registrar / ingest MERGE it."* (The registrar only `MATCH`es
those nodes; it writes the edges BETWEEN nodes it did not create.) **That is the conformance-seal
ruling from the other side: a repo that cannot see the writes must not claim they conform, and
must not claim they are ABSENT.**

**THE SECOND RUN ALSO SAID REFUSED, AND THAT ONE WAS MY REGEX.** The cross-repo check was built and
silently matched nothing — its pattern carried a real newline inside a bracket expression (from
using `chr(10)` to dodge an escape) *and* a literal backspace byte where a word boundary was meant.
It returned "(none)" and the two false refusals stood, now wearing a check that appeared to have
cleared them. **A broken check that returns a clean negative is worse than no check**, because the
first version at least had no evidence behind it.

### The limits of this zero, stated because a zero invites the least doubt

- **It runs over the 56 resolved sites only.** A store whose sole folded writer sits among the 32
  unresolved would appear refused. It is a lower bound on folded-ness, never a proof of absence.
- **"Invoked by a bootstrap" is a name search**, so a script merely *discussed* in folded code would
  read as folded. The one case where it decided an outcome — `sql:lots`/`rates`/`results`, folded on
  `scripts/build_cost_dataset.py` — was checked by hand: `agent_fleet/cost_agent/measures.py:888`
  really does `import build_cost_dataset as dataset_builder`. The others were decided by their home
  directory, not by the name search.
- **A false FOLDED hides debt**, which is the direction this check is weakest in, and the direction
  a zero makes hardest to question.

---

## 3d. Two corrections to this document's own store table

**`datahub:catalog` IS NOT A STORE. IT IS TWO STORES UNDER ONE LABEL.** The registrar emits
`urn:li:mlModel:(urn:li:dataPlatform:mesh,…)` — the verbs. `scripts/seed_datahub_catalog.py` emits
`DatasetProperties` on platforms `postgres` and `snowflake` — a canned demo catalog. **Different
entity types, different platforms, zero overlap.**

The cause is the weakest line in the extractor: it had **no derivation rule for DataHub at all**,
returning a hardcoded `("datahub:catalog", "emitter (external catalog)")` for every one of the 14
sites. **A constant is not a derivation.** Every other substrate's store was read out of the code;
this one was asserted by me, and it merged two populations into a store that does not exist. It is
the largest row in the table, which is exactly how it escaped notice — the number looked like the
finding.

**A MIGRATION IS NOT A SECOND BOOTSTRAP**, and the `mixed` category conflated them. Reading the five
scripts behind it: `migrate_pcn_grouped_review_rows` (*"re-key the last rows"*),
`migrate_compact_to_full_iri`, `phase5_catalog_verb_migration` and `sync_predicate_to_typed_inputs`
(*"Step 2 finisher"*) are **one-shot repairs** — they converge and are done. Only
`seed_datahub_catalog` is a seeder, and by the correction above it writes a store the registrar
never touches.

> **So the class-6 collapse that `mixed` was flagged for — a store with TWO BOOTSTRAPS, two
> producers disagreeing about its shape — has ZERO instances.** That is a better answer than three
> risks, and it is only true because the label was wrong twice in the same direction: too coarse on
> the store, and too coarse on what counts as a bootstrap.

Neither correction touches the edge-type partition (13/13) or the refusal result (0 refused). Both
change the store table.

---

## 4. The second consumer — which of the thirteen edge types belongs to which write interface

| edge type | written by | interface |
|---|---|---|
| `CITES` · `DERIVED_FROM` · `PRODUCED_BY` · `PRODUCED_FOR` | `src/iagent/answer_artifact_writer.py` (also named in `gateway.py`) | **the artifact writer** |
| `PARAMETERISED_BY` | `agent_fleet/mesh_registrar/v2_substrate.py` | **the registrar** |
| `GOVERNED_BY` · `HAS_CHILD` · `REPLACED_BY` · `REQUIRES_TOOL` · `SUBJECT_TO` · `HAS_PART` · `REFERENCES` · `INSTANCE_OF` | **doc-tools** — `plugins/{compliance,maintenance,sustainment,training,manufacturing}.py`, `parsers/{mil_40051,s1000d}_ingest.py` | **THE INGEST DOOR, IN A SIBLING REPO** |

**EIGHT OF THIRTEEN ARE WRITTEN BY THE INGEST DOOR, AND THE PARTITION IS NOW COMPLETE.**
4 (artifact writer) + 1 (registrar) + 8 (ingest) = 13, with no residue and nothing undecided.

**CORRECTED 2026-09-17, AND THE CORRECTION IS THE INTERESTING PART.** This table first reported
five, with `HAS_PART`, `REFERENCES` and `INSTANCE_OF` as *"no writer found"* — and said explicitly
that filing them under doc-tools to complete the table *"would be inventing the tidy answer."*
Master then landed `596c279`, another lane's registrar/SDK conformance seal, carrying live-graph
counts this census could not reach: `INSTANCE_OF` 21, `HAS_CHILD` 54, `SUBJECT_TO` 20,
`GOVERNED_BY` 7, `REQUIRES_TOOL` 2, `HAS_PART` 1, `REPLACED_BY` 1, `REFERENCES` 1 — all attributed
to doc-tools' domain-plugin ingest. **I did not adopt that attribution; I measured it**, and all
three do carry `MERGE` sites there (`s1000d_ingest.py`, `mil_40051_ingest.py`,
`plugins/manufacturing.py`).

So the tidy answer was the true one — and refusing to assert it unmeasured was still right, because
the same refusal is what makes this line worth reading now. The three were absent from my table
because of **my search's reach**, not the fleet's state: I had grepped doc-tools for the five I
already suspected rather than for all thirteen. *A list checked against the names you expect
confirms your expectation.*

 ADR-0054 §4 puts enforcement at *the write
interface*, and the artifact writer and the registrar are the two this repo has. The five above are
`MERGE`d by doc-tools plugins and parsers — a third writer, in a different repository, reaching the
same Neo4j. An enforcement point placed on the two doors here **cannot see 38% of the structural
edge types**, and the graph will not look any different for it.

> **CORRECTED, AND THE CORRECTION IS WORSE THAN THE WARNING.** I first wrote that grepping this
> tree for these types returns *zero* files — a clean, confident, wrong negative. **It returns
> six.** A measurement snapshot (`docs/measurements/verb-snapshot-b967f57-rev112.txt`), two ingest
> tests, and two fixtures all name them. My zero came from my own scan's filters: `.txt` was not in
> its suffix list and `tests/` was not in its scopes at all.
>
> So the hazard for a seal built here is not an empty set that looks suspicious. It is **a false
> NON-zero**: the seal finds a snapshot showing the edges exist and tests exercising the producer,
> concludes the types are present, and asserts compliance **over evidence ABOUT a writer rather
> than over the writer** — and that passes review, forever. Found by `lane/5f`, not by me; I had
> warned them about the opposite failure using a figure my own instrument had narrowed.

**INDEPENDENT CORROBORATION IS WHY THIS IS A FINDING AND NOT A HUNCH.** Two lanes reached the
third writer from opposite directions in the same week — this census by parsing write sites, and
`596c279` by reconciling the SDK's declaration against the registrar's writes — and neither read
the other's work first. That seal also declines to read the graph for its *declared-but-never-
written* direction, for exactly the reason the ruling gives: the live edges have another repo as
their author, so a graph-reading seal would red on someone else's correct behaviour.

---

## 3b. The two rulings this census produced

**A TRANSACTION ACROSS FOUR NODE KINDS IS CLASSIFIED BY ITS STRICTEST STORE.** §4's per-store
refusal has no single store to check when one atomic write lands in four, so the ruling is:
**the write interface checks EVERY target store in the transaction and refuses if any one of them
is a class it may not write — all-or-nothing on the strictest.** That is the honest reading of
"unwritable" for an atomic write: there is no half-refusal available, because there is no half
transaction. `answer_artifact_writer._tx_merge` is the worked case — six statements across `Actor`,
`AnswerArtifact`, `Source` and `WatermarkSequence`, one fate. Goes into the §4 amendment.

**THE DOC-TOOLS CONFORMANCE SEAL CANNOT LIVE IN THIS REPO.** Derive its population by grepping
`invincible-agent` and it asserts compliance over an **empty set, forever** — all eight ingest-door
edge types return zero files here. The ruled split:

| where | what it asserts |
|---|---|
| the SDK | **declares** the ingest door's edge types |
| doc-tools, in its own repo | asserts **its own conformance** against that declaration |
| this repo's seal | asserts only that **no writer HERE emits an ingest-door type** |

This is the *form-checked, existence-not-checked* rule from the citation checker, applied to a
seal: **a repo that cannot see the writes must not claim they conform.** A seal is a claim about a
population, and a population derived where the members cannot exist is a green that means nothing —
the same shape as this document's §0, one level up.

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
