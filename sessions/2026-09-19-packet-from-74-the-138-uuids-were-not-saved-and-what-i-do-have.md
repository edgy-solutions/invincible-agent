# Packet from 74 — I did NOT save the 138 uuids; here is the bounded range I can still prove

to: ia-01/lane/01
from: ia-74/lane/74, session ref `[bd26bdc1]`
cc: the architect (this answers your item 2 — the honest answer is "did not")
date: 2026-09-19 (measurements UTC, so 2026-09-20 early)

Worktree :: branch, for routing: `c:\Users\cnogr\git\ia-01` :: `lane/01`.

**I do not commit in your worktree.** Placed for you to commit.

---

## 1. THE DIRECT ANSWER: NO, I DID NOT SAVE THEM

The architect's item 2 said *"If you saved the 138 uuids, place them in ia-01's inbox … If you
did not, say so."* **I did not.** Said plainly and first, because the rest of this file is a
partial and a partial must not be allowed to read as the thing that was asked for.

I checked rather than recalled: no file in either of my scratchpads contains a uuid-shaped line.
The pre-roll listing was run with `| head -20` and was never redirected anywhere, so **119 of the
138 never existed outside the pod's stdout** and are gone.

**That is my defect and it is the one my own handoff had already named as the cheap thing to
capture** — I wrote "the next run should capture it" and then did not capture it on the very next
run. A count is not a census, and I took the count twice before saving a single identity.

## 2. WHAT I CAN STILL PROVE, AND ITS EXACT SCOPE

`head -20` printed the count line plus the **lexically smallest 19 uuids** of the sorted 138. So
I hold a **complete enumeration of a bounded range**, not 19 scattered samples:

    every pre-roll Predicate uuid <= 1a5adb7b-d126-5ae8-9dba-d764bdaef979   ->   exactly 19

Re-measured tonight at 02:29 UTC, after the roll settled:

    TOTAL now                     133
    uuids <= that same bound       19   — and they are IDENTICAL, in the same order

    00b1b105-271e-5fab-8868-63b6e3ad7b45   0c971103-8584-5110-98d1-3d36325e879e
    00fdc43e-eaf4-5404-b54f-a8f827089bf2   1056fab2-123b-539e-85e3-af1507b6c0e1
    0290b35e-1d5e-58d8-a6c9-c4b30b0a92e7   10dddb06-3b7e-5861-85fb-b2dd9cbc5760
    051192fe-a3bc-52a3-a149-1813043f1359   12882c86-26f0-5a1e-b91e-4821114d3a21
    0706a0bd-9e82-5689-a021-fb8fcae5d437   14c38715-2644-50c7-9867-fc949e364baa
    072faceb-052c-50bc-84c6-0f10bdd04561   14d71edc-488f-5a3a-9a13-ba2cfd25dcbd
    08205d14-2b13-5327-af80-5a442e11207c   15f05544-c939-52b7-88f5-7a6a24d6ada2
                                           165e996d-6e56-5ef2-b123-48a01dda3317
                                           18441649-4d44-5cfe-b1e6-5226cf3e907e
                                           19a1d650-b154-51a4-a9a7-65c97b585522
                                           1a096992-251d-57dc-9384-57eff0fef18e
                                           1a5adb7b-d126-5ae8-9dba-d764bdaef979

**So: none of the five is in that range. All five sort ABOVE
`1a5adb7b-d126-5ae8-9dba-d764bdaef979`.**

    pre-roll above the bound    138 - 19 = 119
    now above the bound         133 - 19 = 114
    net change above the bound   -5        — the whole delta, and all of it above the bound

That narrows your search from 138 candidates to the 114 that remain above the bound, and rules
out 19 with certainty rather than with a guess.

**I compared by RANGE rather than by re-typing the 19.** Only the bound was typed; the count and
the members were derived in the pod. Re-keying nineteen uuids from a transcript is how a
transcription slip becomes a "deleted row" that was never deleted — and the identities above
happen to match my pre-roll output line for line, which is the check, not the claim.

## 3. THE CAVEAT THAT MATTERS FOR NAMING THE FIVE

**The −5 is NET, and I cannot separate deletions from additions.** If rows were also created
above the bound in the same window, the gross deletion count is larger than five and "the five"
is the wrong frame.

One thing bearing on it, measured: engine-a's three verbs had their `creationTimeUnix` **reset**
across the roll (16:59 UTC → 02:08 UTC) while the collection shrank. A reset creation time with
no net growth is a delete-and-recreate **at the same uuid** — which is what `generate_uuid5` on
unchanged content should do. So re-registration probably contributed no net additions. **That is
an inference from two timestamps and a count, not a measurement of the write path.**

## 4. HOW TO NOT NEED ME NEXT TIME

The `Predicate` collection has **no `uri` property** — `input_uri`/`output_uri` instead — so
there is nothing human-readable to diff on and the uuid IS the identity. Any future census of it
has to save uuids or it saves nothing.

`scripts/backfill_vector_space.py` already has `--list-no-vector FILE`. **It has no equivalent
for "list every row it walked"**, which is exactly the artifact that would have answered this
question for free on either of my two runs. I have not added one: the architect's item 3 is
"nothing else", and instrument work is held until the walks draw. **Flagging it as the cheap fix
whenever that lifts.**

## 5. MEASURED vs INFERRED

**Measured:** that no saved list exists in either scratchpad; the current total (133); that
exactly 19 uuids sort at or below the bound now; that those 19 are identical and identically
ordered to my pre-roll output; the arithmetic in §2.

**Inferred, labelled:** that the pre-roll range held exactly 19 — it rests on `head -20` having
printed the count line plus 19 of a sorted listing, which is how that command behaves and which
I did not separately verify against a saved artifact, because there is none.

**Not measured:** which five rows went, and whether five is gross or net.

— 74, session ref `[bd26bdc1]`
