# Handoff — Lane 1, 2026-09-21: four lanes merged, and roll #2 no longer carries all code

to: ia-01/lane/01
from: ia-01/lane/01 · cc ia-74/lane/74 (the worker) and the architect
read-by:
**M** = measured, **I** = inferred. Every M is at the sha named beside it.

## Current state
    worktree / branch   c:/Users/cnogr/git/ia-01 · lane/01                            M
    lane/01 HEAD        this commit — 2 ahead of master, 0 behind                     M
    master              816bbee == origin/master, 0/0, pushed                         M
    working tree        CLEAN in ia-01, and in the master tree                        M

**Merged tonight, standard gate, docs read by content:** lane/91 `9ebb5ce` (docs only — six
`read-by` stamps plus two new files; the diff holds no other changed line, M), lane/32 `f3d3148`
and lane/eo `b0f66fb` (docs only, M), and lane/74 `c171875`, which **was not**: an additive
`--list-walked` in `scripts/backfill_vector_space.py` (+48; writes uuid/outcome/uri sorted so two
runs diff — the fix for the defect where I measured a collection twice and could not name the five
rows that went) plus one regenerated corpus row in `setup/ontologies/docs_corpus.ttl` (M). **74
also DELETED a 389-line handoff, their own**, whose title carried a premise later refuted — within
their gate, but this tree strikes a superseded record rather than removing it. Recoverable (M) at
`70541a0:sessions/2026-09-19-handoff-74-the-backfill-is-scoped-and-the-consumer-is-not-live.md`.

## Decisions and rulings received
* **Any census claim needs three fires.** The standing Predicate census is **one fire plus one
  control re-run** — it predates the ruling and does **not** meet it.
* **The 18083 port-default hold is LIFTED** (`walk_census.py:54` defaulting to the stub's port).
* **Tonight's two projector edits are HAND EDITS to the table ADR-0055 §3 replaces.** When §3
  lands, `threshold`/`threshold_defaulted` and lane/32's `SOURCE_LEDGER` row move with it; they are
  not independent declarations.
* **IOF_Core is HELD with its mechanism recorded**: a second manifest entry re-writes the same
  uuids by batch replace; 12 of 13 BFO/IOF Core rows vectorless. Build nothing.
* **Lanes 91, 32 and eo are closed**; `ia-74`/`lane/74` owns what all four owned. Roster updated at
  `6739988`, rows **struck not deleted** so their citations resolve. `lane/eo` never had a roster
  row at all, and its branch tracked `origin/master` until tonight (M, fixed). A packet's author
  **places** the file and does not **commit** it in another lane's checkout.

## Roll #2 — armed at `8952b11`, NOT fired, and the arming is now STALE
**It no longer carries all code** (M at `816bbee`). Four non-docs files differ from `8952b11`:
`.claude/settings.json`, `.mcp.json`, `scripts/backfill_vector_space.py`,
`setup/ontologies/docs_corpus.ttl`. The last two **reach an image**: `Dockerfile.agent` copies only
`safety_risk_matrix.ttl` and `build_cost_package.py` by name (M), but `Dockerfile.dagster` does
`COPY . /app` (M) and the live dagster pods are pinned to the roll sha `c0005142…` (M, cluster).

**RE-ARM, DO NOT EDIT.** Re-run the whole gate at the new head: 17 images with arm64 at that sha,
bogus-sha negative control absent on all seventeen, CI green, `--dry-run`, then a FULL-MANIFEST
diff (never an image-line diff) with sibling digests re-read by `docker buildx imagetools inspect`.
The command in `sessions/2026-09-20-morning-report-…-roll-2-is-armed.md` §2 is **superseded**, and
it still needs cortex's frontend digest, which has not arrived.

## The census and the attribution
At settle after roll #1 (revision 147, `c0005142…`), `Predicate` (M,
`docs/measurements/predicate-retrievability-census-2026-09-19-post-roll.txt`):

    total 133   retrievable 89   named=89  legacy=44  no-vector=0   partition sums to 133 of 133

The 44 legacy are **43 `mesh:rendersAs` cortex bindings + 1 verb** (M), not the 3+41 predicted. The
43 **cannot cost a route** (I): their only consumer is a plain `Get(limit:500)` with no vector (M,
`graph_menu_source.py:189`). Verb routing does **not** filter `tool_kind` at the retrieval query
(M, `mesh_vectors.py` `_domain_filter`). Walk census: 8 pass / 12 fail — **identical totals to the
lexical baseline, but two rows moved in opposite directions and cancelled**
(`finance-performance-indices` FAIL→PASS, `finance-variance-drivers` PASS→FAIL) (M).

