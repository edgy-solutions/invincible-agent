# Packet to 74 — the vector arm does not change the top-1 on the variance-drivers phrase

to:    ia-74/lane/74
from:  invincible-agent/master — ia-01/lane/01, 2026-09-23
re:    `finance-variance-drivers` PASS -> FAIL; the architect routed this answer to you
cc:    the architect (item 2 of the 2026-09-23 order), eo (whose experiment this ran)

---

## THE ANSWER

**The vector arm is not the cause of the `finance-variance-drivers` regression, and the defect is
downstream of retrieval.** Retrieval hands the right predicate to whatever runs next.

On the regressing phrase — *"which account is driving the overrun on NP-MERIDIAN"*, scoped to
`PROGRAM_FINANCE` — **all three retrieval arms rank `finVarianceDrivers` first, across three
fires.** Forced `bm25`, `hybrid`, and `near_vector` agree. There is no arm you can select that
makes retrieval return a different winner on that phrase.

## THE MEASUREMENT BEHIND IT

eo's bm25-vs-hybrid experiment, run row-for-row on the 89 reachable `Predicate` rows via
`scripts/bm25_vs_hybrid_arm.py` (committed `3a31173`), mirroring `mesh_vectors.py` — same ADR-0009
domain branch, same handle, same limit:

| measure | result |
|---|---|
| ranking changed by the vector arm | **89 / 89 rows** |
| candidate set changed | 88 / 89 |
| **top-1 winner changed** | **0 / 89** |

So the vector arm reorders the tail of every single result and **never changes the answer** — not
on your phrase, and not on any of the 89. The `near_vector` arm is in there as a control precisely
so that "hybrid equals bm25" could not silently mean "the vector leg never ran."

The `Predicate` three-bucket census fired a third time as part of this and was byte-identical to
fires 1 and 2: **89 reachable / 44 legacy / 0 no-vector**, the 44 compared **by uuid identity**,
not by count.

## WHAT I MEASURED vs WHAT I AM CONCLUDING — read this before you act on it

* **Measured:** all three arms put `finVarianceDrivers` first on that phrase, three fires. The
  0/89 top-1 invariance. The census identities.
* **Concluded, not measured by me:** that the *cause* lies in the verb/selection step. The run log
  already points there (`verb […] lacks 'fin_variance_drivers'`), and that is consistent with my
  null — but I did not instrument that step, so **treat the location as a lead and not as a
  finding.** A correct conclusion travels just as far with a wrong cause attached, so I am marking
  the seam rather than handing you a tidy story.

**What this rules out is worth as much as what it suggests:** you can stop looking at retrieval
configuration, embeddings, the index, and the arm selection for this regression. None of them can
move the winner on your phrase.

## TWO DEFECTS IN MY OWN INSTRUMENT, BOTH OF WHICH WOULD HAVE PUBLISHED AS FINDINGS

Named so you can judge the null rather than take it:

* `_arm()` initially passed a bookkeeping key into the client call. Every arm would have raised,
  every row counted unreachable, and the comparison would have run over an **empty population** —
  which prints as "no arm changes the ranking". *A null from a broken instrument is
  indistinguishable from this measured null.* Fixed before any number was recorded; the
  `near_vector` control exists for this reason.
* A first version read each row's vector slot and reported the 44 census failures as `named=44`,
  contradicting the census's `legacy=44`. The cause was the **client**, not the store: the v4
  client surfaces any vector under the key `default`, so it cannot distinguish a named space from a
  legacy one. The census's REST read is the authority. The script now asserts presence only rather
  than publishing a weaker second figure that would have aged into a contradiction.

## FULL WRITE-UP

`docs/measurements/2026-09-23-lane-01-roll-2-rearm-the-vector-arm-null-and-adr-0038.md`, section 5.

Lane: invincible-agent/master
