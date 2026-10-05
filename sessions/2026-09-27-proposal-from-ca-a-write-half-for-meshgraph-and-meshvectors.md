# Proposal — a write half for `MeshGraph`, `MeshVectors`, and `MeshOntology`

to: invincible-agent/seat/architect
from: iagent-mesh-sdk / `lane/ca`, 2026-09-27
re: the fifth order ("Mesh* work, tonight"), item 2 — proposal only, no code
re (addendum, same day): your ruling on the docstring correction — "the write half then goes into
ca's proposal with Jena first, as 7f recommends" — folded in as new §1a below; the docstring itself
is corrected separately in `iagent_mesh/interfaces.py`
cites: this month's writer defects (below), `iagent_mesh/interfaces.py` (`MeshGraph`, `MeshVectors`,
`MeshOntology` — all read-only today), `iagent_mesh/results.py` (`MeshResult`),
`doc-tools/sessions/2026-09-27-report-7f-mesh-jena-update-route-and-writer-inventory.md` (the Jena
update route measured live, and the writer inventory §1a draws on)

## 0. The claim

Three writers — the registrar (`agent_fleet/mesh_registrar/`), doc-tools
(`agent_fleet/docs_agent/`), and the backfill (`scripts/backfill_vector_space.py`) — each own their
own write path into Neo4j and/or Weaviate. There is no shared write contract; there are three.
Researching this month's commit history for the grounding turned up **seven** distinct writer
defects, not five — more evidence for the claim, not less. Five are cited below because each
grounds a distinct piece of the design; the other two (both registrar, both the identical
named-vs-unnamed-space shape as defect 2, cited once) are the same bug recurring, which is itself
part of the argument: **one writer had the same defect twice in two collections**, which a shared
write half makes structurally impossible rather than a code-review habit to keep catching.

## 1. Five defects, each grounding one requirement below

| # | Writer | Commit / date | What happened | Grounds |
|---|--------|---------------|----------------|---------|
| 1 | registrar | `2c7b85cf`, 2026-09-25 | A presentation registration failed, was classified and logged, fell back to a DataHub audit emit, and returned — touching **neither** Neo4j nor Weaviate. 11 URNs registered in DataHub, 0 corresponding rows in the graph or the vector store. The caller could not tell "written" from "silently declined" from the return value. | §3 refuse-not-strip; §4 a result type that names the state |
| 2 | registrar | `19bc52fd`/`14b23c23`, 2026-09-19 | The Predicate and one other collection each **declared** a named vector space (`default`) at creation, then **wrote via a positional `insert(vector=[...])`**, which lands in Weaviate's legacy unnamed slot. Every write reported success; the named space stayed empty; every search against it returned zero. The identical shape occurred **twice, in two collections, in the same writer**, three months apart in commit distance but the same root cause both times. | §6 vector always by name |
| 3 | backfill | `657bd951`, 2026-09-19 | The `--offset` resume path advanced its "seen" counter for skipped rows without recording their outcome, so the partition/completeness guard **fired on every offset run** — a resumable job whose own resume broke its own correctness check. | §5 upsert by deterministic id (a job must be able to ask "did this id already land?" without reconstructing that answer from a counter) |
| 4 | backfill | `c5da2033`, 2026-09-19 | Blank-node detection matched one of two legal spellings of a blank node id; the 3 rows in the unmatched spelling (of 1,299) would have been silently reclassified as named. Separately, a second guard read a field that one row shape does not have, returned the "correct" answer for the **wrong reason**, and would have passed everything the day that stopped being a coincidence. | §5 upsert by deterministic id (identity must be recognized correctly, not incidentally) |
| 5 | doc-tools | `42b74938`, 2026-09-17 | `docs_agent` registered `mesh:explain` as a full IRI instead of the compact form its own registrar expects; the registrar's own IRI-stripping turned it into a malformed relationship type in Neo4j. Nothing queries that type — the verb registered cleanly and reached nothing. | §5 upsert by deterministic id (each writer built its own notion of "the id", and they disagreed) |

