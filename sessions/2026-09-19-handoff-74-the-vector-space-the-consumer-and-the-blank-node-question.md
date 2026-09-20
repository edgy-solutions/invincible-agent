# Handoff — 74 (safety lane), 2026-09-19 end of session

to: ia-74/lane/74
read-by:
cc: ia-01/lane/01 (merge is yours) · the architect
from: ia-74/lane/74, session ref `[075ebc33]`

**Everything below is at `788bf89`, pushed. The tree is clean and I left nothing untracked
anywhere in the repo.**

---

## 1. THE EXACT NEXT STEP

**Read §2 of the architect's order first: there is a QUESTION to answer before any backfill is
scoped, and it is not ruled.** Do not start by running anything.

```
1.  cd ../ia-74
    git fetch origin
    git -C ../ia-74 pull --rebase origin master     # 54 behind; AGENTS.md:99 says rebase,
                                                    # do NOT merge master in
2.  (cd ../ia-74 && uv sync --extra agent-fleet)     # ITS OWN VENV, WITH THE EXTRA (AGENTS.md:100)
3.  (cd ../ia-74 && .venv/Scripts/python -c "import iagent,os;print('SAME TREE?', os.getcwd() in iagent.__file__)")
                                                    # MUST print True (AGENTS.md:101)
4.  uv run --frozen pytest tests/routing tests/safety -q
                                                    # expect 842 passed / 157 skipped at 788bf89
5.  Read, now that the rebase brings it into the tree:
      sessions/2026-09-19-packet-from-ca-the-scoped-slot-declaration-slotdecl-lacks.md
6.  ANSWER THE BLANK-NODE QUESTION (§4 below). It blocks scoping the backfill.
7.  Send the 16 uris to doc-tools/7f's successor (§4). They have NO re-embed path — 7f measured
    that, so the ask is "build one or rule the 16 filtered", not "re-embed these".
```

**Do not run `scripts/backfill_vector_space.py --apply`.** See §6.

---

## 2. STATE

    branch          lane/74
    head            788bf8949bd86cc3e8cf28ad4da3a02930d7d72d   (788bf89)
    origin/lane/74  ahead 0, behind 0 — pushed
    origin/master   ahead 2, behind 54
    working tree    CLEAN (`git status --porcelain` empty)
    untracked       NONE, anywhere in the repo
                    (`git status --porcelain --untracked-files=all | grep '^??'` -> empty)

**My two commits ahead of master:**

    f67c209  fix(backfill): the canary travels with the script, and the self-check survives duplicates
    788bf89  fix(routing): the declaration is `narrowed_by`, and declared-AND-bound is confirmed by mutation

Earlier commits this session are already in master's ancestry via Lane 1's merges, or are on the
lane below those two — `git log --oneline master..HEAD` is the authority, not this list.

**Files outside the repo.** Every probe and draft I wrote lives in this session's scratchpad and
is DISPOSABLE — nothing in the repo references it, and the committed probes are the durable form:

    C:\Users\cnogr\AppData\Local\Temp\claude\c--Users-cnogr-git-invincible-agent\075ebc33-ca71-4da4-aafb-43625755423f\scratchpad\

It holds the seam probes (`seam_probe*.py`), the scratch-collection arms
(`scratch_join*.py`, `scratch_put.py`, `scratch_forms.py`, `verify_dupes.py`), the population
scripts (`dupes.py`, `blanks.py`, `rank_population.py`), commit-message drafts (`msg*.txt`) and
two file backups I used for mutation testing (`v2_backup.py`, `sd_backup.py`). **Both backups
were restored and verified; neither differs from what is committed.**

Nothing of mine is in `C:\Users\cnogr\git\invincible-agent` (the master checkout) — I never wrote
there.

---

## 3. MEASURED vs INFERRED, per claim

**MEASURED — I ran it and read the output.**

