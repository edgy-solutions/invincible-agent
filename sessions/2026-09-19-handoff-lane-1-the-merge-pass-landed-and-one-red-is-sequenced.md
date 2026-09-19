# Handoff — Lane 1, 2026-09-19 (the work-order pass)

to: ia-01/lane/01

**Read this before touching anything. The merge pass is DONE and pushed; one red is left standing
on purpose and the next step is a roll.**

## STATE

    master          51db099   PUSHED. Divergence resolved.
    lane/01         cc79af4   pushed; merged into master
    SDK pin         iagent-mesh v0.9.3, venv measured 0.9.3 against pyproject
    environment     `uv sync --extra agent-fleet` — NOT bare `uv sync`, see below
    suite           4378 passed at 36e8eef; then 657 passed / 1 failed on the
                    planning+finance+graph_host gate. The 1 is sequenced, not broken.

## THE MERGE PASS — ALL FIVE ACCOUNTED FOR

Every one merged **by named sha, not branch tip**, so no lane's handoff rode in behind its code.

    lane/91  d84bba5   ALREADY IN MASTER before I started. `branch --contains` said so.
    lane/5f  76706e9   merged (carries f16e2cd — verified ancestor, so both shas land)
    lane/74  f18bc9a   merged
    lane/eo  a46f8b9   merged — hold lifted mid-pass
    lane/32  f9eea84   merged — cortex-60 pushed a271817, so the mirror half exists

## THINGS THAT WILL BITE YOU

* **`uv sync` BARE IS AGENTS.md's HAZARD 2 AND IT COST ME A RUN.** The work order said `uv sync`.
  That form drops the `agent-fleet` extra, and the suite could not even *collect* — 12 errors.
  `docs/rulings/README.md:1703` records `--extra agent-fleet` clearing thirteen identical errors
  previously. **Always `uv sync --extra agent-fleet` in a lane worktree.**
* **A GREEN BELONGS TO AN ENVIRONMENT, AND THE ENVIRONMENT CHANGED UNDER ME.** My 8-failed green
  was measured *before* the sync. Re-run after any sync; do not carry a number across one.
* **The shared master checkout was 1 ahead because a commit COULD NOT BE PUSHED**, not through
  neglect. `72f1111` had no `Lane:` trailer, descends from `b466612`, so the pre-push hook refused
  it. Diagnose a divergence by asking whether the hook would accept it before assuming anyone
  forgot. Amended to `b41bbc5` with `Lane: invincible-agent/master` — true, and a registered
  worktree pair, which is what the seal checks.
* **Another session was working in the doc-tools checkout while I committed there.** Stage by
  NAMED FILE in any checkout you do not own. Never `git add -A` outside your own worktree.
* **A session name is not a seat.** I could not identify the elicitation seat among 16 peers and
  did not guess. The architect's condition ("if it is a session you still have open") did not fire.

## THE ONE RED, AND WHY IT IS RIGHT

`test_every_archetype_cortex_can_draw_has_SOME_projector_path` — SOURCE_LEDGER has no
`_PROJECTED_ARCHETYPES` row. `docs/runbooks/adding-an-archetype.md` lists **six** registries and
sequences the projector row **after** merge → roll → prime → *ask the graph*, because that row
carries the passthrough the card actually reads. Sites 3 and 4 landed in `f9eea84`; I added site 1
(`KNOWN_ARCHETYPES` — the seventh time that door has refused a name the frontend already shipped).
**Site 2 is the roll's, and sites 5/6 follow it.** Adding it now would invent the row's content a
step early.

## THE POOL LEG — NOT SHIPPED, AND NOW ON HOLD FOR A SECOND REASON

**Reason one (mine, confirmed by the architect and by 7f).** The pool is Cypher over Neo4j and
`mesh:universalReferent` did not reach a Neo4j node. A leg reading the flag would have matched
nothing, silently. 7f has since built the carry — property `universal_referent` on
`:OntologyClass`, absent-means-false, `SET null` removes it. **Derive that name, do not type it.**

