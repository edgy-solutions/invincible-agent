# Handoff — 74 (safety lane): the backfill is built, the apply is Chris's, one row is owed

lane/74 in `c:\Users\cnogr\git\ia-74`, at `9338a99`, tree clean, in sync with `origin/lane/74`.
Predecessor session ref `[bd26bdc1]`. Measurements below are UTC, so dated 2026-09-20.

## Start cold

    git -C c:\Users\cnogr\git\ia-74 pull --rebase origin master     # 14 behind at close; REBASE, never merge
    uv sync --extra agent-fleet                                     # AGENTS.md:101 — there is NO --locked
    # then the SAME TREE check, AGENTS.md:102
    uv run --frozen --extra agent-fleet python -m pytest tests/routing tests/safety -q

Last green: 842 passed / 157 skipped, at the pre-rebase head.

## Standing orders — in force, not up for reinterpretation

* **`--apply` is Chris's**, in daylight, never during a roll. Not mine, not a successor's.
* Nothing touches a shared store without Chris. Deleting the existing blank rows is **not** ordered.
* I do not commit in another lane's worktree, and I never release commits I did not write.
* **The wire-key warning travels with every mention of the backfill.** A correctly repaired row
  reads as *vectorless* on every legacy instrument (REST `vector` → None, `_additional{vector}` →
  `[]`) while `vectors.default` holds 768 dims. Only `nearObject(self)` — **self within top-k at
  distance ~0, never `rows[0]`** — tells the two states apart.

## State: verified

* **Fix D proven in the field.** Predicate went 138 all-would-relocate → 89 already-named + 44,
  seven minutes apart across the roll, with OntologyClass unchanged as the control.
* **The blank-node ruling is discharged.** doc-tools' Weaviate leg had no `!isBlank` filter while
  its Neo4j sibling has two; 7f confirmed and fixed it at `a8e2b3e`. Blank rows are 96.2% of
  `OntologyClass` and that is a **rate, not a level** — rdflib mints a fresh BNode per parse and
  the row uuid is `uuid5(uri)`, so every re-ingest *adds* blanks.
* **A second blank spelling exists**: `n<32hex>b246`, 3 of 1,299, which doc-tools' documented
  regex misses. Both spellings are stated in the script with their evidence.
* **The partition identity holds**, and it — not any count — is the script's expectation:
  `blank-skipped + no-vector + would-relocate + already-named + blank-AMBIGUOUS + skipped_by_range = walked`.
