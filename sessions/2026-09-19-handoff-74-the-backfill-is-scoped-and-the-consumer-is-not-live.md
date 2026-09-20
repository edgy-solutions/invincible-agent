# Handoff — 74 (safety lane), 2026-09-19 night: the backfill is scoped, and the consumer is not live

    to:        ia-74/lane/74
    cc:        ia-01/lane/01 (merge is yours; one file to place in doc-tools) · the architect
    from:      ia-74/lane/74, session ref `[bd26bdc1]`
    read-by:   ____________________

**Everything below is at `c5da203`, pushed. Working tree clean; I wrote ONE file outside this
repo and it is named in §4.**

---

## 1. THE EXACT NEXT STEP

1. `git -C ../ia-74 pull --rebase origin master` — I am 4 ahead / 0 behind as of tonight.
2. `(cd ../ia-74 && uv sync --extra agent-fleet)` then the SAME TREE line. **The declared form
   in `AGENTS.md:101` has NO `--locked`** — the architect's §6 quotes it with one. Use the file.
3. **Do not re-open the blank-node question.** It is ruled and the ruling's condition is
   discharged (§2). My 16-question discriminator is withdrawn and was never run.
4. **§5 is the only thing still owed by this lane and it is BLOCKED ON THE ROLL, not on cortex.**
   Read §5 before you check anything: the precondition you were given is TRUE today on a pod
   that cannot possibly have the consumer.

---

## 2. THE ARCHITECT'S ORDER, ITEM BY ITEM

