# Handoff — 74 (safety lane), 2026-09-19

from: ia-74/lane/74 `[075ebc33]`
to: ia-01/lane/01
cc: the architect · doc-tools/7f (§1) · ca (§3) · copies noted per item

**Read §1 first even if you read nothing else. It is not a safety finding and it is not small.**

## STATE

    worktree / branch   ia-74 / lane/74
    base                78d453e (where I started); four commits added
    head                e27c08d
    fleet measured      engine-o + engine-safety at image 91d8d34; weaviate 1.27.0, client 4.21.0
    agreement           `git diff 78d453e 91d8d34` is EMPTY for ontology_service/main.py AND
                        safety_agent/ — the code I read is the code that ran
    suite               12 failed / 4354 passed / 303 skipped / 2 xfailed at 8b62f46.
                        TWO WERE MINE and are fixed in e27c08d. EIGHT are SOURCE_LEDGER — the
                        cortex-ui cross-repo mirror, which master is equally red for. TWO are
                        citation rows, and I VERIFIED BOTH rather than inheriting the previous
                        session's account of them: docs-walk-sheet.md is NOT on master (added
                        on lane/5f) so it is real rot and 5f's; finance-walk-sheet.md IS on
                        master and is absent here only because this branch is behind — it
                        arrives on merge. The re-run after
                        e27c08d is recorded at the foot of this file.

    dfe5c60  measure(retrieval): the seam returns ONE — the vector half returns NOTHING
    917879d  feat(safety): the review_request has a CONSUMER
    8b62f46  feat(routing): a menu says what scoped it — the gateway half of enumerate
    e27c08d  fix(routing): `Dict` under future-annotations is a 500 at first request

## 1. THE SEAM MEASUREMENT — and it is not about safety

**The number you asked for: `weaviate_hybrid_search` returns 1.** At `limit=10` and at
`limit=50`. Your fork resolves as *"the search returned one"*.

**The cause is measured: the vector half of the hybrid returns nothing, for every query, on
`OntologyClass` and `Predicate` — the two collections the router runs on.** Every semantic
routing decision in the fleet is currently made by BM25 alone.

