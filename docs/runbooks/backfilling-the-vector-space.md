---
# EXPLAINS IS EMPTY, FOR THE REASON rolling-a-service.md ESTABLISHED (register R-015). Repairing
# a vector slot is an infrastructure act on a store. The mesh declares four lowercase verbs and
# 72 classes and NOT ONE of them concerns embeddings, vector spaces or storage repair, so there
# is no contract-depth target and minting `mesh:backfillVectors` is exactly the move the
# invented-IRI gate (ADR-0037 §1) refuses.
iri: docs:runbook-backfilling-the-vector-space
explains: []
doc_kind: how-to
audience_hint: ARCHITECT
---

# Runbook — backfilling the vector space (Chris's morning procedure)

**You are the only person who runs this.** `--apply` is yours, in daylight, never during a roll.
Everything below is one sitting: do not start step 3 intending to finish step 6 tomorrow.

---

## ⚠ READ THIS BEFORE YOU START — THE REPAIR LOOKS EXACTLY LIKE THE DISASTER

**After a row is successfully repaired it reads as having NO VECTOR on every instrument this
fleet has been using.**

    REST  /v1/objects?include=vector   `vector` -> None        `vectors.default` -> 768 dims
    GraphQL  _additional{vector}       []

**That is the repair working. It is not data loss. DO NOT REVERT ON THAT SIGNAL.** The two slots
are different keys on the wire, and every tool we had asks the legacy one — so rows appear to go
from "has a vector" to "has no vector" at the exact moment they become searchable.

**The only check that distinguishes the two states is `nearObject(self)` — self within top-k at
distance ~0, never `rows[0] is self`.** Duplicate vectors exist in this index; on a scratch pair
`nearObject(a)` returned **b** first. The script does this check itself: it verifies the FIRST
relocated row before writing a second, re-verifies every `--verify-every` rows, and stops on the
first regression.

Nothing is re-embedded, no LLM is called, nothing is deleted. Each row's own vector is read and
written back under a name. Measured lossless: norms identical, max|delta| 0.000e+00.

---

## 0. STOP CONDITIONS — check these first, they are cheap

* **PROVE THE SCRIPT, in the file that is about to run.** Step 2 pipes the script over stdin from
  **this checkout** (`< scripts/backfill_vector_space.py`), so the pod's image is irrelevant: the
  copy in your tree *is* the program. **Run this from `master` only** — a lane worktree can be
  behind, ahead, or mid-rebase, and the counts below are properties of a **copy**, not of "the
  script".

      cd /c/Users/cnogr/git/invincible-agent      # MASTER TREE. Not a lane worktree.
      git branch --show-current                   # expect: master
      git rev-parse --short HEAD                  # RECORD THIS. Every count you report is its.
      f=scripts/backfill_vector_space.py
      grep -c '^def verify_self' "$f"             # expect 1   — the ruled top-k check is present
      grep -c '^def retrievable'  "$f"            # expect 0   — the rows[0] form is GONE
      grep -c -- '--list-walked'  "$f"            # expect 3   — the flag exists (>=1 is the rule)
      git status --porcelain "$f"                 # expect NOTHING printed

  **Any other answer: stop.** A `1` on the second line means you are holding a copy from before
  `7ac0765`, whose verification asks "is self the *single* nearest neighbour" under `limit:1` — it
  reds on a row it has just repaired correctly, and five known duplicate-vector twins in this index
  will trip it. A `0` on the third means `--list-walked` is absent and the run cannot save the
  uuids it walked; 138 `Predicate` uuids were lost in exactly that way on 2026-09-19.

  **And positive-control the greps before you trust the zero** — a matcher that matches nothing
  also returns `0`, and that reads as a pass:

      git show 7ac0765~1:scripts/backfill_vector_space.py | grep -c '^def retrievable'   # expect 1

  If that prints `1` the pattern works and your `0` above is a real absence. If it prints `0` your
  `grep` is broken, or the sha is unreachable, and **you have measured nothing**.

  *Why this step exists:* on 2026-09-19 a correction naming `retrievable()` and `rows[0]` in this
  file was reported back as landing on no script at all. The correction was right — it landed on
  the copy at `7ac0765~1`, `:161` and `:169` — and the reply was written from a *different copy of
  the same path*. Counts above stated at 2026-09-23 with `master` at `c6436ee`, and identically in
  `lane/74` at `1c1f061`; the control discriminates on all three lines (`7ac0765~1` answers
  1 / 0 / 0).

