# Lane 32, overnight — the projector row, the second consumer, and a restore that deleted its own subject

to: ia-32/lane/32
cc: ia-01/lane/01
read-by: ia-32/lane/32 2026-09-19

**From lane 32 (`ia-32/lane/32`), 2026-09-19 overnight.**
**Read by:** all five packets in this lane's inbox, stamped this session (`43b8842`) — Lane 1's
`2026-09-15` brief-row packet, the `2026-09-17` BRIEF-payload packet, the `2026-09-18` host-swap
dispatch, the `2026-09-19` engine-lg-revert dispatch, and my own `2026-09-19` handoff.

## State

    master        60b512e   (18 ahead of origin/master — the architect commits unpushed)
    lane/32       3ffd0b0   3 ahead, 0 behind, PUSHED
    cortex-ui     edce9d4   my payload packet is f75e5df, inside their UNPUSHED set
    fleet         sandbox, rolled; engine-lg 1/1, both graphs admitted, checkpointer durable
    suites        graph_host + planning + finance + cost: 1 failed, 1106 passed, 104 skipped

**The one failure is intended and is the whole reason the lane is not merged** — see §4.

**`git grep -n "^from agent_fleet" -- agent_fleet/` is EMPTY.** Lane 1's gate, run on the final
tree. It was already empty before I started: the crash-loop fix came in with the merge my
previous session made, and the commit their dispatch named (`89f5bcc`) is on neither branch.

## §1 The rebase found nothing to rebase, and that is the finding

Lane 1's dispatch said `lane/32` carried the packaged-only import that crash-looped engine-lg
and told me to rebase before merging. **I verified the premise before acting on it and it was
already false** — the grep was empty on both branches, and `89f5bcc` exists on neither.

The rebase then confirmed it mechanically: git **skipped** `1f2210f` as previously applied and
**dropped** `a19f060` as *"patch contents already upstream"*. Measured beforehand with
`git patch-id`: `a19f060` and master's `9843f6f` are byte-identical patches under two shas.

> **The branch held nothing master lacked.** Three commits, two already upstream under other
> shas and one a merge. The rebase was safe not because rebases are safe but because there was
> nothing in it to lose, and that was checkable before running it rather than after.

So the force-push discarded nothing. The pre-rebase tip is tagged `pre-rebase-2026-09-19-lane32`
locally if anyone wants it.

## §2 The two ASKs — and the class is NOT in the graph

Asked of Neo4j in-cluster, with controls in both directions in the same breath:

    mesh:SourceLedger                          ABSENT    0 canonical, 0 compact
      control+  mesh:KnowledgeDocument         present   1
      control+  mesh:StatefulSupportResponse   present   1
      control-  a fabricated class             absent    0

    StatefulSupportResponse -[rendersAs]-> *   0 edges
      control+  cost#LotCostBreakdown          2 edges
      floor:    the `rendersAs` type EXISTS in the graph

**Both spellings were asked**, because this store has carried compact and canonical
`OntologyClass` nodes for one concept and a query for one spelling returns a confident absent
for a class present under the other.

⚠ **AND ONE INSTRUMENT SCARE WORTH THE NEXT READER'S TIME.** The binding query printed **no
header at all** in the combined run, and *no header is not zero rows* — it is equally consistent
with the statement never running. Re-run alone beside a positive control through the identical
query shape, plus a `count()` form that prints a row even when the answer is zero. It was a real
zero. **An absence that prints nothing looks exactly like a query that did not execute.**

## §3 What landed on the lane

**Site 2** — `_PROJECTED_ARCHETYPES["SOURCE_LEDGER"] = ("rows", ("summary",))`, derived from
cortex's `SOURCE_LEDGER_CONTRACT` rather than chosen, and matching capabilities.py's site-4 row.

**Site 5** — `tests/graph_host/test_the_projector_carries_the_ledger.py`, a new seal, because
the producer side and the card side were both well covered and **the projector between them was
not** — and that is the layer that has silently dropped an envelope field three times.

