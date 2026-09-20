# Handoff — Lane 1, 2026-09-19 evening

to: ia-01/lane/01

**Read this before touching anything. It states what is true, what is in flight, and the one
next step.**

## STATE

    base sha        lane/01 at the merge below; master was 9843f6f when I merged it in
    SDK pin         iagent-mesh v0.9.3  (sha b6d597f) — 17 pyprojects, 18 locks, broker, chart 0.4.4
    fleet           rolled at 91d8d34, hooks complete (prime 15m, ontology-seed, engine-reregister)
                    42/42 Running. Census reports fleet=MIXED(91d8d34,d3ca169) — doc-tools is
                    pinned separately and that is not a fault.
    census          17 rows over FOUR sheets: 5 cost, 8 finance, 3 safety, 1 docs.
                    Last full run (fleet 91d8d34): 4 pass, 4 fail, 2 blocked.

**THE SUITE IS RED AND IT IS NOT THIS LANE'S.** Five planning seals fail:

    tests/planning/test_archetype_registries_agree.py
    tests/planning/test_bindings_point_at_archetypes.py
    tests/planning/test_planning_classes_are_declared.py   (three arms)

    archetype(s) a component contract declares but capability_admission does not know:
    ['SOURCE_LEDGER']
    binding object_uri(s) with no owl:Class in any SEEDED ttl: ['mesh:SourceLedger']

These read `_ROOT.parent/"cortex-ui"`, a SIBLING REPO. cortex-ui landed `SOURCE_LEDGER`; the
backend half is held on `lane/32` (`feat(site-4): … HELD ON THE LANE, the mirror half is
cortex-ui's`). **Master is equally red for anyone with cortex-ui checked out** — the inputs are
outside this repo, so no commit here caused it and none here fixes it. Do not chase it as a
regression; it is a cross-repo mirror mid-transition. **Do not merge lane/32 to fix it without
reading `sessions/2026-09-19-dispatch-32-…` first** (it used to carry the packaged-only import;
32 has since landed the better fix on master, so re-check before assuming either way).

## WHAT IS IN FLIGHT

* **Cause 1 — MINE, NOT STARTED.** Add the `iof_mro.ttl` manifest row so
  `mro:MaintenanceWorkOrder` seeds, which unblocks `assess_deferral_risk`'s Contract D
  registration. **Same commit:** the parity seal that the fallback loads what the manifest
  primes, so the next file added to one side reds. Do NOT mint a house synonym to pass the
  registration — ADR-0007's survey-before-mint settles it and the citation is the point.
* **Cause 2 — doc-tools/7f, NOT YET DISPATCHED.** Two rulings: the Weaviate dual-write failure
  must FAIL the asset (a partial ingest reported as success is the failure the class-system
  exists to refuse), and the derived seal — every class a manifest TTL declares is a row in the
  Weaviate collection, derived from the manifest, run after ingest — belongs in doc-tools. The
  readiness sentinel becomes per-domain: one class per manifest entry, or it is a store liveness
  check wearing an ingest check's name.
* **Cause 3 — MINE, NOT STARTED.** `review_request` is emitted unconditionally since 09-12 and
  has NO CONSUMER in this repo (R-076). The consumer to build: read the review request off the
  draft's artifact, run `safety_acceptance_selection` on its `level`, dispatch the selected
  definition. That is what puts a task in bob's queue and it has never existed.
* **The pool leg — MINE, NOT STARTED, and it wants one roll with 5f's half.** 5f declared
  `mesh:Thing` + `mesh:universalReferent` at `f16e2cd` on lane/5f. My leg: the parameterisation
  admits a verb whose referent carries the FLAG — read the flag, never the IRI — skipping the
  class-chain coverage check for that referent only. Three seals belong with my leg (none can
  pass until the pool reads the flag): `explain` enters the pool for a Column, a Hazard and a
  Program question; **a verb with an ordinary referent still scopes** (the control that matters —
  a flag implemented as "skip the check" rather than "skip it for this referent" widens every
  verb and all the positive arms still pass); and the answer's subject stays what was asked
  about. `owl:Thing` is NOT available — 0 OntologyClass nodes, measured by 5f; my 2026-09-18
  dispatch telling them to use it was wrong and is to be corrected by APPEND when the leg lands.
* **The hybrid-vs-bm25 census line** — ruled and never built. Second time today a retrieval-mode
  question cost a diagnosis. The census is its home.

## THE OPEN QUESTION, WITH EVERYTHING RULED OUT

`find_orphaned_hazards` is REGISTERED and routes nowhere. For its own declared phrasing:

    subject: product#Part 0.2 · candidates: 1 (product#Part 0.300) · excluded: 0 · no_compatible_verbs

Ruled out, each with a positive control in the same query:

    index        safety#Hazard present, domain SUSTAINMENT, 768-dim vector (control product#Part identical)
    ontology     4 triples, ASK a-Class True, label+comment+example — better described than the winner
    Topaz        ENABLE_AGENTIC_AUTH=false on engine-o — the pre-BAML gate is a no-op
    retrieval    LLM_EMBED_MODEL declared; "falling back to BM25" 0 hits in 3000 lines,
                 matcher positive-controlled at 141 "resolve" hits

**Next measurement:** the pool size AT THE SEAM — what `weaviate_hybrid_search` returns before
anything downstream trims it. That separates "the search returned one" from "the search returned
ten and something kept one". One instrumented call. It is 74's, and the appended correction on
their dispatch says so.

## EXACT NEXT STEP

**Commit and push what is in this worktree, then take Cause 1.** The tree holds the merge of
`origin/master` (32's host swap onto the SDK) plus one comment repair: the merge left MY
description of a flat/packaged try/except sitting above the import that replaced it — a stale
claim from a textual merge with no conflict. `tests/graph_host`: 75 passed, 10 skipped.

Then Cause 1 in one commit: the `iof_mro.ttl` manifest row + the parity seal.

## THINGS THAT WILL BITE YOU

* **Port-forwards die across every roll.** bff and keycloak both. A dead forward and an empty
  answer are identical at the call site; the census reports UNREACHABLE separately for that.
* **Never type a sha.** `$(git rev-parse <ref>)`. I wrote a 40-char sha from a 7-char prefix
  today; the first seven matched and `upgrade-sandbox.sh` refused it. Its message is the lesson.
* **Never route by a bare session name.** Two live sessions share `invincible-agent-28`. Route by
  the lane-addressed inbox; confirm with `git branch --contains` and `git worktree list`.
* **The citation seal now has THREE states** — PHANTOM / PENDING / ROT. A sheet on an unmerged
  branch prints PENDING with the branch and its age, and is not red.
* **A control must be in the SAME query as its subject.** A 60-row page against `limit: 60` reads
  exactly like a complete answer; the control caught it and a separate control would not have.

Lane: ia-01/lane/01