* **Is a roll in progress?** If yes, stop. No backfill during a roll, no roll during a backfill.

      kubectl -n sandbox get pods | awk 'NR>1 && $2!="1/1" && $3!="Completed"'

  Anything printed means the fleet is still moving. **Wait for silence.** (DISCOVERED: the fleet
  rolled in the middle of a measurement on 2026-09-19 and the `Predicate` count moved 138 → 133
  in seven minutes, with rows deleted and re-created.)

* **Has doc-tools rolled its writer?** If doc-tools has re-ingested since its fix landed, the
  `OntologyClass` numbers below will be different — that is expected, not a defect.

* **Set the pod once and reuse it.** Any fleet pod with `requests` and the cluster env works:

      BFF=$(kubectl -n sandbox get pods --no-headers -o custom-columns=":metadata.name" \
              | grep '^iagent-cortex-bff-')
      echo "$BFF"

* **⚠ GIT BASH REWRITES POD PATHS. This will waste an hour if you hit it cold.** DISCOVERED
  2026-09-19: `--list-walked /tmp/x.txt` silently became
  `C:/Users/.../AppData/Local/Temp/x.txt` before `kubectl` saw it, and the script died with
  `FileNotFoundError` on a path that does not exist inside a Linux pod. **Prefix every command
  that passes a pod-side path:**

      MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' kubectl ...

---

## 1. THE EMBED-GATEWAY CHECK

The backfill does not embed anything, so why check? **Because a dead embed gateway makes the
registrar write NEW rows with no vector at all** — and a vectorless row is the one case this
script cannot repair. You want to know the gateway is healthy *before* you spend a sitting, so a
growing `no-vector` count is not mistaken for something the backfill did.

    kubectl -n sandbox exec $BFF -- python -c "
    try:
        from utils.embed import embed_document
    except ImportError:
        from agent_fleet.utils.embed import embed_document
    v = embed_document('backfill preflight probe')
    n = sum(x*x for x in v) ** 0.5
    print('EMBED GATEWAY OK  dims=%d  norm=%.4f' % (len(v), n))
    "

**Expect exactly:** `EMBED GATEWAY OK  dims=768  norm=1.0000` (measured 2026-09-20 03:12 UTC).

**If it raises or the dims are not 768, STOP.** Do not run the backfill. The relocation itself
would still be safe, but you would be working blind on the one number that tells you whether the
store is getting worse underneath you.

---

## 2. THE DRY RUN — in this sitting, immediately before the apply

**Not "a dry run I did yesterday".** The counts below are a SNAPSHOT and go stale in hours; what
the script promises is the partition IDENTITY, which it checks itself and fails the run on.

    cd <your checkout at the rolled sha or later>

    for C in OntologyClass Predicate; do
      MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' kubectl -n sandbox exec -i $BFF -- \
        python - --classes $C --progress-every 30000 --list-walked "/tmp/$C-before.txt" \
        < scripts/backfill_vector_space.py
    done

**Reference numbers, measured 2026-09-20 03:10 UTC on `c0005142a610…`, committed as
`docs/measurements/*-walked-2026-09-20-post-roll.txt`:**

    OntologyClass   26,239 = 25,255 blank-skipped + 16 no-vector + 968 would-relocate
    Predicate          133 =     89 already-named +                 44 would-relocate

**A different number is a QUESTION, not a blocker.** Ask which writer ran: engine verb
registration on startup (fixed, ships named), frontend/presentation registration (fixed, ships
named), doc-tools' ontology ingest (**fix not yet rolled** — a re-ingest puts `OntologyClass`
rows back in the legacy slot and re-leaks blank nodes).

**Save the listings out of the pod. The file dies with the pod and this is the step people skip:**

    for C in OntologyClass Predicate; do
      MSYS_NO_PATHCONV=1 kubectl -n sandbox exec $BFF -- cat "/tmp/$C-before.txt" \
        | tr -d '\r' > "docs/measurements/$C-before.txt"
    done

`tr -d` is not decoration: **kubectl on Windows emits CRLF**, and these files exist to be diffed.

---

## 3. THE CANARY — six rows, and it is the ruled first write

    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' kubectl -n sandbox exec -i $BFF -- \
      python - --classes OntologyClass --canary safety \
      --apply --i-have-read-the-warning \
      < scripts/backfill_vector_space.py

**Expect 6 rows relocated, and a `VERIFY (first relocated row) … RETRIEVABLE` line before the
second write.** The canary set travels inside the script, so it works piped into a pod.

**If the first row verifies NOT RETRIEVABLE the script stops itself**, having written exactly one
row. That is the write shape being wrong, not the plan. Stop and report; do not re-run.

Six rows means a mistake costs six rows, every one re-derivable from the ontology. That is why
this set was chosen — not because it is small, but because **the next step can tell whether it
worked**, which a silent canary cannot.

---