| claim | how |
|---|---|
| `weaviate_hybrid_search` returns **1** for the census query | in-situ gate log on the census turn, and a direct call in the pod; limit=10 and limit=50 |
| the vector half returns nothing on `OntologyClass`/`Predicate` | halves separated: near_vector 0, hybrid α=1 → 0, α=0 → 1 |
| the cause is the legacy slot vs the named space | server's own error `"vector not found for target: default"` on an object's OWN stored vector |
| `DocumentChunk` works | same server, `nearObject(self)` returns self |
| the inferred join HOLDS | `Scratch74ArmA` reproduced the live failure verbatim from a bare create + positional write |
| three fixes work (B, C, D); D's schema already matches live | scratch collections, through INSERT **and** REPLACE |
| the backfill is lossless and idempotent | un-normalised probe: norms 5.000000 both sides, max\|delta\| 0.000e+00, re-run is a no-op |
| the two wire keys swap on repair | REST `vector`→None, `vectors.default`→768 dims |
| largest duplicate-vector group is **2** | full walk of both collections, bucketed by exact vector |
| `nearObject(a)` can return **b** first | scratch duplicate pair — the reason `rows[0]` is the wrong assertion |
| index is **96.2% blank nodes** (25,255 / 26,239) | full walk |
| no-vector set = **16 real + 1,299 blank** | full walk, `--list-no-vector` |
| `safety#Hazard` ranks **1st of 12,512**, Part 23rd, 0 blank nodes above | cosine over every vectorised SUSTAINMENT row |
| the live HAZ-1003 artifact **carries** `review_request` | called engine-safety directly |
| the consumer selects `safety_acceptance_direct` and binds the audience identically to the matrix TTL | run against the live artifact |
| `narrowed_by` must be declared-AND-bound | mutation: dropping `& set(offered)` turns 3 arms red |
| no `agent_fleet` request model sets `extra="forbid"` | grep before sending `bound_slots` to providers |
| `ENUMERATE_INSTANCES_URL` is set on the live fleet | read the configmap |

**INFERRED — reasoned, not run. Treat as a guess until someone measures it.**

* **That relocating blank nodes is harmless.** I measured that they do not crowd the TOP of one
  query's ranking. I did **not** measure what 25,255 of them do to recall across many queries,
  nor to HNSW build time or memory. §4's question exists because of this gap.
* **That the 16 vectorless real classes are vectorless because they lack definition text.** Their
  shape (BFO/IOF upper-ontology) makes it plausible. I never opened doc-tools' embed path.
* **That the write pass scales.** The READ pass is 25s over 26,239 rows, measured. The write pass
  is one PUT per row and I measured **one**. Duration and mid-run failure behaviour at 24,924
  rows are unmeasured.
* **That `_probe_retrieval_seam.py` and the backfill agree in the field.** They now share the
  same top-k semantics by construction; I ran each, never both against the same repaired row.

**NOT A CAUSE I MEASURED, AND LABELLED A GUESS:** why the 1,299 blank nodes lack vectors while
the other 23,956 have them. I have no mechanism for the split — only the counts.

---

## 4. RULED vs OPEN

**RULED (this order and the earlier ones, in sequence):**

* Fix shape **D** — declare the space at the create, address it at the write — for both Predicate
  creators. *Built, `19bc52f`.*
* The seal is `nearObject(self)`, retrievability not liveness, in the same commit. *Built,
  mutation-tested.*
* The self-check is **self within top-k at ~0, never `rows[0]`**. *Built; the probe brought to
  the same semantics.*
* The backfill has a dry run, a row range, built-in verification, and **is not run by me**.
  *Built; five corrections applied in `f67c209`.*
* The canary set reaches the pod as an argument. *`--canary safety`, in-file.*
* The wire-key warning at the top of the script and in the packet to Lane 1. *Both.*
* The declaration is `narrowed_by`, paired with the response's `scoped_by`; the gateway refusal
  stays **inert** until v0.9.4 is cut and pinned. *Renamed, `788bf89`.*
* `review_request` consumer: read the request, run `safety_acceptance_selection` on `level`,
  dispatch the selected definition. *Built.*

**OPEN, and whose:**

1. **SHOULD BLANK NODES BE RELOCATED AT ALL? — NOT RULED. The architect's §2, and it blocks
   scoping the backfill.** My population scoring, and what it does and does not show:

   > **Shows:** for the census query `"what hazards are unattended"`, scored against all 12,512
   > vectorised SUSTAINMENT rows, `safety#Hazard` is **rank 1** (cos 0.659), `product#Part` is
   > **rank 23** (0.520), **zero** blank nodes rank above Hazard and **none** appear in the top
   > 10. Their hex-id labels embed far from natural language. So on THIS query, turning vector
   > search on over the full corpus puts the right class first and the blank nodes nowhere.
   >
   > **Does NOT show:** anything about other queries — this is ONE question, and it is the one I
   > already knew the answer to, which is the weakest kind of test. Nothing about the other
   > 12,743 rows in MAINTENANCE. Nothing about recall@k across the census's 17 rows. Nothing
   > about HNSW build time, index size or query latency with 25,255 extra vectors — relocating
   > them is what builds them into the graph, and the read pass timing says nothing about that.
   > And nothing about whether a blank node could ever be a USEFUL answer, which is a modelling
   > question, not a retrieval one.
   >
   > **My read, offered as opinion not measurement:** relocating them is cheap and reversible in
   > kind, and excluding them needs a rule someone has to author and maintain. But the corpus is
   > 96% rows that can never be a routing answer, and that is worth deciding deliberately rather
   > than inheriting. **The cheap discriminator nobody has run: score the census's other 16
   > questions the same way and count blank nodes in each top-10.** That is an afternoon and it
   > converts this from opinion to evidence.