**THE `mesh:explain` CORRECTION — I published a wrong cause.** I wrote that the docs rows fail
"consistent with mesh:explain being the ONE verb row in the legacy slot". **There are TWO rows**
(M): the live one is **NAMED and reachable**, updated `02:08:10Z`, one second before engine-docs
logged RECOVERED; the legacy one is a stale duplicate (`verb_local` =
`//invincible-agent/mesh#explain`). Corrected in-file at `9fd8112`, wrong sentence left visible.

**The discriminator is eo's bm25-arm experiment, and it has NOT been run on Predicate.** On
`OntologyClass` at `9c7ea4b` (M, theirs): forced bm25 gave identical rows in identical order,
`near_vector` alone gave 0, `nearObject(self)` was REFUSED — against a nonexistent-uuid control
with a distinguishable message. `mode` reports only whether **this reader's** embed call raised, so
confirming my attribution by watching `mode='hybrid'`, which I proposed, could never have worked.

## Three red seals on master — one is now GREEN
| seal | at `816bbee` | owner |
|---|---|---|
| `test_the_two_MIRRORS_agree_FLEET_WIDE` | **GREEN** (M, by name: 1 passed / 15 deselected). Cortex added the `LotCostingReview` binding at cortex-ui `ea060f3`; lane/32 reported it, I re-ran it on master as they asked | closed |
| `test_THE_REPO_INBOX_IS_FULLY_ADDRESSED` | **RED**, now **12** lane-less files, not 9 (M) — the three closing handoffs and the three ca packets I was ordered to commit all name no lane in the vocabulary it parses | the architect (open vocabulary item) |
| `test_EVERY_CITED_ANCHOR_NAMES_A_HEADING_THAT_EXISTS` | **RED**, 1 site left (M), down from 2 | the architecture seat |

Everything else is from **last night's** Windows run (4552 / 4 failed), **not** CI-equivalent.
Tonight: only the seals the merges could touch — 614 passed / 0 failed, plus 54 on the five that
read `AGENTS.md`. **Nobody has run the full suite at `816bbee`.**

## Tried and failed
* **I committed the wrong three packets first.** Ordered to commit "74's three packets that sit in
  your sessions/", I was standing in the **master tree**, found exactly three untracked files, and
  committed those — **ca's**, addressed to the architect. 74's three were in `ia-01`, my actual
  worktree, headed `to: ia-01/lane/01`. Both sets are committed now with the right attribution, but
  "exactly three untracked" read as a fingerprint and was a coincidence.
* **My report of the anchor defect was a second instance of it.** The seal is a `git grep` over
  tracked files and cannot tell a defect from its description. Fixed at `816bbee`.

## Open questions
1. **Does the legacy/named split move after Chris's first page load?** Standing prediction: legacy
   44 → 1, named 89 → 132, total 133, no-vector 0. Unmeasured.
2. **Does `lane/5f` hold work beyond ADR-0055?** It is `ce264b4`, one unmerged handoff commit (M).
   ADR-0055 itself **is on master** at `73547e8` (M) and already was. Not merged tonight, not ordered.
3. The stub on **18083** is still live and still answers `deadbeef`. It is nobody's row.

## Files I placed uncommitted in another lane's checkout
`ia-74/sessions/2026-09-19-packet-from-lane-01-the-consumer-is-live-confirmed-independently.md` —
**now committed by 74** at `c171875` and merged tonight. Nothing else of mine is in any other
checkout: `ia-74`, `ia-32`, `ia-91`, `ia-eo`, `ia-5f` all report an empty `git status` (M).

## NEXT TASK
**Nothing fires without Chris.** The lot 4 walk record **landed** (M, `f16841f`,
`docs/measurements/cost-card-walk-sheet.md:50`, `## WALKED 2026-09-19`). Waiting on Chris, in
unblocking order: **the first page load** (then re-run the three-bucket probe against the
prediction, naming any row in a non-zero no-vector bucket) · **the walks** · **the go on roll #2**
(re-arm first) · **the doc-tools chain, then the `mesh_system.ttl` prime** · **the backfill**
(`docs/runbooks/backfilling-the-vector-space.md`; the apply is Chris's) · **the stub on 18083**.

First thing Lane 1 can do alone: **fire the Predicate census a third time** for the three-fires
ruling, and **run eo's bm25-arm experiment on Predicate** — read-only, in-pod, never a port-forward.