## 4. THE QUESTION — the canary's actual pass condition

    uv run --frozen --extra agent-fleet python scripts/walk_census.py \
      --only safety-unattended-hazards

The row asks *"what hazards are unattended"* as **bob / SAFETY_ENGINEER / SUSTAINMENT** and
expects verb `find_orphaned_hazards`, archetype `CONTRIBUTION_RANKING`, at least 3 rows,
disposition `drawn`.

**This is the step that makes the canary meaningful.** "The script did not crash" is not a pass.
Before the repair this question builds a pool of one (`product#Part`) and abstains, while the
query vector ranks `safety#Hazard` 0.659 above `product#Part` 0.520 — so it is the question that
visibly changes when the named space starts answering.

**If it still abstains after a clean canary, STOP and report.** Six rows are relocated and
harmless; the rest of the collection is untouched, and the reason the question did not move is
worth more than finishing the sitting.

---

## 5. THE REST — one sitting, both collections

    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' kubectl -n sandbox exec -i $BFF -- \
      python - --classes OntologyClass,Predicate --progress-every 2000 \
      --apply --i-have-read-the-warning \
      < scripts/backfill_vector_space.py

**`Predicate` IS IN SCOPE** — 44 legacy rows at settle. **The architect expects that to read
about 1 after your first page load of the day**, because an authenticated page load POSTs the
full capability menu and the registrar re-writes each presentation row by name. **Treat that as
an expectation to check, not a target**: if the dry run in step 2 says something else, the
number is the finding and the backfill still handles whatever is actually there.

**Known, and not a defect:** the script reports the blank-node check as INERT on `Predicate`.
Those rows carry `input_uri`/`output_uri` and no `uri`, so there is nothing for the check to
read — correct, because a `Predicate` row is a verb registration and can never be a blank node.

**Timing, honestly:** the read pass is ~25–32s over 26,239 rows, measured. The write pass is one
PUT per row and **its duration at ~1,000 rows has never been measured.** Do not start this with
ten minutes to spare.

**If it stops mid-run**, re-running is safe: relocated rows skip as `already-named`. An HTTP
error prints the counts on the way out so you know how many rows were already rewritten.

---

## 6. THE SECOND DRY RUN — it must read ZERO

    for C in OntologyClass Predicate; do
      MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' kubectl -n sandbox exec -i $BFF -- \
        python - --classes $C --progress-every 30000 --list-walked "/tmp/$C-after.txt" \
        < scripts/backfill_vector_space.py
    done

**`would-relocate` must be 0 for both.** `no-vector` will still be 16 on `OntologyClass` — those
need a RE-EMBED and this script cannot repair them; that is doc-tools' item, not a failure here.

### ⛔ A NON-ZERO SECOND READING IS A FINDING, NOT A RETRY

**Do not re-run `--apply`.** A non-zero `would-relocate` after a completed apply means **a live
writer is still filling the legacy slot while you work**, and re-applying would chase it forever
without closing the gap. Stop, and report which collection moved and by how much.

Save the after-listings the same way as step 2, then name the delta:

    for C in OntologyClass Predicate; do
      MSYS_NO_PATHCONV=1 kubectl -n sandbox exec $BFF -- cat "/tmp/$C-after.txt" \
        | tr -d '\r' > "docs/measurements/$C-after.txt"
      diff "docs/measurements/$C-before.txt" "docs/measurements/$C-after.txt" | head -40
    done

**This diff is the whole reason `--list-walked` exists.** A count cannot name which rows moved,
and `Predicate` has no human-readable key at all — the uuid IS the identity. On 2026-09-19 that
collection's size was read twice and the five rows that vanished could not be named afterwards,
because only the counts had been kept.

---

## 7. WHAT IS DELIBERATELY NOT IN THIS RUNBOOK

* **Deleting the 25,255 blank-node rows.** Ruled a separate, later act and yours. This script
  only declines to repair them. **And it must not happen before doc-tools' filter fix is
  running**: rdflib mints a fresh blank-node id per parse and the row uuid is `uuid5(uri)`, so
  every re-ingest ADDS the blank population instead of overwriting it. **The 96.2% is a rate,
  not a level** — a delete against a leaking writer refills on the next prime.
* **Re-embedding the 16 vectorless named classes.** No re-embed path exists in doc-tools; it is
  an either/or with them (build one, or rule the 16 filtered).

## 8. IF YOU ONLY REMEMBER FOUR THINGS

1. **A repaired row reads as vectorless. That is the repair.** Do not revert.
2. **Dry run immediately before, dry run immediately after, same sitting.**
3. **Zero on the second dry run, or it is a finding — never a retry.**
4. **Save the listings out of the pod.** A census inside a container is not a census.