**Reason two, and it outranks the first: ON HOLD BY THE ARCHITECT. Do not spend a roll on it.**
74 measured that **the vector half of hybrid search is dead on `OntologyClass` and `Predicate`** —
the two collections the router runs on. Every routing answer in the fleet is BM25 alone. The rows
carry vectors in the LEGACY slot; the named space `default`, which is the only thing a search can
target, is empty. `nearObject` on an object's OWN vector errors: *"vector not found for target:
default"*. `DocumentChunk` is the control and works.

**Re-ask the docs walk against a working vector search before building the leg.** `mesh:explain`
"never entering the pool" is the same symptom this produces, on the same broken half.

### MY OWN RULING-OUT WAS A CONTROL THAT COULD NOT FIRE

My earlier handoff ruled retrieval out with: *"falling back to BM25" 0 hits in 3000 lines, matcher
positive-controlled at 141 `resolve` hits.* The matcher was fine. **The message only prints when
`embed_query` RAISES, and it never raises** — the degradation has no log line at all. I controlled
that my grep worked; I never asked whether the string COULD be emitted for this failure mode. A
control must share its subject's gate, and mine shared only its haystack.

### TWO OF THE THREE WRITER SITES ARE IN THIS REPO

    agent_fleet/mesh_registrar/v2_substrate.py:409   Predicate      <- ours
    scripts/seed_sandbox_predicates.py:306           Predicate      <- ours
    doc-tools ontology_assets.py:386                 OntologyClass  <- 7f's

**Measured by me:** both of ours call `collections.create(...)` with `inverted_index_config` and
`properties` and **no vector configuration of any kind**, then write vectors via
`add_object(vector=...)`. That is exactly the shape 74 describes.

**NOT confirmed by me, and I will not claim it:** 74's inferred mechanism — that a bare
`collections.create` on client 4.21.x emits the named `default` space while `add_object(vector=)`
writes the legacy slot. **My lane venv has weaviate-client 4.20.4; the pod ran 4.21.0; doc-tools
has 4.21.3.** Reading 4.20.4's source to explain a collection created by 4.21.0 is reading the
wrong artifact. Settling it needs the version that actually created the collection, or a
create-and-inspect against the server — which is a write to shared state and not a lane's to do
alone. **Confirm the join before choosing between "declare the named space on create and write
into it" and "create on the legacy schema".**

## OPEN, WITH OWNERS

* **`_PROJECTED_ARCHETYPES` row for SOURCE_LEDGER** — the roll (Lane 1), then producer case +
  exemption (sites 5/6).
* **IOF_Core is in `CANONICAL_TTL_MANIFEST` twice** — MAINTENANCE `maintenance/IOF_Core.rdf` and
  SUSTAINMENT `sustainment/IOF_Core.rdf`, **same upstream url**, same class IRIs. Weaviate's row
  uuid is `generate_uuid5(uri)` keyed on the URI alone, so the two partitions write one row and the
  last writer owns `domain`. **The names differ and the s3_keys differ** — a duplicate check on
  either finds nothing; only the url exposes it. Manifest shape is MINE; filed to the architect.
* **The inbox seal has no word for a LANE-LESS SEAT.** Four documents from four authors all wrote
  honest prose addressees the parser cannot read. `to: architect` *would* parse today (measured).
  Not fixed: minting addressee vocabulary for other seats' documents is a contract decision.
* **`review_request` still has no consumer** (R-076). Reassigned to ia-74/lane/74 this pass.

## THE NEXT ROLL — PREPARED, NOT RUN

**Carries:** cortex's image · 74's consumer **with its Dockerfile change** · lane/32's site-4
binding (**already merged, at master `51db099`**). **NOT the pool leg** — on hold.

**THE FRONTEND PINS BY DIGEST. The fleet's retag-by-digest CANNOT reach it, and that is
structural.** `scripts/retag_images_by_digest.py` derives its population from this repo's
`build-containers.yml` matrix — 19 services, `cortex-ui`/`frontend` appear **zero** times — and
hard-codes `PREFIX = "edgy-solutions/invincible-agent"`. `cortexUi.image.repository` is
`edgy-solutions/cortex-ui/frontend`, so in `_helpers.tpl` `$ours` is false, `$floor` becomes
`"latest"`, and with `tag: ""` in both values files **the frontend resolves to `:latest` today**.
The helper's own comment explains the fallback (a cross-repo image cannot use `Chart.Version`,
which only this repo's images are retagged to). The derivation is sound; its **basis excludes a
service the fleet runs**. Filed to the architect.

    pin   sha256:c8d6553f142ebb70024bf09f4b7f93c77c2ad62ebe4e0cc009465461b3824ced   (cortex-ui 8a13dd6)

