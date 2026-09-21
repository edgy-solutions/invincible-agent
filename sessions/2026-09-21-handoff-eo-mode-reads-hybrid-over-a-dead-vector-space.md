# Handoff — lane eo, 2026-09-21: `mode` reads `hybrid` over a dead vector space

to: `ia-74` / `lane/74` (the consolidated worker)
from: `ia-eo` / `lane/eo` — **this lane is closing. Nothing below is held by anyone until 74 takes it.**
read-by:

## Current state

    worktree / branch   c:/Users/cnogr/git/ia-eo  ·  lane/eo
    HEAD                9c7ea4b3690cef473b2885bd276eade155ae6d38   (9c7ea4b)
    vs master           22 behind, 0 ahead          [measured]
    vs origin/lane/eo   87 ahead, 0 behind          [measured]
    tree                CLEAN before and after everything below   [measured]

**`lane/eo` has ZERO commits of its own.** [measured] It is an ancestor of `master`; my dispatch's
"rebase" was a fast-forward and rewrote nothing. All work attributed here is already in `master`.

**Its upstream is `origin/master`, not `origin/lane/eo`.** [measured] `branch.lane/eo.merge =
refs/heads/master`, `push.default` unset. A bare `git push` **fatals** (measured, `--dry-run`:
*"The upstream branch … does not match the name of your current branch"*) — a papercut, not a live
footgun — **but `git pull` here pulls MASTER.** **74: fix the upstream before you pull.**

## Decisions and rulings received

* **The `mode` vocabulary is the SDK's to rule, not a lane's.** I proposed no third value. ca has
  since filed `sessions/2026-09-19-packet-from-ca-mode-measures-the-embed-call-not-the-vector-leg.md`
  — Option A (`hybrid` must be EARNED), recommended. **Unruled as of this writing.** [measured]
* **A packet in another lane's checkout is not committed by its author.** Honoured; ca landed both.
* **Nothing touches a shared store without Chris.** All read-only — no write, backfill, re-embed or
  schema change [measured] — and **probed inside the pod, never a port-forward** (`kubectl exec`).

## The measurement

At **`9c7ea4b`**, pod `iagent-engine-o-56fd8d8c79-ls5d7`, context `edge`, ns `sandbox`, image
`ontology-service:c0005142a610bc7759cfc8953666aee7c6064632`. **Subject pinned first** [measured]: pod
`/app/mesh_vectors.py`, my HEAD copy and `git show c0005142:…` all sha256 `061d3c70109e1e07…`.

`WeaviateVectors.nominate()`, query **"what hazards are unattended"**, `OntologyClass`: [all measured]

| call | `outcome` | `mode` | rows |
|---|---|---|---|
| `domains=()` | `answered` | **`hybrid`** | 10 — not one a hazard class |
| `domains=("SUSTAINMENT",)` | `answered` | **`hybrid`** | **1** (`sustainment/product#Part`) |
| nonsense query | `empty` | **`hybrid`** | 0 |

The vector leg contributed nothing to any of it: [all measured]

* same query forced down the **bm25** arm → **identical rows, identical order**
* **`near_vector` alone → 0 rows**, no error
* **`nearObject(self)`** on a row reading back 768 dims → **REFUSED**, `vector not found for target: default.`
* `hybrid(query+vector)` → rows returned, **no refusal** — the vector half is dropped silently

**The control discriminates** [measured] — I checked, because both arms refused: the real row says
`vector not found for target: default.`, a nonexistent uuid `vector not found.` `OntologyClass`
declares exactly one space, a **named** one called `default`; rows hold 768 dims it cannot resolve.
`safety#Hazard` is present, reads back 768 dims, never surfaces for its own census question.

**So `mode` reports whether THIS READER's embed call succeeded — never whether the store could use
the vector.** It reads `hybrid` with every vector in the collection unreachable, the state it is in.

**Report:** `iagent-mesh-sdk/sessions/2026-09-19-measurement-from-eo-mode-says-hybrid-over-a-dead-vector-space.md`

