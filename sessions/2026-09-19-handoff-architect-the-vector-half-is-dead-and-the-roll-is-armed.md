# Handoff — the architect seat, 2026-09-19 (evening): the vector half is dead, and the roll is armed

to: the architect seat (lane-less by R-019 — the inbox seal has no word for this; known, held)
read-by:
supersedes: `sessions/2026-09-19-architect-handoff.md` — read that first for the role, the
grants and the register; where they differ, this wins.
placed by: Chris. The architect writes to no repo; this was written in chat.

**Nobody has walked a screen yet. Seven hours of rulings and zero walks. The first act of the
next architect is to get Chris in front of lot 4 BEFORE the roll.**

---

## 1. THE EXACT NEXT STEP

1. **Chris walks lot 4 now, against the fleet as it runs (`91d8d34`).** alice / `COST_ANALYST` /
   `PRODUCTION_COST`, from the desktop UI: *"how concentrated is purchasing on lot 4"*. Expect
   `CONTRIBUTION_RANKING`, four rows, shares summing to 1.0000, bound `0.25` marked default
   (`docs/measurements/cost-card-walk-sheet.md`). It is the only before-picture of the roll.
   Then the NP-MERIDIAN brief (plain card is expected) and the finance board. None of the three
   waits on anything.
2. **Read the five lane handoffs before writing any order** (paths in §2). Each has its own §1.
   Do not re-derive their next steps; rule only where they say "open — architect".
3. **The roll** is Lane 1's, armed and not fired. It fires when: the four image probes pass at
   `c0005142…` (with a bogus-sha negative control), the EXACT command re-run with `--dry-run`
   shows the frontend on `@sha256:c8d6553f…` on a FULL-MANIFEST diff, and Chris says go.
4. **The backfill** is Chris's, in daylight, and is NOT next. Its chain is in §4.

---

## 2. STATE — as the lanes' handoffs report it (none of these shas verified by me)

| lane | pair | head | handoff |
|---|---|---|---|
| Lane 1 | `ia-01/lane/01` | `4731705`; master = roll sha `c0005142a610…`, chart `0.4.6` (deployed `0.4.4`, rev 146) | `ia-01/sessions/2026-09-19-handoff-lane-1-the-roll-is-armed-and-not-fired.md` |
| safety / worker | `ia-74/lane/74` | `788bf89`, 2 ahead / 54 behind master — REBASE, do not merge | `ia-74/sessions/2026-09-19-handoff-74-the-vector-space-the-consumer-and-the-blank-node-question.md` |
| SDK | `iagent-mesh-sdk`, `lane/ca` | `711c6d0`, v0.9.4 draft, 2 ahead of master, NO tag | `iagent-mesh-sdk/sessions/2026-09-19-handoff-sdk-ca-the-v0-9-4-draft-is-on-a-branch-and-uncut.md` |
| doc-tools | `doc-tools`, `lane/7f` | `0688628`, PR #1 green, UNMERGED | `doc-tools/sessions/2026-09-19-handoff-7f-end-of-context-the-blank-node-question-is-next.md` |
| cortex | `cortex-ui`, master (R-009) | `b3f2782` | `cortex-ui/sessions/2026-09-19-handoff-cortex-60-the-roll-gate-cleared-and-the-vocabulary-three-homes.md` |