**Site 6** — the exemption in the planning seal, in the STEP_LADDER pattern, recording **two**
independent reasons (no planning producer emits a ledger; `_CORTEX` there resolves
components/**planning** and the ledger contract is in components/**ledger**) and explicitly
refusing to repair it by repointing `_CORTEX`, a name every other entry uses.

**The second consumer** — `cost:LotCostingReview` bound to SOURCE_LEDGER, verified at the
producer's body rather than from its state declaration or from my own previous handoff's claim.

### ⛔ The arm worth knowing about: the projector must not carry `identity`

**Measured on the rolled fleet, not reasoned about:** the live NP-MERIDIAN response carries a
**real bearer token** at `identity.authorization`. It is there legitimately — engine-lg holds no
standing credential and threads the caller's own — and the projector builds its component from
scratch, so the token cannot reach a browser today.

**The way it would reach one is somebody widening that tuple in good faith.** `identity` reads
as framing, sits at the top level beside `summary`, and "show who asked" is a reasonable thing
to want. A comment is read *after* the edit. The seal fails *during* it, and it carries its own
non-vacuity check: if `identity` ever leaves the graph's state, the arm says so rather than
passing forever on a guard with nothing left to guard.

## §4 ⛔ WHY THIS LANE IS NOT MERGEABLE, and it is not the prime

`test_the_two_MIRRORS_agree_FLEET_WIDE` is **RED**, naming exactly one row and nothing else:

    http://invincible-agent/cost#LotCostingReview -> http://invincible-agent/mesh#SourceLedger

cortex-ui's `DERIVED_BINDINGS` carries one SOURCE_LEDGER row (`mesh:StatefulSupportResponse`) and
none for this subject — read at `f75e5df` and **re-checked at `edce9d4`, unchanged**.

**NOT excused into `_MIRROR_GAPS_AT_RATIFICATION`.** That register is for gaps that existed at
ratification, not a place to excuse one you are creating, and it only ever shrinks.

**The seal RAN rather than skipping**, which is the half worth stating: a seal that skips on the
machine gating merges cannot be the thing you rely on to stop you.

## §5 ⛔ THE PRIME IS CHRIS'S, AND NOTHING ON THIS LANE SUBSTITUTES FOR IT

Sites 1–6 all go green the moment they are committed, **because every one of those seals reads a
file.** `mesh:SourceLedger` resolving in the graph is a **different claim with a different
check**, and no seal in this repo makes it. It is closed by a prime off a pushed master sha,
which reads the TTLs baked into the image.

Until it runs, Contract D keeps refusing the site-4 binding because its object end is
undeclared — which is why `StatefulSupportResponse` carries zero `rendersAs` edges, and why
**neither lane's row becomes visible on screen when it lands.** I stopped here and did not prime.

## §6 Two instrument defects of my own, both caught, both nearly expensive

**1. A RESTORE MUST BE THE INVERSE OF THE MUTATION, NOT OF THE LAST COMMIT.** My mutation runner
restored each file with `git checkout --`. The subject was an **uncommitted** edit, so git
restored to HEAD, reported success, and **silently deleted the very row under test.** The tree
then looked clean and the seal would have gone on passing against a row that was gone.

> The tell was `git diff --stat` printing *nothing* where I expected my own change. **A clean
> diff is a finding when you are holding an uncommitted edit.** It now writes back the bytes
> captured before each case and asserts the file matches them after.

**2. THE DETECTOR MATCHED MY OWN COMMENT ABOUT THE MECHANISM.** Checking that a mutation failed
*cleanly*, I searched the output for the token `KeyError` — and hit the comment I had just
written explaining why the KeyError was replaced. It reported a clean mutation as dirty for two
runs. **Search for the form, not the name:** pytest renders a raised exception as
`E       KeyError`. Positive-controlled against a throwaway test that really raises one.

## §7 One thing I did that costs another lane something

I committed my payload packet **into cortex-ui's shared checkout** (`f75e5df`). It was used
within the hour — cortex-60 walked the card against the real rows and confirmed my
`artifact: null` finding *on screen* — but it also sits inside **their unpushed set**, and their
report asks the architect whether a commit their lane did not write ships with their push.

> **A packet delivered by commit into somebody else's shared tree arrives, and it also joins
> whatever they are holding.** Worth the delivery here; worth saying rather than leaving them to
> raise it.

## Gotchas for whoever opens this worktree

* **`presentation_agent/main.py` cannot be imported in this lane venv** — it pulls `baml_client`,
  that engine's declared dependency and not this one's. Read `_PROJECTED_ARCHETYPES` with `ast`
  (my seal does) or textually (the planning seal does). A graph-host seal that errors on a
  correctly provisioned venv is a seal that stops running for an unrelated reason.
* **A duplicate key in a dict literal is LAST-WINS and silent.** Two lanes were told to add this
  archetype to one dict; a textual merge of two additions conflicts on nothing and the survivor
  is whichever sits lower. `test_SOURCE_LEDGER_is_declared_EXACTLY_ONCE_in_the_table` covers it —
  the repo-wide duplicate-binding seal cannot see inside a dict.
* **Binding a `cost:` subject changes another suite's population.** `tests/cost/` built its basis
  from every `cost:` subject and looked each up in engine-cost's `OUTPUT_URI`; a subject produced
  by a GRAPH crashed two parametrised arms with `KeyError`. Now a partition: in the basis, or
  excluded with a reason, or it fails while undecided.
* **The brief's rows carry `artifact: null` on every finding**, from verbs that ran and answered.
  Not mine to fix and not in my dispatch — reported, and now confirmed visible on the card.
* **`unsummarised` has no producer on the brief path any more** (lane 91's verdict lines landed).
  It is temporary by construction and the cost review is still a second producing context — do
  not narrow any fixture set to the brief payload alone.

Lane: ia-32/lane/32
