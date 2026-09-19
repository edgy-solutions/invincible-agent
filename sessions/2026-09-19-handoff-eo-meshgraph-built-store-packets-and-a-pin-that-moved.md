# Handoff — eo lane: `MeshGraph` is built, the store packets are filed, and the SDK pin moved under me

to: ia-eo/lane/eo
read-by:

From `invincible-agent-28` **`[5401d7]`** (`ia-eo`/`lane/eo`). **The ref is not decoration — a
second live session shares the bare name `invincible-agent-28` (`[09c0fb]`), which misrouted a STOP
to me today. Address this lane by lane, or by name AND ref; never by the bare name.**

---

## 1. State, as shas

| | value |
|---|---|
| `lane/eo` HEAD | **`ef7a37e`** — ahead 2, behind 8 at time of writing |
| base (merge-base with master) | `3849f72` — the lane was fast-forwarded to master, then two commits added |
| the two in flight | `60d73e8` store packets · `ef7a37e` `Neo4jGraph` |
| **SDK pin — THIS LANE** | **`v0.9.2`** (`pyproject.toml`), installed `0.9.2` — consistent |
| **SDK pin — MASTER** | **`v0.9.3`** (landed in `262fedb`) |

## 2. THE ONE THING THAT WILL BITE ON MERGE, AND IT IS BY DESIGN

**Merging master brings `pyproject`'s pin to `v0.9.3` while this venv still has `0.9.2`, and
`tests/test_mesh_graph_conforms.py::test_the_imported_sdk_IS_the_pinned_artifact` will RED.**

That is the arm working, not breaking. It exists so conformance cannot be proved against whatever
`iagent_mesh` happens to be importable. **Fix it by syncing the environment (`uv sync --locked
--extra agent-fleet`), never by loosening the arm.**

**And re-run the conformance file after syncing, because `Neo4jGraph` was written against
`v0.9.2`'s `MeshGraph` Protocol.** `262fedb` bumped the fleet for the *ledger vocabulary*; whether
`MeshGraph`'s nine operations or `MODES` moved in `0.9.3` is **unverified from here** — I did not
read the 0.9.3 tag. The structural arm (`test_it_satisfies_the_protocol_structurally`) is what will
tell you, and it compares signatures, not just names.

## 3. What landed

**`ef7a37e` — `agent_fleet/ontology_service/mesh_graph.py` + `tests/test_mesh_graph_conforms.py`.**
All nine Protocol operations over an INJECTED driver (the module imports none, asserted by an arm),
identity refused for service subjects on all nine, every return a `MeshResult`. 30 arms, no skips.
**The routes are NOT migrated** — that is the `mesh_vectors` precedent, and the drift arm below
assumes it.

Three things in there worth knowing before touching it:

- **The drift arm caught its first error before commit, and the error was mine.** The Cypher exists
  here *and* in `main.py` until routes migrate, so the test reads `main.py`'s constants by AST and
  asserts they still match. It failed on first run: I had read `_SERVED_CLASSES_CYPHER` nine lines
  deep and missed a `UNION` branch — which is the entire mechanism behind `include_referents`.
  **When a route migrates, delete its row from that parametrize — not the assertion.**
- **`include_referents` is a flagged contradiction, not a settled default.** The Protocol declares
  `False`; `main.py`'s `_served_class_uris` declares `True`; the operation's own summary calls it
  *"the productive-option gate"*, which is the `True` question. One of the three is wrong. I took
  the Protocol's, because the Protocol is the contract, and documented it. **The trap is delayed:**
  the referent set is EMPTY in the live graph, so both readings agree today and a wrong default
  looks correct — until someone declares a referent, which the ruling says is the right thing to do.
- **`path`'s hop bound is read from `main.py`'s `Field(4, ge=1, le=8)`**, with an arm asserting they
  still agree. A default invented locally becomes a contract.

**`60d73e8` — six store packets** under `docs/plans/store-class-*.md`, plus corrections to
`fleet-write-census-store-classes.md`.