**`WeaviateVectors` has no live consumer** [measured]: two references tree-wide — its own definition
and `tests/test_mesh_vectors_conforms.py`. It ships in the image; nothing in the serving path
constructs it. **`main.py`'s inline retrieval (≈1105–1130 classes, ≈1270–1321 predicates) emits no
`mode` at all and its bm25 fallback is a `print()` — INFERRED: I read that path, I did not run it.**
That it returns the same ten rows is **inferred** too, from the same filter and the same `hybrid()`.

Conformance at `9c7ea4b` under **v0.9.3**: `tests/test_mesh_*_conforms.py` → **44 passed, 0 failed,
0 skipped, exit 0** [measured]; `uv run` did the sync itself (0.9.2 installed vs 0.9.3 pinned).
**One of the 44 asserted nothing** — `test_the_IMPORTED_SDK_IS_THE_PINNED_ARTIFACT_not_a_working_tree`
early-`return`s off a non-editable SDK: correct here, but its assertion did not run. [measured]

## Files I placed in another lane's checkout

Both in `c:\Users\cnogr\git\iagent-mesh-sdk\sessions\`. **Neither is uncommitted any more — ca landed both** [measured]:

* `2026-09-19-measurement-from-eo-mode-says-hybrid-over-a-dead-vector-space.md` → **`c303b35`**
* `2026-09-19-handoff-sdk-ca-the-v0-9-4-draft-is-on-a-branch-and-uncut.md` (my `read-by` stamp only) → ca amended at **`8a74e68`**, **`6bfce06`**

Nothing of mine is uncommitted in any checkout other than this handoff.

## Tried and failed

* **First `nearObject` control could not discriminate** — both arms refused and I had truncated both
  messages at the same point. Re-ran whole; they differ. *A control that cannot answer differently
  is not a control.*
* **First slot probe asked REST `include=vectors`** → HTTP 400. REST surfaces the bytes under the
  legacy `vector` key, the v4 gRPC client under `default` — two views, one storage. I claim only
  that the `default` index cannot resolve them, never which physical slot holds them. [measured]
* **Git Bash rewrote `/app/…` into `C:/Program Files/Git/app/…`** on the first `kubectl exec`; fixed
  with `MSYS_NO_PATHCONV=1`. **Master moved under me twice** (79→87 behind; 22 now) — hence the shas.

## Open questions — NOT mine to rule

* **`include_referents`** — ca's `sessions/2026-09-19-packet-from-ca-include-referents-the-wrong-one-is-main-pys-default.md`. Open.
* **The five open store fields.** Open.
* **The `mode` vocabulary itself.** ca's Option A is a proposal, unruled — and ruling it is *not
  sufficient*: the fix lands on the conformant reader, while the live inline path has no `mode`
  field at all. **That second half has no owner.** Nor is `OntologyClass`'s repair measured by me.

## NEXT TASK — for the worker (`lane/74`)

**Force the bm25 arm on `Predicate` and compare row-for-row with `hybrid`. READ-ONLY.** Lane 1
named this as **the discriminator for its census attribution**.

Why `Predicate` and not `OntologyClass`: `Predicate` is **mixed**. Per Lane 1's census at
`docs/measurements/predicate-retrievability-census-2026-09-19-post-roll.txt` [measured by Lane 1,
not by me]: **133 total, 89 retrievable, 44 unreachable, 0 with no vector** — slot states
`named=89, legacy=44`, partition sums to 133 of 133, all 44 failures `slot=legacy`. So **89 rows
are reachable** and hybrid *should* diverge from bm25; on `OntologyClass` the two were identical
because nothing was reachable at all. **If hybrid and bm25 come back identical on `Predicate` too,
the vector leg contributes nothing even where the index CAN reach the rows — a different and larger
finding than mine.**

Notes: `Predicate`'s domain filter carries the ADR-0009 agnostic branch (`domains contains_any` OR
`length == 0`), so scope moves the pool differently than on the class side; the census's five
duplicate-vector pairs (twins at ~1e-7) are a ranking hazard, not a retrievability one. Use the
census's own negative control.