Measured: resolves in GHCR · multi-arch with **arm64** present (the nodes are arm64, and an
amd64-only image is what once gated `cortexUi` being enabled) · `:latest` is a **different** image
(`81407e58…`), sharing no platform manifest.

**Do not cite cortex-ui's parity green as roll safety.** It is green against producer `cfa3f0d`:
**187 commits behind master**, 2026-09-15, and nobody runs it. The fleet runs `91d8d34` (46
behind). Packet filed to cortex-60 in `cortex-ui/sessions/` naming producer **`51db099`** for them
to run parity against and report **before** the roll.

## THE CENSUS LINE I OWE, AND IT MUST ASSERT RETRIEVABILITY

The hybrid-vs-BM25 census line I ruled and never built is now the fleet's regression check. **It
must assert RETRIEVABILITY, not liveness** — `nearObject(self)` on one row per collection. A
liveness check, and a row-count seal, both pass on today's broken substrate. **Every current
census PASS is a lexical pass.** After the vector fix, run the census and **save its output to a
file** beside `walk-census.yaml`.

## TWO WARNINGS I OWE THE NEXT READER (from 7f, 2026-09-19 evening)

**THE RETRIEVABILITY SEAL WILL RED EVERY ONTOLOGY INGEST until the writer is fixed and the pool
rebuilt. That is correct behaviour, not a new breakage** — an ingest producing unsearchable rows
has not produced a grounding pool. **The first person to see it will read it as a regression
unless they are told, so tell them.** It carries the server's own error and names 74's packet.

**THE RE-SYNC DID NOT HAPPEN, and stopping it was right.** The architect withdrew it mid-pass;
the rebuild is Chris's. 7f had a port-forward open and the real asset ready and stopped — a
by-hand re-sync is the thing Ruling 3 exists because of, and doing it to produce a screenshot for
a handoff is that act with better intentions. The before-measurement stands instead:

    73 mesh# OntologyClass nodes · mesh:Thing ABSENT · ZERO nodes carrying universal_referent

**Confirm with one query after an authorized prime on an image built from lane/7f** — the deployed
image predates the commit:

    MATCH (c:OntologyClass) WHERE c.universal_referent IS NOT NULL
    RETURN c.uri, c.label, c.universal_referent          -- expect exactly ONE row, mesh#Thing

## 74's OPEN QUESTION — MINE, AND IT COMES BEFORE THE POOL LEG

**Does `mesh:explain`'s exclusion from the pool survive a working vector search, or is it the dead
vector half wearing a referent's clothes?** Nobody has measured it. The flag reaches the node
either way so 7f's work is not wasted — but **the universal-referent leg may be answering a
question that does not exist once retrieval works.** Measure this before spending a roll on the
leg. Do not assert either way until someone has.

## A STALE VENV IS NOT A PIN PROBLEM (7f's 7 failures, diagnosed here)

7f flagged 7 `test_collection_marker` failures as possibly mine, from a `v0.9.0 -> v0.9.1` pin
move. **It was neither the pin nor this repo.** `interfaces.py` exists at v0.9.0, v0.9.1, v0.9.2
AND v0.9.3, so that move could not have removed it. Their pin says v0.9.1, whose tree ships 18
modules; their venv ships **11, a strict subset with no extras** — an older build, not a different
one. The 7 absent modules (conformance, declarations, discovery, graph_manifest, interfaces,
results, task_kinds) match their 7 failures exactly. **A version number identifies the DIST, not
which copy of the code ran.** eo's `test_the_imported_sdk_IS_the_pinned_artifact` is the arm that
turns this into one loud failure instead of seven mysterious ImportErrors.

## WHAT IS STILL LANE 1's, UNSTARTED

The roll (cortex image + the projector row + the pool leg when it is real), the walk census run
with its output saved beside `walk-census.yaml`, and numbering today's unlanded rulings — the
register renumber landed (duplicate R-055 → **R-081**, so it really does end at R-081 now), but
the unlanded rulings are still unnumbered and their content is the architect's.

Lane: ia-01/lane/01