2. **doc-tools/7f: the 16 vectorless real classes, and 7f has NO re-embed path** (measured by
   them). The ask is therefore *"build one, or rule the 16 legitimately text-less and filter
   them"* — not "re-embed these". The uris are in
   `docs/measurements/ontologyclass-rows-with-no-vector-2026-09-19.txt` and the packet
   `2026-09-19-packet-from-74-to-7f-sixteen-reembeds-and-a-96-percent-index.md`.
   **Send them to 7f's SUCCESSOR** — mine was addressed `to: 7f` in this repo's inbox and has
   not been relayed.
3. **doc-tools owns `OntologyClass`'s writer** (`ontology_assets.py:386`). Until their half of
   fix D lands, **a re-ingest would undo the backfill**. Ordering not ruled.
4. **v0.9.4 is not cut.** ca's draft rides the next pin the fleet needs anyway (their §, ruled by
   the architect). My refusal branch is inert until then.
5. **Owed by me: the `risk_acceptance_medium` task row**, measured after the roll carrying the
   consumer — which must include `COPY policy/decisions/ /app/policy/decisions/`. It waits on
   the roll, **not** on cortex; the running frontend already serves the safety rows.

**ca's packet, per the order:** **no path ever reached me** — Chris did not hand one over. I read
it from `origin/master` at `be8ed5d` without merging, since the order also said to write the
handoff before further work. **Nothing I built depended on it.** It confirms `narrowed_by` as
`Optional[list[str]] = None` (the shape I assumed) and adds
`iagent_mesh.enumeration.unhonoured_scoping(declared, bound, response)` — which computes exactly
what `slot_disposition.py:473-474` computes locally. **When v0.9.4 lands, adopt theirs and delete
mine**; two implementations of one comparison is the drift this whole arc is about.

---

## 5. WHAT I GOT WRONG, AND WHAT CAUGHT IT

Every one was caught by something other than my own re-reading.

| wrong | caught by |
|---|---|
| `Dict[str,str]` in a Pydantic model under `from __future__ import annotations` — a **500 on first request** to the endpoint I had just widened, not an import error | `test_no_typing_generics_in_pydantic_models` |
| a `sed` line-range trim cut `return then` off the selector; every level selected `None` | the new consumer seals, 4 arms at once |
| an audience seal that demanded EVERY definition audience equal the engine's — `safety_concurrence` is deliberately a different queue | HAZ-1001, correctly |
| a skip whose stated reason was FALSE ("restate extras not installed"; restate imports fine — the real cause is a flat import at `restate_analyst/main.py:633`) | checking the skip instead of accepting it |
| the scoped_by refusal fired on ANY bound slot, refusing menus that were always right | `test_a_pick_from_the_menu_BINDS_and_merges`, an existing test |
| three of my own seal's matchers matched PROSE, not code — and one returned `[]` on a shape the code does not have, reporting two correctly-fixed files as broken | the seal failing for the wrong reason, then a positive control on the extractors |
| two packets with a `to:` line the address grammar rejects | `test_THE_REPO_INBOX_IS_FULLY_ADDRESSED`, twice |
| the backfill IMPORTED the fix it precedes — dead in a pod running the deployed image | **running it**; reading it would never have shown this |
| `http://host:8080:8080` — engine-o carries both env conventions at once | running it |
| a fabricated commit sha in a handoff draft (`3fbca0c` for `917879d`) | deriving it with `git log` instead of typing it |
| **claiming "the fix is a fix" from a hand-scored subset of SIX classes I had already picked out** | the 96.2% blank-node measurement, which a subset like that is blind to by construction |

The last one is the one to carry: the subset was chosen from the classes I believed in, so it
could only confirm me. It happened to survive the population test. It did not have to.

---

## 6. STANDING

* **Nothing touches a shared store without Chris.** `scripts/backfill_vector_space.py` does not
  run with `--apply` except by Chris, in daylight: **canary first** (`--canary safety`), then the
  walk question `"what hazards are unattended"`, then the rest in **one sitting**, and **never
  during a roll**. The script refuses `--apply` without `--i-have-read-the-warning`, refuses a
  non-routing collection, verifies the first relocated row before writing a second, and stops on
  the first regression. I created and deleted scratch collections only; the live collections were
  READ, and a final independent sweep confirms `Scratch74*` leftovers = `[]` and both routing
  collections unchanged (`legacy=768, vectors={}`).
* **No instrument work until the four walks draw.**
* **Never release commits I did not write.**

**And the warning that must travel with the repair, because it looks like the disaster it fixes:**
after a successful relocation a row reads as having **NO vector** on every instrument this fleet
has been using — REST `vector` is `None`, `_additional{vector}` is `[]` — while `vectors.default`
holds the dims. That is the repair working. The only check that distinguishes the states is
`nearObject(self)`, self within top-k at ~0.

— 74, session ref `[075ebc33]`