Not cited above but from the same search, for completeness: two more backfill defects
(`7ac0765e`, `c5da2033`'s sibling in the same file) in tooling/self-check correctness rather than
the write path itself — grounding, but redundantly with #3/#4 above.

## 1a. `MeshOntology` / Jena goes first

Added after the docstring correction: `iagent_mesh/interfaces.py`'s `MeshOntology` no longer claims
"no verified working path" — 7f measured `POST update=<sparql>` to `/{dataset}/update` returning
200 against sandbox Fuseki. The blocker was false; what remains is a real one — **no ruling yet**
on the SDK write shape or graph scoping. This section is that: Jena first, ahead of Neo4j and
Weaviate, for the same reason 7f gave in the report cited above, plus one defect of its own kind
that the Neo4j/Weaviate defects in §1 don't cover:

- **One production caller, not three.** `execute_update` (`jena_client.py:79-87`) has exactly one
  live call site — `semantic_assets.py:531`. Neo4j has the registrar and doc-tools; Weaviate has
  the registrar, doc-tools, and the backfill, each with its own vector-argument shape. A shared
  writer replacing one caller is a seam, not a migration.
- **The writer must own graph scoping — this is a live defect, not a hypothetical.** Of four
  SPARQL-emitting plugins, only `sustainment.py` scopes its inserts with `GRAPH <...>`.
  `compliance.py:155`, `maintenance.py:330`, and `manufacturing.py:423` each emit a bare
  `INSERT DATA {{...}}` that lands in Jena's **default graph** — invisible to the mesh resolver.
  Three domains' ingests have been silently not reaching what the mesh reads. This is defect #6,
  uncited in §1 because it's Jena-specific, and it grounds a requirement §1–§6 don't: **a caller
  must not be able to emit an unscoped write at all** — the same "structurally unavailable, not a
  lint rule" standard §6 asks for vectors, applied to graph scoping. (The architect has separately
  authorized 7f to fix this at the plugin/caller layer in doc-tools, sealed on these three
  offenders, own PR, not merged — the SDK write half is the second, permanent half of that fix: once
  it owns scoping, a plugin cannot regress into a fourth offender.)
- **Today's loudness is inconsistent, not absent.** `semantic_assets.py:531`'s own caller logs an
  `execute_update` failure rather than raising it — the same "wrote nothing, said nothing" shape as
  §1's defect #1, just not yet caught in a commit. `MeshWriteResult` (§4) closes this the same way
  for Jena as for Neo4j/Weaviate: a failed update is `failed`, not a logged line the caller moves
  past.
- **Weaviate goes last, not first, per 7f's own recommendation**: three call sites, three
  vector-argument shapes, and one deliberately-preserved refusal (`skipped_would_strip_vector`,
  §3) to carry over exactly. Neo4j is the middle case. Jena's route is now the only one of the
  three that is both freshly verified end-to-end and down to a single caller — the cheapest place
  to prove the shared writer's contract before it has to absorb Weaviate's harder cases.

## 2. What the three defect classes have in common

Read together, they are not five unrelated bugs:

- **A write can report success while writing nothing, or writing to the wrong place.** (#1, #2)
- **A write's identity is reconstructed differently by different code**, so two writers disagree
  about whether the same thing already exists. (#3, #4, #5)
- **None of the three writers' results can be asked "did the vector actually land?"** — Weaviate's
  own 200 does not distinguish "wrote to the space you meant" from "wrote to the one nobody
  reads."

A shared write half does not make embedding failures or Weaviate quirks disappear. It makes them
**visible in one type, once**, the way `MeshResult` already did for reads — instead of three
writers each discovering the same failure mode independently, on their own schedule, this month's
five (of seven) at a time.

## 3. Refuse-not-strip on embed failure

**Today's failure mode (defect 1, and `seed_sandbox_predicates.py`'s silent no-vector write found
in the same search): a write whose vector could not be produced was written anyway, without one,
with nothing in the return saying so.** That is a stripped write masquerading as a normal one.

Proposed default: **if a write declares it needs a vector and embedding fails, the whole write is
refused** — no row lands in either store, and the caller gets a failure, not a partial write it
has to notice is partial. A write that is allowed to proceed without a vector must **say so up
front** (an explicit `vector_required=False`, or equivalent), not discover it after the fact.

## 4. `written` / `written_without_vector` in the result

Given §3, `written_without_vector` is not "the vector embed failed, we shrugged" — it is **a state
a caller explicitly opted into**, and the result must show which one happened, the same way
`MeshResult.mode` shows how a read was answered instead of leaving it to be inferred. Sketch, not
a signature (illustrative only):

```
MeshWriteResult:
    outcome: "written" | "written_without_vector" | "failed" | "unreachable"
    id: str                    # the deterministic id that was written, echoed back
    detail: Optional[str]      # required on failed/unreachable, same discipline as MeshResult
```

`written_without_vector` only reachable when the caller declared the vector optional; a required
vector that fails to embed is `failed`, never silently `written_without_vector`. This is the same
"a degraded mode must be named, never served silently" rule `MeshResult.mode` already states,
applied to writes.

## 5. Upsert by deterministic id

**The caller supplies the id; no writer generates one, and no writer derives one by re-parsing an
IRI or a URN its own way (defect 5).** One write to the same id is an update, not a duplicate,
regardless of which of the three writers made it or how many times. This is what would have made
the backfill's resume guard (#3) askable directly ("has this id already landed?") instead of
reconstructed from a row counter that the offset path did not update correctly.

## 6. Vector always by name

**Every vector write addresses a named vector space; nothing calls the positional/legacy
`insert(vector=[...])` form, ever.** Defect #2 happened twice in one writer because the underlying
client library allows writing to an unnamed slot even when a named space exists and looks
identical from the write call's return value. A shared write half that only exposes a
by-name write path makes the mistake structurally unavailable rather than a lint rule to remember.

## 7. What this proposal does NOT decide

- **Protocol shape.** Whether `MeshGraph`/`MeshVectors` grow write methods directly, or a separate
  `MeshGraphWriter`/`MeshVectorsWriter` Protocol pair keeps the existing read-only Protocols pure
  (the current interfaces' whole design point is "read-only by design, documented, ruled" — adding
  writes to the same Protocol is a bigger claim than adding a sibling one).
- **Who computes the embedding.** Given a name and a value, does the write half call an embedder
  itself, or only accept an already-computed vector? Doc-tools, the registrar and the backfill may
  not agree on this today, and that disagreement is exactly the kind of thing worth deciding once.
- **The exact outcome vocabulary.** §4's sketch is illustrative; `failed` vs `unreachable` for a
  write needs the same care `MeshResult` gave reads (a store that refused the write is a different
  remedy from a store that could not be reached at all).
- **Authorization.** Whether a write requires `Initiator.require_person`, admits a `delegate`, or
  is scoped some other way is untouched here — this proposal is about ONE shape for three writers,
  not about who may call it.
- **Migration.** §1a settles *which store first* (Jena, then Neo4j, then Weaviate) but not the
  rest: whether the registrar, doc-tools and the backfill move to the new write half together or
  one caller at a time within each store, is still a rollout decision, not a design one.

## 8. Rulings I'd ask you to make

1. One write-capable Protocol pair, or writes added to the existing read Protocols — and if the
   former, its name. (§1a's Jena caller needs this decided before it can be built at all.)
2. Embedder ownership: SDK-side or caller-supplied vector only.
3. The outcome vocabulary for a write result (§4's sketch, or your own), and whether
   `vector_required` defaults to `True` (this proposal's recommendation, matching refuse-not-strip)
   or `False`.
4. Whether this belongs on `lane/ca` once ruled, or is scoped as its own lane.
5. Whether the graph-scoping rule in §1a (a caller cannot emit an unscoped write) is enforced only
   in the new SDK writer, or also asserted as a Jena-side constraint (a named-graph-only mode, if
   one exists) — belt-and-suspenders vs. one seam, one owner.

Lane: ia-ca/lane/ca