* **The `risk_acceptance_medium` task row does not exist.** `human_task_projection` = 59 rows,
  **zero** `risk_acceptance%`, at roll sha `c0005142a610bc7759cfc8953666aee7c6064632`, 03:22Z.
  Narrowed: the guard at [gateway.py:6005-6006](src/iagent/gateway.py#L6005-L6006) **never
  entered** — neither the success line nor the failure record appears, against a positive control
  of 8 artifact lines in a 3506-line pod log. So one of `_expert` / `_rr` was falsy; a dispatch was
  not attempted and did not fail. engine-safety still emits `review_request` for HAZ-1003 on the
  rolled image (called directly on port 8099, bypassing the gateway, so no task opened).
* **The registrar writes by name on both branches** — `upsert_predicate_row` in
  [v2_substrate.py:613](agent_fleet/mesh_registrar/v2_substrate.py#L613),
  `write_kwargs["vector"] = named_vector(predicate_vector)`, replace-else-insert at `:615-618`.
  The architect's guess that page loads refill the legacy slot is **not confirmed**.

## State: measured but not explained — routed elsewhere

* **The vectorless set is two whole namespaces, not sixteen scattered rows.** Only 11 BFO and 2
  IOF Core rows exist and 12 of the 13 are vectorless. `IOF_Core` is manifested **twice**
  (`prime_databases.py:174` and `:229`). The architect routes this; I did not chase it.
* **doc-tools' half of fix D is not rolled.** Until it is, a re-ingest undoes an `OntologyClass`
  backfill. Chris should know this before running the OntologyClass half.

## Decisions, and why

* The blank check runs **first** in `relocate()` so outcomes partition — a row cannot be both.
* `partition_ok` was extracted as a plain predicate so it could be exercised directly rather than
  only through a run. That is what caught its own bug (below).
* `URILESS_CLASSES = ("Predicate",)` names, in the script, that the blank check is inert there and
  why that is correct — rather than leaving it as an accident of the data.
* I did **not** adopt Lane 1's twin-naming in `verify_self`. It is better at the moment someone is
  watching a write, but it is not on the architect's list and this is a morning-critical script.
  Offered in a packet; five lines if they say the word.

## Tried and failed — read these before repeating them

* **My own `partition_ok` guard would have fired on every `--offset` run.** The offset branch
  advances `seen` without recording an outcome. Found by *writing the control*, not by review.
* **`--list-walked` appeared to succeed and wrote nothing.** Git Bash rewrote the pod-side
  `/tmp/x.txt`; the script raised `FileNotFoundError` and **my own grep for success markers
  deleted the traceback**. The guard is `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'`, and it is
  in the runbook.
* **Docs corpus drift, 6 failures.** The page sha is the git *blob* sha and the stamp derives from
  the commit, so: commit the page, *then* run `scripts/generate_docs_corpus.py`, *then* commit the
  corpus separately.
* **A packet `to:` line was rejected by the inbox grammar** — `_TO` at
  `src/iagent_pure/lane_packets.py:52` is end-anchored, so doc-tools' `to: <path> :: lane/7f` form
  does not scan. Use `to: ia-01/lane/01` and put routing on its own line. Run `lane_packets.scan`
  against a packet **before** committing it.
* **WITHDRAWN 2026-09-23 — "Lane 1 reported a `rows[0]` defect in my script; it lands on neither
  script" was wrong. It landed on mine.** `scripts/backfill_vector_space.py` at `7ac0765~1` carried
  `def retrievable` at `:161` and `rows[0]["_additional"]["id"] == uuid` as the pass condition at
  `:169` under `limit:1` — Lane 1's file, function name and form were all correct about the copy
  they held. My negative was true only of the copy after my own fix `7ac0765`
  (2026-09-19 17:14:38 -0500); I read my tree and `origin/master` and asserted it of every copy,
  theirs included. A sample stated as a population, pointed across a lane.

## Files changed this session (all committed on lane/74)

* `scripts/backfill_vector_space.py` — blank predicate in-script, partition identity, `--list-walked`.
* `docs/runbooks/backfilling-the-vector-space.md` — Chris's morning procedure, commands in order.
* `docs/runbooks/README.md` — index row.
* `docs/measurements/{predicate,ontologyclass}-walked-2026-09-20-post-roll.txt` — 133 and 26,239 rows.
* `setup/ontologies/docs_corpus.ttl` — regenerated for the runbook page.
* `sessions/` — this handoff, plus packets received from ca / lane-01 / 7f.

**Uncommitted and not mine to commit:** three packets from me in `c:\Users\cnogr\git\ia-01\sessions\`
(consumer-is-live, the-138-uuids-were-not-saved, the-rows0-correction). Lane 1 commits those.
doc-tools holds 5 pre-existing untracked files that are not mine.

## Open questions for the architect

1. Which of `_expert` / `_rr` is falsy at `gateway.py:6005-6006`? `_expert` travels into the
   artifact as `expert_response` at `:6074`, so one of Lane 1's census artifacts settles it in a
   single read. Offered to them; not taken up.
2. The predicate seal on `blankness` is still owed and deliberately unwritten — instrument work was
   held until the walks draw. The `--list-walked` half of that hold was lifted; the seal was not.
3. The 138 Predicate uuids were **not** saved. Said plainly, as ruled. `--list-walked` means the
   next run cannot lose them again.

NEXT TASK: Determine whether Chris has walked safety step 2 as bob since roll sha
`c0005142`, and re-run the `human_task_projection` query for `risk_acceptance%`. Report the row —
or its absence — **with the sha it was measured at**. A real walk that leaves no row is the
finding, and the architect has ruled that I **do not produce a dispatch** for it either way.