Not opened tonight and still holding work: `ia-32`, `ia-5f`, `ia-91`, `ia-eo` (all merged by
Lane 1's pass, per Lane 1).

**ROUTING HAZARDS, live:**
* `doc-tools-7f [f76842]` is a DIFFERENT live session from the one that did tonight's 7f work
  (`doc-tools-f6 [5e05c6]`). "7f" is the lane, not a session. Route by worktree/branch pair.
* `cortex-ui` is shared with a lane called **ba**, which is not in the lane map. R-009's premise
  ("cortex-ui has one lane") is false. ba's push released two of cortex-60's held commits today.
* Lane-less seats have committed on the shared master checkout (`72f1111`). That checkout was
  meant to be read-only.
* cortex-60 wrote "22" and "f3" for what the lane map calls 32 and 5f.

---

## 3. WHAT I VERIFIED MYSELF vs WHAT I TOOK ON A LANE'S WORD

**Read from disk by me (the architect can read, not run):**
* `iof_mro.ttl` is a self-described dummy; `Maintenance.rdf` declares only
  `iof-constr:MaintenanceWorkOrderRecord`; `IOF_MRO` is in the prime manifest (`prime_databases.py:181`).
* The Jena→Neo4j sync (`doc-tools/doc_tools/assets/ontology_assets.py`) selected only
  `?uri ?label ?definition` and SET six properties; the "Mechanics" comment described an n10s
  route the docstring said was abandoned. (Read BEFORE 7f's fix; 7f's commits change it.)
* The doc-tools OntologyClass writer created the collection bare and wrote `vector=` positionally.
* `Neo4jGraph` on `lane/eo` vs `MeshGraph`: nine of nine, signatures textually identical —
  compared against the SDK repo's WORKING TREE, not the wheel; ca's wheel diff covers the gap.
* doc-tools `pyproject.toml` has no extras; `uv.lock` pins `iagent-mesh v0.9.1 @ 557976d`.
* `build-container.yml`: bare `uv sync` in the tests job under the comment 7f quoted (pre-fix).
* `scripts/backfill_vector_space.py` at `19bc52f` — read in full; my four findings were fixed at
  `f67c209` per 74. **I did not re-read the fixed version.**
* R-007, R-009, R-058.1 in `docs/rulings/README.md`; the register ends at **R-080** (no R-081).
* ADR-0055 exists only in `ia-5f`, not on master (as of this morning).

**Taken on a lane's word — every one of these is a claim until re-measured:**
everything about the live cluster and stores (the dead vector half, 96.2% blank nodes, 16+1,299
vectorless, the running pod on `df702ca`/`70a0eead`, deployed tags, GHCR contents), every suite
count, every sha, every merge, the census numbers, the helm dry-run results, PR #1's CI result.

---

## 4. RULED vs OPEN

**Ruled tonight (all 2026-09-19, by this seat; none has a register number — R-021 says Lane 1
numbers them, and the register work is held):**
* Walk order: lot 4 first. (The cost sheet's "runs last" line from 09-11 is stale.)
* Cause 1 (add an `iof_mro.ttl` manifest row + parity seal) WITHDRAWN.
* The `universalReferent` flag travels through the doc-tools sync, not a second read path.
* **Vector fix shape D**: declare the named space at create, write by name. Seal is
  `nearObject(self)`, self within top-k at ~0 — never `obj.vector["default"]`, never `rows[0]`.
* Backfill conditions: Chris only, daylight; lexical census baseline saved first (done:
  `docs/measurements/walk-census-run-2026-09-19-lexical-baseline.txt`, `76b9733`, 8 pass / 12
  fail — EVERY pass is a lexical pass); canary = six `safety#` rows, then *"what hazards are
  unattended"*, then the rest in one sitting; never during a roll, no roll during a backfill.
  **After success every repaired row READS AS VECTORLESS on today's instruments. Do not revert.**
* The frontend rolls BY DIGEST (`sha256:c8d6553f…`, built at cortex-ui `8a13dd6`), in a declared
  values file, never a bare `--set` (R-034). Lane 1's overlay is on master.
* The pool leg is ON HOLD until the `mesh:explain` cosine number exists. **Lane 1 never ran it**;
  the probe is a scratchpad draft (path in Lane 1's handoff §4).
* `narrowed_by` (slot, obligation) paired with `scoped_by` (response, claim); invariant
  `scoped_by ⊆ narrowed_by ∩ bound`. v0.9.4 is NOT cut on its own; order is cut → pin → declare.
* Reassigned from Lane 1 to `ia-74/lane/74`: the `review_request` consumer, the gateway half of
  the scoped menu. Both built and merged per 74/Lane 1.
* doc-tools CI: `--locked` on both `uv sync` and `uv export`.
* cortex pin bump: after the roll, to the rolled sha, ONE commit with the third check rewritten
  to read producer sha AND SDK pin, plus the `SourceLedger.contract.ts:56` comment.
* 72f1111 amended with a true `Lane: invincible-agent/master` trailer, not exempted.
* Held until four walks draw: lane-less addressee vocabulary; where seats may write in the shared
  tree; the three sibling `:latest` images (`dag-tools/central-gateway`,
  `dag-tools/user-deployment`, `pub-tools`); whether retag-by-digest ever published `0.4.4`;
  sessions-only pushes triggering cortex image builds; pinned-artifact seals in doc-tools.

**Open — the architect's:**
1. **SHOULD BLANK NODES BE RELOCATED, OR BE IN THE INDEX AT ALL?** Not ruled. It scopes the
   backfill. 7f's successor has the first read (does the WEAVIATE leg's extraction query carry
   the `!isBlank` filter the Neo4j leg has?); 74's successor has the cheap discriminator (score
   the census's other 16 questions, count blank nodes in each top-10). Rule after both.
2. **The backfill chain is longer than I ordered.** doc-tools' chart pins an exact sha
   (`values-sandbox.yaml:34`, `d3ca169`); there is no `:latest`. So "7f's writer is running"
   means: Chris merges PR #1 → image builds → the tag is RE-PINNED → doc-tools rolls. Until then
   a re-ingest writes the dead slot again.
3. **`IOF_Core` twice in the manifest COLLIDES.** Same uri in two domains, and the Weaviate uuid
   is `generate_uuid5(uri)` — one row overwrites the other. My "looks deliberate, leave it" was
   wrong (§5). No reshape until the walks draw, but it is a defect, not a design.
4. **No re-embed path exists** in doc-tools; "backfill" is promised 4× across 3 writers, and the
   promise covers `DocumentChunk` and `semantic_assets` too. 16 real classes are vectorless.
   Commission it after the walks.
5. **ca's open rulings:** `limit` (a truncated list wearing a complete menu — same defect class
   as the scoped menu; ca and 74 are told NOT to invent it); four names exported by two SDK
   modules each, blocking root promotion; SDK master's `uv.lock` is stale.
6. **Three homes for the ledger vocabulary** (cortex-ui, producer, SDK ≥ 0.9.3). `PRODUCER_REF`
   no longer determines it.
7. **R-009 needs re-ruling** — its premise is false (ba).
8. **R-007 (§9.2)** — still held until the finance board is walked.
9. Register debt: duplicate R-055; tonight's rulings unnumbered; ADR-0055 not on master.

---

## 5. WHAT I GOT WRONG, AND WHAT CAUGHT IT

1. **A bare `uv sync` in a work order** — the declared form was in a dispatch I had read the same
   hour. Cost Lane 1 a run (twelve collection errors). Caught by Lane 1 citing AGENTS.md:334.
2. **"`IOF_Core` looks deliberate."** I read distinct names and s3 keys and stopped. Lane 1 read
   the uuid derivation. I checked the manifest, not what the manifest feeds.
3. **"Merging doc-tools main moves `:latest`."** I wrote it into a handoff order as a fact to
   record. 7f read the chart instead of recording it: no `:latest`, a pinned sha.
4. **"`mesh:Thing` is on master."** It was on two lane branches when I told 7f so. Caught by 7f's
   `merge-base --is-ancestor`, because the precondition check was ordered before the build.
5. **"Walk 4 waits on the cortex roll"** — inherited from the morning handoff and repeated for
   hours. The pod already served the rows; cortex read `/version.json`.
6. **"~1,315 vectorless rows need re-embedding."** Arithmetic on two of 74's numbers. It was 16
   real classes and 1,299 blank nodes.
7. **I told 7f its own in-flight work might be orphaned** only by inference from timestamps; it
   was right, but Lane 1 had already warned 7f off its own file on the same missing fact.

The pattern is 7f's, and it is mine too: **a premise stated as settled, load-bearing, never
re-measured.** This seat reads and does not run, so every number it repeats is second-hand. Say
which.

---

## 6. STANDING

* You read every worktree and write to none. Rulings go to a lane as text Chris places; a lane
  refuses a relay, correctly.
* Verify a lane's claim in the tree before ruling — and say when you could not.
* Every environment command in an order is the repo's DECLARED form
  (`uv sync --locked --extra agent-fleet` here; `uv sync --locked` in doc-tools;
  `uv run --extra dev python -m pytest -q` in the SDK).
* Nothing touches a shared store without Chris. No instrument work until four walks draw. Rule
  only to unblock a screen.
* Chris is the scheduler. He is tired of rulings and has not yet seen a card. Lot 4 is first.