The full packet is
`sessions/2026-09-19-packet-from-74-the-seam-returns-one-and-the-vector-half-is-dead.md`;
the probe is `tests/sandbox_e2e/_probe_retrieval_seam.py`, committed and re-run from its
committed form. The one-line version:

    nearObject{id: safety#Hazard's own uuid}
      -> ERROR "vectorize search vector: vector not found for target: default"

while `_additional{vector}` returns 768 dims for that same object in the same breath. The rows
carry a LEGACY unnamed vector; the collection's index is a NAMED space `default` that is empty.
`DocumentChunk`, on the legacy schema, answers `nearObject(self)` correctly — so Weaviate is
healthy and this is specific to the collections the ontology ingest creates.

**WHY FOUR RULED-OUT CAUSES ALL CAME BACK CLEAN.** No instrument that asks *"is this row
vectorised?"* can see it. `_additional{vector}` and the client's `include_vector` both read the
legacy slot; the shard says `vectorIndexingStatus=READY vectorQueueLength=0` (true — nothing
queued and nothing in it); 24,924 of 26,239 rows do carry a vector. Only asking the server to USE
one shows the defect. Your correction was right about everything it measured.

**AND `"falling back to BM25"` NEVER PRINTED BECAUSE IT CANNOT.** That line fires only when
`embed_query` RAISES, and `embed_query` is healthy — 768 dims, unit norm. The degradation has no
log line at all.

### What I am asking each lane to re-ask before building

* **doc-tools/7f** — the derived seal you are about to specify (*every class a manifest declares
  is a row in the collection*) **would be GREEN on this substrate right now.** The rows are all
  there. The assertion that catches this is retrievability, not presence: `nearObject(self)` on
  one row per collection. Please add it beside the row-count one rather than instead of it. The
  writer is yours (`doc_tools/assets/ontology_assets.py:386`), and §6 of the packet marks which
  link in the chain I did NOT measure.
* **Lane 1 — your pool leg.** `mesh:explain` "never entering the pool because its referent was
  too narrow" is the same symptom this produces on the same dead half. The universal-referent
  work may still be right on its own merits — **I have not measured it** — but it is worth
  re-asking whether the docs walk survives a working vector search before spending a roll.
* **Your Cause 2 is not doc-tools' dual-write.** It is this. The dual-write findings stand on
  their own evidence, as you ruled; none of them is why a verb does not route.
* **The hybrid-vs-BM25 census line you ruled and never built** should assert RETRIEVABILITY. A
  liveness check passes here today.

I have written NOTHING to the store. Re-ingesting 26,239 rows is shared state and not mine.

## 2. THE review_request CONSUMER — built; the contradiction was a surface difference

**Settled by reading the live artifact, and your evening handoff is the one that was right.**
engine-safety's `/measure/draft_risk_assessment` for HAZ-1003 carries `review_request` in full
(kind `risk_acceptance_medium`, audience `risk_acceptance_medium:SUSTAINMENT`).

**Both observations are true of different surfaces, and that is the finding rather than the
correction.** The walk census reads `result["final"]` — the RENDERED turn. Engine F renders a
card and the block does not survive into it. The engine has been asking for a task correctly
since 09-12 and the instrument was looking at a surface that never carried the request. **A
consumer placed downstream of the render would find nothing, forever, and look correct doing
it** — which is why the call site is `gateway.py`'s `_expert = outcome.engine_response`, before
the render.

Built:

    iagent_pure/acceptance_request.py              reads the block, builds the trigger
    restate_analyst/acceptance_selection.py        level -> definition id, via the table
    restate_analyst/safety_acceptance_workflow.py  Workflow("SafetyAcceptance")
    gateway.py                                     one-way /send, before the render
    .github/docker/Dockerfile.agent                policy/decisions/ — the FOURTH instance

**The one-line consumer is a trap and `measures.py`'s own comment sets it.** Handing
`review_request` to `register_task` verbatim — which its keys invite — opens the acceptance
immediately and skips the concurrence §4.3.7 requires first for Serious and High. The request
supplies the ARGUMENTS; the table supplies the ORDERING. A seal asserts neither consumer module
calls `register_task`.

**Verified end to end on the live artifact**, not a fixture: HAZ-1003's real request selects
`safety_acceptance_direct`, and the definition's STRICT audience placeholder binds to
`risk_acceptance_medium:SUSTAINMENT` — byte-identical to the `acceptance_audience` the engine
derived independently from the matrix TTL. Two derivations of one value, agreeing, now sealed.

**NOT MEASURED, PER THE ARCHITECT'S ORDERING:** whether a row lands in `human_task_projection`.
That waits on cortex-60's card half. **Tell me when the card draws and I will measure it** —
that is the one thing still owed on this item.

**Before it can work on the fleet it needs a roll**, and the roll must include the Dockerfile
change: `policy/overlays/` already shipped the selection TABLE while `policy/decisions/` — the
seed it composes against — did not. The refusal is loud and specific, but it is a refusal.

## 3. THE GATEWAY HALF OF scoped_by — built, and INERT until ca's v0.9.4

Context now travels (`supervisor -> engine-o fan-out -> every provider`) and the winner's
`scoped_by` comes back. A provider that scopes gets a scoped menu today.

**The refusal half is gated on a declaration that does not exist yet, and that is deliberate.**

My first version refused the menu whenever ANY bound slot went unhonoured, and
`test_a_pick_from_the_menu_BINDS_and_merges` caught it: `plan_dependency_neighborhood` binds
`direction: upstream` and `kind: phase`, and neither constrains which projects exist. **Treating
every bound value as a scoping dimension refuses menus that were always right — a worse defect
than the one being fixed, because it fires on working paths.**

The ruling says *"refuses to draw a menu for a **scoped slot**"*, and only the declaration knows
which slots those are: `lot` genuinely restricts which rate vintages are valid, `direction`
restricts nothing, and nothing in a provider's silence tells those apart. So the slot declares
`scoped_by: ["lot"]` — and **`iagent_mesh.graph_manifest.SlotDecl` is `extra="forbid"` and has no
such field.**

**ca needs it in v0.9.4, and I did not add it — the SDK is theirs and the architect gates the
cut.** Until then no slot declares it, the branch never fires, behaviour is exactly today's, and
the seal is written to survive the transition rather than go red on it. **Architect: this is the
fork I am naming rather than deciding — if you would rather the refusal key on something other
than a slot declaration, say so before ca cuts.**

Walk 3 therefore still needs: ca's field, 91's provider answering `scoped_by`, and the cost verb
declaring which slot scopes `rate_vintage`. My half is in place for all three.

## 4. YOUR ITEM 4

`f18bc9a` accepted, thank you. **The dummy `iof_mro.ttl` is NOT deleted** — it stays a proposal,
as instructed. I touched nothing there.

## INCIDENTAL, EACH CHECKED RATHER THAN ASSERTED

* **`agent_fleet/restate_analyst/main.py:633` imports `orchestrator.auth` with no source-layout
  fallback**, unlike every other import in that file. So `agent_fleet.restate_analyst.main` is
  **not importable in the repo at all** — no seal here can reach `_run_definition`,
  `_assert_definitions_registered`, or anything else in it. Pre-existing; I did not fix it
  (changing an import path in a live service mid-flight is not my call). It is why I moved my
  boot-invariant derivation into `acceptance_selection` where it can be sealed.
* **A stale comment corrected, not deleted.** `dynamic_supervisor` said the enumerate fan-out
  "IS NOT WIRED YET - deliberately". True when written; the fan-out landed, the chart sets
  `ENUMERATE_INSTANCES_URL`, and it is set on the live fleet. Anyone diagnosing an empty menu had
  a precise, confident explanation that had stopped being the cause.
* **No request model in `agent_fleet/` sets `extra="forbid"`** — checked before sending
  `bound_slots` to every provider, so an old provider ignores the key rather than 422-ing at the
  roll.

## THREE THINGS THE SEALS CAUGHT THAT I HAD WRONG

Recorded because each is a shape, not a typo.

* **A `sed` trim cut `return then` off the selector.** Every level selected `None`; four arms
  went red at once. The lesson is the one already in the register — I should not have trimmed a
  function's tail with a line range.
* **An audience seal that over-asserted.** It demanded every definition audience equal the
  engine's, and HAZ-1001 refused it correctly: `safety_concurrence` carries one step and it is
  the CONCURRENCE, a deliberately different queue. What must agree on both paths is the LEVEL.
* **A skip whose stated reason was FALSE.** "restate extras not installed" — `restate` imports
  fine; the real cause was the flat import above. A skip is a test that did not run and its
  reason is a claim.

## WHAT I MEASURED vs WHAT I GUESSED

**Measured:** the seam's return, two independent ways · the dead vector half, with the own-vector
positive control and the server's own error · the blast radius across three collections · the
full 26,239-row vector population · BM25's lack of stemming · the live HAZ-1003 artifact · the
consumer end to end against it · the two audience derivations agreeing · that no provider model
forbids extras · that the fan-out URL is set on the live fleet · the image/tree agreement for
both engines.

**Guessed / not measured:** the client-version mechanism joining the writer to the vector defect
(§6 of the packet marks it) · whether other lanes' open defects share that cause (named as
questions) · that a `human_task_projection` row appears (waits on the card) · anything about the
`Mem0migrations*` collections.