## 4. The numbers, and what they replaced

The dispatch asked for *"the eleven unclassified stores as packets"*. **Eleven is now the
CLASSIFIED count.** Three rulings landed after that figure was set (§2 widening `rebuildable` to a
durable declared **log**; scripts classified by their target; an atomic write classified by its
strictest store). Re-derived: **18 stores — 12 classified, 1 disagreeing, 5 open.**

**The second basis is the method worth reusing.** `setup/prime_databases.py` already holds the
fleet's executable answer to "what is rebuildable": it clears `OntologyClass`, every Weaviate
collection, the Jena dataset and the MinIO TTLs — *"the ingest rebuilds all of it"* — and PRESERVES
the answer-durability graph plus the three Postgres stores. **Classifying against both §2's prose
and the drop set turns a reading into a measurement:** agreement corroborates, and the single
disagreement becomes the deliverable instead of a judgment made silently.

Two findings inside that:

- **A name is not a class; the writer is.** `sql:human_task_projection` is *named* a projection and
  is not one — `register_task` materialises rows from the caller's arguments plus Topaz state, and
  no log replays it. Classified by name it would have been `rebuildable` with nothing to rebuild it
  from.
- **`sql:answer_artifact_projection` is the one disagreement, and it resolves to a coupling.** It
  cannot be rebuilt alone: empty it without resetting `sql:projector_cursor` and every replayed row
  lands below the cursor. That is the stranded-cursor bug of 2026-07-18, where both stores were
  individually defensible and the invariant BETWEEN them broke. `WatermarkSequence`,
  `projector_cursor` and `answer_artifact_projection` share a fate; a per-store field cannot say so.

## 5. Suite

Last uncontended full run on this tree: **3 failed, 4334 passed, 307 skipped — exit code 1.**
**None of the three are this lane's:**

- `test_the_mirror_register_ONLY_SHRINKS` — cortex-60 fixed the gaps in `cortex-ui`; the register
  lives here and only a same-repo lane can shrink it. Lane 1's.
- `test_phantom_allowlist_is_honest[...safety-walk-sheet.md]` and `[...finance-walk-sheet.md]` —
  sheets added at `0f1f2cb` and later deleted, then allowlisted as *phantoms*. The test is right:
  in history means ROT, not phantom.

**One observation on that test worth more than its rows: its failing SET was not stable today** —
one row, then two, then three in isolation, on the same tree. It shells out to `git log --all`, and
`--all` reads whatever refs happen to exist locally. I did not prove that is the mechanism and am
not asserting it; a seal whose verdict moves deserves attention before the rows it reports do.

## 6. EXACT NEXT STEP

1. `git merge origin/master` (clean at time of writing; re-check with `git merge-tree`).
2. `uv sync --locked --extra agent-fleet` — **required**, the pin moves to `v0.9.3`.
3. `uv run --frozen pytest tests/test_mesh_graph_conforms.py -v` — expect the pinned-artifact arm
   green after the sync, and **read `test_it_satisfies_the_protocol_structurally` carefully**: it is
   the only thing here that knows whether `0.9.3` moved `MeshGraph`.
4. Full suite, **uncontended** — do not run a second suite or a cross-repo grep beside it. A
   concurrent run exhausted the paging file today and a subprocess failure surfaced as
   `pricing.py is not standalone-importable` with an EMPTY stderr, which reads exactly like a code
   defect. Exit code `0xC000012D`.

**Nothing is blocked on this lane, and no walk depends on either commit.**

## 7. Open, and NOT this lane's to rule

- `include_referents` — three declarations, one wrong (§3 above). ca owns the Protocol.
- The five open store fields — `datahub:dataset`'s `authority` (it describes systems that do not
  exist), `datahub:mlModel`'s `sync obligation` (the fleet writes into a system it does not own and
  never reads back), and §6 `releasability`, which `sql:user_canvas` is the waiting case for.
- Whether ADR-0054 can express *these three stores share a fate* — 5f is carrying that amendment.

Lane: ia-eo/lane/eo