| item | state |
|---|---|
| §1 steps 1–5 (rebase, venv, SAME TREE, suite, ca's packet) | **done**, §3 |
| §2 blank-node ruling + withdraw the discriminator | **done** — condition discharged, §4 |
| §3 scope the script to named rows only | **done and measured**, `c5da203`, §5 |
| §4 deliver the 16-uri packet into `doc-tools/sessions/` | **done**, placed not committed, §4 |
| §5 measure the `risk_acceptance_medium` task row | **BLOCKED, correctly** — §6 |

---

## 3. §1, AND THE TWO THINGS IT TURNED UP

    rebase        3 commits replayed clean onto c000514; 0 behind
    venv          uv sync --extra agent-fleet; SAME TREE? True
    SDK           installed iagent-mesh 0.9.3 == pyproject pin v0.9.3 (checked, not assumed)
    suite         842 passed / 157 skipped in 201.96s  —  tests/routing tests/safety
                  EXACTLY the count my predecessor predicted, and it SURVIVES the rebase over
                  54 commits of fleet work. Windows side. Tree verified clean before AND after
                  the run, so the count belongs to the rebased head and not to a directory
                  somebody was typing into.

**ca's packet, read.** `narrowed_by` is ruled, and the condition the architect attached — each
docstring naming the other field and stating `scoped_by <= narrowed_by & bound` — is met, and ca
checks it **mechanically** over the live docstrings rather than by having read them. My gateway
refusal stays inert until v0.9.4 is cut and pinned. **When it lands, adopt
`iagent_mesh.enumeration.unhonoured_scoping` and delete my local copy** — it computes exactly
what `slot_disposition.py:473-474` computes, and two implementations of one comparison is the
drift this whole arc is about. Ordering is unchanged and still hard: cut → pin → declare.

**One correction owed to the architect, small and worth making because it travels into work
orders:** their §6 gives this repo's declared env command as `uv sync --locked --extra
agent-fleet`. `AGENTS.md:101` has no `--locked`, and nothing in that file declares one for
`sync`. Same shape as the bare-`uv sync` slip they already recorded in their own §5.

## 4. THE BLANK-NODE RULING — the condition is DISCHARGED, and I read it myself

The ruling was *conditional on doc-tools confirming the read on `lane/7f`'s head*. I did not wait
for the confirmation and I did not take the premise on trust: **I read it at
`doc-tools` `lane/7f` @ `aa36e41`.** It holds on all three points.

| leg | SPARQL | Python | sealed |
|---|---|---|---|
| Neo4j `sync_jena_ontologies_to_neo4j` | **YES** `FILTER(!isBlank(?uri))` :1649 | **YES** `isinstance(..., BNode)` :1673 | **YES** `tests/test_ontology_assets_blank_node_filter.py` |
| Weaviate dual-write in `ingest_ontology_to_jena` | **NO** (:1151‑1167) | **NO** (:1169‑1175) | **NO** |

`sync_ontology_to_weaviate` (:663) adds no check either, so there is no downstream backstop.
**The 96.2% is a leak one leg closed and the other never had.** Not a design.

**Two things in that file I did NOT expect, and both are worth someone's time:**

* **doc-tools' own comment already counts the second writer.** :1618‑1626 records the 2026-06-15
  history — the filter was Python-side, checked `startswith("Bnode_")`/`"_:"`, *"which never
  match"* rdflib's output, and *"substrate count grew 1,191 blank-node phantoms **across two
  writers**, this pipeline contributing 441."* **The comment counts two and the fix reached
  one.** The ordinary shape: the reported instance got fixed, the population was never
  enumerated, and the neighbour kept running with the comment recording that it existed.
* **A false sentence sits where it will stop the next reader from looking.**
  `derive_missing_class_labels`:270‑271 says blank nodes are *"already excluded downstream"*.
  True of Neo4j, **false of Weaviate** — and it reads as settled fact in a file that discusses
  blank nodes in four separate places.

**The discriminator was withdrawn before I spent anything on it.** Recording that because the
withdrawal was right for a reason worth keeping: it was built to decide a question the writer's
source already answers, and an afternoon of scoring 16 questions would have produced evidence
for a conclusion that did not need any.

## 5. THE SCRIPT IS SCOPED — and the predicate nearly went in wrong

`c5da203`. Blank rows are skipped, never relocated, and **the predicate is stated in the script
with its evidence** rather than inherited from a scratch file that does not travel into a pod.

**THE FINDING: THERE ARE TWO BLANK SPELLINGS, AND DOC-TOOLS' DOCUMENTED FORM MATCHES ONLY ONE.**

    1,296 / 1,299   N + 32 hex          rdflib BNode.__str__ — the form doc-tools documents
        3 / 1,299   n + 32 hex + b246   lowercase, suffixed — their documented form MISSES it

Had I keyed on the documented regex — which is the obvious thing to do, it is written down and
it is theirs — those rows would have classified **named**, and been either relocated or reported
to doc-tools as re-embed work. **The number that decides the entire dry run turns on the
predicate**, so both spellings are named in the script and the evidence sits beside each.

**And a third bucket exists because that census was a SAMPLE.** I enumerated spellings over the
1,299 *vectorless* blanks — never over all 25,255; the other 23,956 were never listed row by
row. So a blank-LOOKING uri in neither known spelling is `ambiguous`: not written, printed, and
the run exits non-zero. **Then the full walk measured `ambiguous` = 0 across all 26,239 rows**,
which upgrades the sample to a population fact: there is no third spelling. The guard stays, for
the next ingest.

**Order matters and is commented as such.** The blank check runs FIRST — before `already-named`,
before `no-vector` — so the outcomes partition the collection and sum to the walk. Ordered later,
the 1,299 vectorless blank nodes land in `no-vector` and get sent to doc-tools as re-embed work,
which is the wrong ask for a row that should not be in the index at all.

**THE DRY RUN, against the live store, matching the architect's arithmetic exactly:**

    OntologyClass   26,239 = 25,255 blank-skipped + 16 no-vector + 968 would-relocate
    Predicate          138 would-relocate
    ambiguous            0
    canary               6 would-relocate — unchanged, as ordered

**One more guard, because the filter was right for an accidental reason.** `Predicate` rows carry
`input_uri`/`output_uri` and **no `uri`**, so `blankness()` reads `""` and answers "named" for all
138. That outcome is correct — a Predicate row is a verb registration, not an RDF class node —
but a filter returning the right answer *because it reads a field that does not exist* is one
collection away from silently passing everything. So each run now **states which collections the
check was live on**, and refuses a clean exit if a collection not in `URILESS_CLASSES` turns out
to carry no uris at all.

**Deleting the existing blank rows is NOT in this script and is NOT ordered.** It only declines
to repair them. That act is separate, later, and Chris's.

**Owed and deliberately not done: a seal on the predicate.** No test imports this script, so
tonight's green does not cover it and I have not pretended otherwise in the commit message.
Instrument work is held until the four walks draw; when it lifts, this is first.

## 6. §5 IS BLOCKED, AND THE PRECONDITION I WAS GIVEN CANNOT TELL THE STATES APART

The order: *"When Lane 1 tells you the consumer is live (`/app/policy/decisions` present):
measure the `risk_acceptance_medium` task row."* Lane 1 has not told me. **The precondition is
checkable, so I checked it instead of waiting — and it does not mean what it looks like.**

    iagent-cortex-bff     /app/policy/decisions  PRESENT   (holds only README.md)
    iagent-data-analyst   /app/policy/decisions  ABSENT

**Both pods run image `91d8d34e…`, which does NOT contain my consumer commit `917879d`** —
verified by `merge-base --is-ancestor`, not by dates. So the precondition reads **TRUE on
cortex-bff on an image that has no consumer in it at all.** Checked there, it is a guard that
cannot fire: true on both sides of the question it is asked.

**The reason is in my own earlier packet and I nearly re-derived it as a contradiction.**
cortex-bff's image copies the whole `policy/` tree — I confirmed it in the container: `users.yaml`,
`groups.yaml`, `task_grants.yaml` and fifteen more, far beyond `Dockerfile.agent`'s per-file
COPY lines. So `/app/policy/decisions` is present there **without** the COPY line, and always was.
`data-analyst` is built from the per-file path, and it is the pod that actually runs
`SafetyAcceptance`. The packet already said *"cortex-bff needs no line"*. **Two readings that
look contradictory were about two different images.**

> **So the precondition must name the pod: `/app/policy/decisions` present in
> `iagent-data-analyst`.** It is ABSENT there today, which is the correct reading of "not yet
> rolled", and it will appear exactly when the roll carries `917879d`.

**Measured, so nobody re-checks it:** none of `acceptance_selection.py`,
`safety_acceptance_workflow.py`, `acceptance_request.py` is in either running image. The consumer
is not live anywhere. §5 stays owed and unstarted, and **it waits on the ROLL, not on cortex** —
the running frontend already serves the safety rows.

## 7. ONE THING I FOUND THAT IS NOBODY'S ASSIGNMENT — the store has a live writer

My 17:13 packet reports `Predicate` at **135 rows**. Tonight it is **138**. I chased it exactly
as far as naming it and no further:

    3 rows created 2026-09-20 00:52 UTC — about an hour before this handoff
    all three are `mesh:rendersAs` bindings for `cortex-ui-desktop`
    no job ran; no pod is younger than 8h

**Measured:** the count, the creation timestamps, the predicate names, and that no Kubernetes job
or recent pod accounts for them. **NOT measured:** what wrote them. Most likely cortex's
vocabulary work landing, but I did not establish it and it should not be repeated as though I had.

**Why it matters to the backfill rather than being trivia:** the routing store is being written
to by something long-running, and **new rows still go into the legacy slot** until doc-tools'
half of fix D ships. So (a) the dry-run counts are a snapshot with a short shelf life — **re-run
the dry run immediately before `--apply`**, and (b) a single pass will not be final: rows written
after the walk passes them stay broken, and the remedy is a second pass, which is safe because
relocated rows skip as `already-named`.

**It also means my own 135 was never written down as a list.** I could not name the three by
diffing because no uri list was kept — and `Predicate` rows have no `uri` property to diff on.
That is the cheap thing the next run should capture.

---

## 8. STATE

    branch          lane/74
    head            c5da203
    vs origin/master  4 ahead / 0 behind; pushed (force-with-lease, rebase)
    working tree    CLEAN
    suite           842 passed / 157 skipped (tests/routing tests/safety), Windows

    7ac0765  fix(backfill): the canary travels with the script, and the self-check survives duplicates
    2685609  fix(routing): the declaration is `narrowed_by`, and declared-AND-bound is confirmed by mutation
    5914a1b  docs(handoff): 74 — the vector space, the consumer, and the blank-node question
    c5da203  fix(backfill): relocate NAMED rows only, and the blank predicate lives in the script

**OUTSIDE THIS REPO — one file, for Lane 1 to commit, and I did not commit it:**

    c:\Users\cnogr\git\doc-tools\sessions\
        2026-09-19-packet-from-74-the-weaviate-leg-has-no-blank-node-filter.md

Addressed `c:\Users\cnogr\git\doc-tools :: lane/7f`, per their own worktree::branch convention.
It answers the exact read their §1 ordered first, carries the sixteen re-embed uris with the
either/or ask (build a path, or rule them text-less), and carries the wire-key warning. **Nothing
else of mine is in that tree.**

## 9. STANDING — unchanged

* **Nothing touches a shared store without Chris.** Everything I ran tonight was READ-ONLY: dry
  runs, walks and `ls` in containers. No `--apply`, no writes, no scratch collections.
* `--apply` is Chris's, in daylight, **never during a roll**, canary first, then
  *"what hazards are unattended"*, then the rest in one sitting.
* **After a successful repair a row reads as having NO vector on every instrument this fleet has
  been using.** REST `vector` `None`, `_additional{vector}` `[]`, `vectors.default` 768 dims.
  That is the repair. **Do not revert on that signal.** The only check that distinguishes the
  states is `nearObject(self)`, self within top-k at ~0 — never `rows[0]`.
* No instrument work until the four walks draw.
* Never release commits I did not write.

## 10. MEASURED vs INFERRED, for everything new tonight

**MEASURED — I ran it and read the output:** the rebase and the suite count, with the tree
verified still on both sides · installed-vs-pinned SDK · the three doc-tools reads at `aa36e41`
and the absence of a Weaviate-leg seal · the two blank spellings and their 1,296/3 split · the
predicate positive-controlled in both directions (1,299/1,299 blank, 16/16 named, a synthetic
third spelling → ambiguous, real uris → named) · the full dry run on both collections and the
canary · `ambiguous = 0` over all 26,239 · that `Predicate` rows carry no `uri` · that
`/app/policy/decisions` is present in cortex-bff and absent in data-analyst · that the consumer
modules are in neither image · that `917879d` is not an ancestor of the deployed `91d8d34` ·
`Predicate` at 138 with three rows created 00:52 UTC.

**INFERRED, and labelled:** that the Weaviate leg is the "second writer" the :1621 comment counts
— those counts are of a different substrate and I did not reconcile them · that the three new
predicates are cortex's vocabulary work · that the sixteen are vectorless for want of definition
text (I have still never opened doc-tools' embed path) · that a second backfill pass is the right
remedy for rows written mid-walk — reasoned from the `already-named` skip, not run.

— 74, session ref `[bd26bdc1]`

---

# ADDENDUM, same session, ~40 minutes later — THE ROLL FIRED AND THE TITLE OF THIS FILE IS NOW WRONG

**§6 above says the consumer is not live anywhere. THAT IS NO LONGER TRUE, and this addendum is
here rather than in a new file because the paragraph above is the one a reader will find first.**

The fleet rolled to `c0005142a610bc7759cfc8953666aee7c6064632` while I was working — I caught it
in the act, images pulling mid-command. **It carries `917879d` (the consumer + the Dockerfile
`COPY policy/decisions/` line) and `19bc52f` (fix D for the Predicate writers).** It does NOT
carry any of my five lane commits.

## What is now true

* **The consumer is LIVE and exercised, in `iagent-engine-a`** — the deployment running the
  `restate-analyst` image. Imported in the pod: `decision_dirs()` resolves BOTH the seed and the
  overlay, `load_table()` is True, and `select('Low'/'Medium')` → `safety_acceptance_direct`,
  `select('High'/'Serious')` → `safety_concurrence`. A lowercase level refuses with a message
  naming the declared domain, which is the control.
* **The producer still emits on the rolled image**: engine-safety returns `review_request` for
  HAZ-1003, kind `risk_acceptance_medium`, audience `risk_acceptance_medium:SUSTAINMENT`, and
  `risk_level: Medium` — which is the key `select()` answers `safety_acceptance_direct` for.
  **Called DIRECTLY on port 8099, bypassing the gateway, so no task was opened.**
* **`§6`'s corrected precondition was STILL one pod out, and I had it wrong too.**
  `iagent-data-analyst` is a *different agent* (`data-analyst` image). The consumer lives in
  `iagent-engine-a`. Checked on data-analyst, all three conditions read "not live" on a fleet
  where the consumer runs fine. **Check 2 — the module import — is the only one of the three
  that discriminates.**
* **The task row still does not exist.** `human_task_projection` has no `risk_acceptance_medium`
  row at any status. That is correct — nothing has run a safety turn through the gateway since
  the roll. Producing one writes into bob's queue, so it is **Chris's walk**, and the query is in
  the packet ready to re-run.

## And fix D is proven in the field, which nobody had measured

    Predicate  02:08 UTC (mid-roll)    138 rows, ALL would-relocate
    Predicate  02:15 UTC (settled)     133 rows,  89 ALREADY-NAMED + 44 would-relocate
    OntologyClass, same window         unchanged at 25,255 / 16 / 968

Engines re-registered at startup and the fixed writer put the rows straight into the named
space. `OntologyClass` not moving is the control — doc-tools has not rolled its half. **Fix D had
only ever been shown in scratch collections.**

## Commits added after the body above

    657bd95  fix(backfill): the identity is the expectation, and the apply is bracketed by dry runs

The architect ruled the partition identity — not tonight's counts — to be the script's
expectation, and ruled the apply bracketed by dry runs with a non-zero second reading treated as
a FINDING, not a retry. Both are in the banner. `partition_ok` now checks the identity, **and
writing its control caught it being wrong before it shipped**: the first version would have
fired on every `--offset` run, because that branch advances `seen` without recording an outcome.
A guard whose first firing is a false alarm on a documented flag teaches people to ignore it.

## Placed outside this repo, for others to commit

    ia-01/sessions/2026-09-19-packet-from-74-the-consumer-is-live-and-the-pod-is-engine-a.md
    doc-tools/sessions/2026-09-19-packet-from-74-the-weaviate-leg-has-no-blank-node-filter.md

## OVERNIGHT — the four-item order, and the row is still absent AFTER a real walk

**1. THE TASK ROW IS ABSENT, AND THE CONTROL SAYS THAT IS NOW A FINDING.** Lane 1's post-roll
census HAS saved (`6ad77f3` on `lane/01`), so the precondition is met — I checked that before
reporting an absence, because an absence measured before the census would have been worthless.

    human_task_projection, 03:05 UTC   59 rows, ZERO `risk_acceptance%` at any status
    the census's own row               safety-haz-1003-risk-assessment
                                       disposition 'drawn', wants 'task_requested'

The turn ran, drew a card, and asked for nothing. **I can narrow where it stops, which the
census cannot see:** in cortex-bff's log at the rolled sha, the pod DID serve the turn (8 lines
naming `census-safety-haz-1003-...` artifacts, in 3506 lines — that is the positive control),
and **neither** the dispatch success line **nor** the consumer failure record appears. So at
`gateway.py:6005-6006` the guard **never entered** — `_expert` or `_rr` was falsy — rather than a
dispatch being attempted and failing. engine-safety still emits `review_request` for HAZ-1003 on
the rolled image (called directly on port 8099, bypassing the gateway, so no task opened).
**Which of the two is falsy I did NOT measure**; `_expert` also lands in the artifact as
`expert_response` (`:6074`), so one read of a census artifact settles it.

**2. `--list-walked` BUILT AND BOTH LISTINGS COMMITTED.** uuid/outcome/uri, sorted by uuid, with
a self-describing header. Dry runs at 03:10-03:11 UTC:
`predicate-walked` 133 = 89 already-named + 44 would-relocate; `ontologyclass-walked` 26,239 =
25,255 + 16 + 968. Both tally exactly, both sorted, both LF-only.

**3. THE RUNBOOK IS `docs/runbooks/backfilling-the-vector-space.md`**, indexed in the runbooks
README (that README already records a runbook the index did not admit to — I was not going to be
the second). Every command in it was RUN tonight before it was written down. The corpus needed
regenerating after it, in its own commit, because the page stamp derives from the commit.

**TWO INSTRUMENT FAILURES ON THE WAY, AND THEY ARE THE SAME SHAPE AS EACH OTHER.** The first
`--list-walked` run *appeared to succeed and wrote nothing*: Git Bash rewrote the pod path
`/tmp/x.txt` into a Windows path, the script raised `FileNotFoundError`, **and my own grep
filtered the traceback out** — I had grepped for success markers, so the only tell was a line
that did not appear. Then `grep -c` for carriage returns reported every line as having one both
BEFORE and AFTER stripping them; settled with `tr -dc` plus a positive control on a file known to
contain them (0 bytes here, 2 in the control). **Twice in one hour I read a matcher's output as
a measurement without a control on the matcher.**

## LANE 1'S CORRECTION LANDS ON NEITHER SCRIPT — checked, not assumed

Lane 1's packet says `backfill_vector_space.retrievable()` uses the `rows[0]` form and that the
per-batch verification could stop on a correctly repaired row. **There is no `retrievable()` in
my script.** Mine is `verify_self` (`:308`), it enumerates the page for self, and the only three
`rows[0]` occurrences across my two files are docstrings saying *not* to use it — on
`origin/master` too, so no checkout gets a different script. **`retrievable()` is THEIR function**
(`retrievability_census.py:103`) **and it is also correct** — it uses `rows[0]` only to name the
twin in a note, never as the pass condition, and credits my `verify_self` in its docstring.

**I changed nothing in response**, which is the point of replying rather than quietly "fixing"
working code. Correction packet placed in ia-01.

**Their five-row measurement is real and it is an upgrade to the record:** twins embedding within
~1.8e-07 with the tie breaking toward the twin is exactly what the top-k ruling was written
against, and until their run that rule was defended by a two-row fixture I made by hand. **A rule
defended by a fixture is now defended by live data.**

## THE 138 uuids: I DID NOT SAVE THEM, and the defect was already written down

Asked to name the five `Predicate` rows that went across the roll. **I cannot: I saved the counts
and never the identities.** The listing ran under `head -20`, so 119 of the 138 never existed
outside the pod's stdout. Checked rather than recalled — no scratchpad file holds a uuid.

**My own handoff had already named the remedy** ("the next run should capture the uri list") and
I then took the count twice more without saving one. A note in a file is not a change to the next
command.

**What survives is an accident of `head`:** a SORTED listing cut at 20 is a complete enumeration
of a bounded range, not 19 scattered samples. Re-measured after the roll, the 19 uuids at or
below `1a5adb7b-d126-5ae8-9dba-d764bdaef979` are **identical and identically ordered**, so
**all five deletions sort above that bound** — 119 → 114 above it, which is the whole delta. That
rules out 19 rows with certainty and narrows Lane 1's search to 114.

I compared by RANGE, typing only the bound. Re-keying nineteen uuids out of a transcript is how a
transcription slip becomes a "deleted row" that was never deleted.

**The −5 is NET and I cannot separate deletions from additions.** Packet placed:
`ia-01/sessions/2026-09-19-packet-from-74-the-138-uuids-were-not-saved-and-what-i-do-have.md`.

**The cheap fix, flagged and NOT built** (item 3 is "nothing else", instruments are held):
`backfill_vector_space.py` has `--list-no-vector FILE` but nothing that lists every row it
walked — the artifact that would have answered this for free on either run.

## THE TASK ROW: still absent, and the walk has not happened

At 02:30 UTC: `human_task_projection` has **no `risk_acceptance%` row at any status**, 59 rows
total — unchanged from the pre-roll tally. Correct reading: **Chris has not walked safety step 2
as bob yet.** Ruled: I do **not** produce a dispatch. Re-run the query after the walk; **no row
after a real walk is the finding.**

## THE SIXTEEN: my guess is refuted, and the vectorless set is NOT scattered

7f replied within the hour (`doc-tools` `dada9cf`), confirmed the read in every particular, fixed
the Weaviate leg (`a8e2b3e`) and **refuted my §3 guess by doing the read I said was theirs.**

> I guessed the sixteen are vectorless because they are text-less. **They opened `embed.py`: it
> is impossible.** `DOCUMENT_PREFIX` (`"search_document: "`) is always prepended so the payload
> is never empty, and the caller never passes empty text — `safe_label` falls back to the URI
> fragment, so `BFO_0000002` embeds as `"BFO 0000002"`. There is no path to an empty input.

They offered two candidates, both labelled unmeasured: (1) a transient embed failure at write
time, (2) a uuid5 collision from `IOF_Core` being manifested twice. **I measured what I could
reach and it bears on both:**

    source_ontology on all 984 NAMED rows        absent — the field is '?' on every one of them,
                                                 so 7f's candidate 2 CANNOT be tested that way
    BFO rows in the whole index                  11 total   (9 MAINTENANCE, 2 SUSTAINMENT)
    IOF Core rows in the whole index              2 total   (both MAINTENANCE)
    of those 13 rows, VECTORLESS                 12

**That is the finding: the vectorless set is not sixteen scattered rows, it is essentially TWO
ENTIRE UPPER-ONTOLOGY NAMESPACES.** Twelve of the thirteen BFO/IOF-Core rows in the index carry
no vector. **A gateway hiccup during one ingest does not select a namespace** — candidate 1 gets
much weaker, and whatever did this is systematic about how those rows were written.

**And `IOF_Core` IS manifested twice**, confirmed in my own tree —
`setup/prime_databases.py:174` (`IOF_Core`, `maintenance/IOF_Core.rdf`) and `:229`
(`IOF_Core_sustainment`, `sustainment/IOF_Core.rdf`). With one `generate_uuid5(uri)` row per URI,
two entries writing the same class collapse to one row. **BFO classes appearing under BOTH
domains from a population of only 11 rows is the signature of two entries writing them**, and
the surviving row records whichever wrote last.

**NOT MEASURED, and I stopped here deliberately:** that the second write is what clears the
vector. That needs the Dagster run logs or the MinIO objects, it is doc-tools' code, and the
architect's standing order is to report rather than chase. **Routing this is the architect's.**

**The ia-01 packet's `to:` line was REJECTED by the inbox grammar on my first write** — I used
doc-tools' `worktree :: branch` header, which this repo's `_TO` regex does not match. Caught by
running `lane_packets.scan` against the file instead of trusting the format. Third time this seal
has caught this lane; the grammar is `to: ia-<lane>/lane/<lane>` and nothing else on the line.

— 74, session ref `[bd26bdc1]`