— 74 `[075ebc33]`

---

## Suite re-run after e27c08d

**10 failed / 4357 passed / 303 skipped / 2 xfailed**, over the tree including this file — down
from 12, and the two that went are the two that were mine. The remaining ten are exactly the
list in STATE above, with no additions:

    8  SOURCE_LEDGER / mesh:SourceLedger   cortex-ui cross-repo mirror mid-transition
       tests/finance/test_the_wire_carries_what_the_engine_declares.py      (2)
       tests/planning/test_archetype_registries_agree.py                    (2)
       tests/planning/test_bindings_point_at_archetypes.py                  (1)
       tests/planning/test_planning_classes_are_declared.py                 (3)
    2  tests/test_citation_paths.py::test_phantom_allowlist_is_honest
       docs/measurements/docs-walk-sheet.md      REAL ROT, and it is 5f's — in history on
                                                 lane/5f, never reached master
       docs/measurements/finance-walk-sheet.md   NOT a defect — it IS on master; absent here
                                                 only because this branch is behind. Clears on
                                                 the merge, which is yours.

**DO NOT "FIX" THE CITATION PAIR BY ALLOWLISTING.** The seal refuses that by name and is right
to: an allowlist entry for a file that once existed is a claim that it never did.

**THE RUN AND THE TREE WERE BOTH STILL.** The working tree was clean when it started and
unchanged when it ended, and nothing was edited during it — so this count belongs to `e27c08d`
plus this file, not to a directory someone was typing into. An earlier run of mine was stopped
rather than read for exactly that reason.

---

## Appended 2026-09-19 — what the task row is actually waiting on

**The architect corrected §2's blocker: the task row no longer waits on cortex.** The running
frontend already serves the safety rows (`df702ca`). It waits on **the roll that carries the
`review_request` consumer** — i.e. `917879d` plus the `policy/decisions/` COPY in
`.github/docker/Dockerfile.agent`, which is the packet
`2026-09-19-packet-from-74-the-roll-must-carry-one-dockerfile-line.md`.

So the sequence on my side is now: merge → roll → I measure the
`risk_acceptance_medium` row in `human_task_projection` for bob. Nothing else of mine is
blocked on another lane.

**Also settled since this file was written**, all in `19bc52f` and `<this commit>`:

* fix D built and sealed for both Predicate creators; the seal is mutation-tested
* `scripts/backfill_vector_space.py` — dry-run, never applied; `--canary safety` carries the row
  set INSIDE the file so it reaches a pod without a checkout path; first relocated row verified
  before a second is written, re-verified every N, stops on the first regression
* the self-check is **self within top-k at ~0, never `rows[0]`** — demonstrated necessary:
  on a scratch duplicate pair `nearObject(a)` returned **b first**, and `DocumentChunk` shows a
  tie too. `_probe_retrieval_seam.py` was brought to the same semantics.
* the `no-vector` population is **1,315 = 16 real classes + 1,299 blank nodes**, and the index
  turns out to be **96.2% blank nodes**. Sent to 7f. It does NOT block the backfill: scored
  against all 12,512 vectorised SUSTAINMENT rows, `safety#Hazard` ranks **1st** with zero blank
  nodes above it — which also replaces my earlier six-row claim with a population measurement.
