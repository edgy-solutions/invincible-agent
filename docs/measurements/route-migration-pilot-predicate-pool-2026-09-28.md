# Route migration pilot, second route — the predicate search through `WeaviateVectors`

**Date:** 2026-09-28 · **Lane:** `ia-74/lane/74` · **Flag:** `ONTOLOGY_CLASS_POOL_VIA_MESH`, literal
`"false"` when measured · **Seal:** `tests/test_the_migrated_predicate_route_returns_the_same_rows.py`
(52 arms) · **Companion:** `route-migration-pilot-class-pool-2026-09-27.md`

*Correction, 2026-10-01 (Lane 74):* `ONTOLOGY_CLASS_POOL_VIA_MESH` is now DEFAULT ON (literal
`"true"`), flipped after an in-process census of every walk row moved no row (`class-pool-flag-default-on-census-2026-10-01.md`).
Every figure in this file was measured with the literal `"false"`.

The second route moved, behind the same flag as the first. `nominate`'s docstring already said
`domains` is a *sequence* because "both live call sites scope by an entitlement list" — this is the
second of those two call sites finally reaching the shared implementation through the interface
rather than around it.

One route proves a shape fits one caller. Two routes are what turn it into an interface. Nothing here
proposes flipping the default; §6 says what still blocks that.

---

## 1. What moved

`/search_predicates` and `/classify_predicate` share one search, so one fork serves both. The fork is
the async wrapper `predicate_hybrid_search` and nowhere else, which means there is a single place to
read to know which arm served a request, and both routes get the same answer to that question.

| | incumbent | mesh arm |
| --- | --- | --- |
| retrieval | `_predicate_hybrid_search_sync` | `_predicate_pool_via_mesh_sync` → `WeaviateVectors.nominate` |
| projection | `_predicate_row` + `_predicate_ranked` | **the same two functions** |
| identity | none read | `Initiator(subject=user_email, kind="person")` |

## 2. The projection is SHARED, and that moved where the defect can hide

The class pilot duplicated its projection expression-for-expression, so its equality arms compared two
independent expressions. That projection was four keys. This one is **fourteen**, with an anti-synonym
Jaccard penalty, two JSON-string tolerances and a re-rank — two copies would agree exactly as long as
nobody edited one.

Sharing costs what item 3 of the overnight packet measured on this lane: **a defect sitting identically
on both sides of an equality seal is invisible to it**, however many ways the equality is parametrized.
Reverting one arm of the `definition` repair reddened 22 arms; reverting both reddened 4, and the parity
arms stayed silent.

So the shared half is sealed by arms that assert its **values**, not its agreement:

| arm | asserts | result |
| --- | --- | --- |
| penalty arithmetic | `score - alpha × overlap`, alpha read from the module, never restated | both arms |
| floor | a penalised score reaches `0.0` and never goes negative | both arms |
| both serializations | list *and* JSON-string `verb_anti_synonyms` / `verb_synonyms` score identically | both arms |
| broken JSON | an unparseable string degrades to `[]`, no `ValueError` on a routing path | both arms |
| re-rank | the pool comes back in adjusted-score order, not the store's | both arms |
| scoreless row | sorts last, is not dropped, does not raise | both arms |
| bare row | every optional key absent still meets the 14-key contract | both arms |
| no second implementation | the diagnostic key is written once; both arms call `_predicate_row` | derived from source |

## 3. Parity, over the census

| arm | assertion | result |
| --- | --- | --- |
| 20 census questions × flag off/on | pools identical, row for row and key for key | **identical, all 20** |
| filter shape (1 domain, 2 domains, none) | both arms issue the same query | **identical** |
| flag selects a different path | `embed_query` vs `observe_query_embedding` counters | **1/0 and 0/1** |
| embedding fails | degrades to BM25, still answers | **both arms** |
| collection absent | `[]`, and no query issued | **both arms** |
| store answers zero objects | `[]` — a real answer, not a refusal | **both arms** |
| mid-query exception | HTTPException **503** | **both arms** |

The last two are deliberately not collapsed, and on this route the reason is sharper than on the class
route: RULED 2026-09-14, an empty predicate pool means **no predicate matched**, and the supervisor
falls back to the generalist on it. A substrate outage returned as `[]` is therefore a confident
no-match under a false diagnosis.

## 4. Four differences, reported rather than smoothed over

1. **A blank `user_email` is refused by the mesh arm (400) and served by the incumbent.** `nominate`
   refuses a service initiator, and neither request model carried a person before this change. The
   blank is refused rather than minted: `Initiator(subject="", kind="person")` passes the interface's
   check while being exactly what that check exists to stop. `SearchPredicatesRequest.user_id` was
   **not** reused — it is documented as an audit-log slice key that is "null for canary", and an audit
   label borrowed as a provenance claim would make every canary read look like a person's.
2. **The entitlement scope is case-folded on the mesh arm and not on the incumbent — and no caller can
   reach it.** `WeaviateVectors._domain_filter` upper-cases; the incumbent passes `entitled_domains`
   to `contains_any` verbatim. What makes it unreachable is two lines in the *routes*, not anything in
   either search: both `/search_predicates` and `/classify_predicate` normalise before calling. Both
   halves are sealed — the arms differ on a lower-case scope, **and** every call site upper-cases.
   Direction if a route ever drops that line: against an upper-case store the mesh arm matches rows a
   lower-case scope would have missed, which is a scope **widening**, and row identity against a
   scripted store cannot see it because a double ignores the filter it is handed.
3. **`failed` / `unreachable` become a 503, never `[]`** — see §3.
4. **A row owning its own `score` property** is read differently: `nominate` keeps the stored property
   and drops the retrieval score, reporting the collision; the incumbent always reports the retrieval
   score. No `Predicate` row has ever carried that property, so the behaviour is **pinned** by an arm
   rather than aligned by guess — the treatment the class pilot gave a `uri`-less row.

## 5. How this was measured, including what the measurement got wrong

**The extraction was proven a no-op before anything else.** A probe captured 6 cases / 42 rows against
the unmodified engine, positive-controlled so every fixture demonstrably fires (0.80 → 0.55 penalty,
0.05 → 0.00 floor, both serializations, broken JSON, a scoreless row sorting last, a verbatim
lower-case filter). After the extraction the normalised dump hashed **`b07eb7904b61ff7d` on both
sides**, with a control that mutated one score reported as DIFFERENT as required.

**17 subject mutants, 17 killed by a named arm** — each requiring the *expected* arm among the
failures, not merely that something failed, and each restored from bytes read before the run with the
digest re-checked. A nonzero exit was never counted as a kill.

Two things the mutation run found that reading would not have:

* **Four of the seventeen anchors matched twice**, and the second match was never a typo: the class
  pool and the predicate pool are **byte-identical** at the identity refusal, the 503, the metadata
  request and the route's scope normalisation, because the second route was built to the first's
  shape. Mutating "the first match" would have measured the class route's seal while reporting on this
  one. The harness now mutates inside a named function's span.
* **A derivation mutant walked straight through the arm that guards §4.2.** The first draft asked
  whether an upper-casing comprehension appeared anywhere in the calling function; leaving the
  comprehension in place and handing the call `request.entitled_domains` instead of the normalised
  local left **all 52 arms green**. That is not a contrived edit — a normalised local and a raw request
  field, one line apart under similar names — and it is precisely the edit that makes the case-fold
  difference reachable while every other arm reports parity. The arm now follows the *value* handed to
  `entitled_domains=` and, when that is a name, every binding of that name in the function. The mutant
  dies.

**One survivor, recorded rather than chased.** A mutant that adds a three-key stub projection spelling
the diagnostic key as `"anti_synonym" + "_overlap"` survives the no-second-implementation arm. Before
widening the arm: the attack a second implementation actually arrives by is copy-paste, and a
copy-paste carries the fourteen key literals with it. That mutant was built (a genuine duplicate of
`_predicate_row`) and **is killed**. A three-key dict with a concatenated key is not a second
implementation of a fourteen-key projection, so the survivor is a limit of the census string, not a
hole in the claim.

**Consequence run, not an edit-shaped one.** The population is the 30 tracked test files that mention
this route, the flag, the shared implementation or the identity chain, derived by `git grep`, plus the
new seal. Attribution is measured, because master is not green and a pre-existing red looks exactly
like one I caused:

| | red | passed |
| --- | --- | --- |
| HEAD baseline (change stashed, seal parked) | 37 | 336 |
| with the change, first run | 38 | 395 |
| with the change, final bytes | **37 — the same 37 by node id** | 396 |

The one intermediate red was `test_EVERY_CLAIM_about_the_default_agrees_with_the_artifact`: the new
comments name the flag beside the word "defaults" while meaning the *field's* default, which that seal
correctly reads as an undecided claim about the *flag*. Both comments now state `DEFAULT OFF` in the
decided form. Zero new reds, zero fixed, nothing swapped.

## 6. What is still open

* **The flag default is not settled**, and this route does not change that. It is blocked on a gated
  merge, an image build and a roll — not on a measurement.
  *Correction, 2026-10-01 (Lane 74):* at this file's sha the literal was `"false"`. "Not
  settled" meant the decision to flip it was still pending, never that the value was unknown. Lane 1's 09-29 merge census read the sentence as an undecided claim.
* **The flag's name is now narrower than its scope.** `ONTOLOGY_CLASS_POOL_VIA_MESH` gates two pools.
  The order asked for the same flag and the reason holds — one switch rolls both routes back, and one
  switch is what an operator can use under load. The cost is recorded here and not paid unilaterally:
  the variable is set in a deployed values file, so a rename is a change to the chart, not to this
  module. **Routed for the naming decision.**
  *Correction, 2026-10-01 (Lane 74):* no tracked values file sets the variable (`git grep` over the
  tree), and the deployed engine-o carried none when measured
  (`class-pool-flag-default-three-fire-2026-09-27.md` §3). A rename is a code change; the naming
  decision is still routed.
* **`/search_predicates` has no in-repo HTTP caller** — only the route declaration; `cortex-ui`'s
  `src/registry/frontendCapabilities.ts:18` says "Until then". Its 400 blast radius is therefore
  unmeasurable from this repo, and that is a gap in the evidence, not a reason to assume it is zero.
  `/classify_predicate` has one real caller, the supervisor's `_classify_route`, and it is threaded.
* **A HEAD control run of the new seal was not performed**, deliberately: at HEAD
  `predicate_hybrid_search` takes no `user_email`, so the seal would crash rather than red, and a
  crashed run never reached the behaviour. The mutation set is the stronger form of the same evidence.

## 7. Instrument defects found while measuring this

* **`git grep` silently returned zero matches for a leading-slash pattern.** `git grep -F
  "/search_predicates"` found nothing while the same pattern without the slash matched many files:
  MSYS rewrote the pathspec into a Windows path. `MSYS_NO_PATHCONV=1` fixes it, and a positive control
  is what exposed it. Without that control the conclusion on file would read "no tracked file mentions
  this route."
* **`grep -c '\r'` reported carriage returns in a file that has none** — in bash single quotes `\r` is
  a literal `r`. Engine-o's `main.py` is LF-only in the working tree, measured by a byte count.
* **A pytest failure extractor collapsed 38 lines into 25 names**, because parametrized ids contain
  spaces and the splitter cut at the first one. Both logs collapsed identically so the *answer* held,
  but a swap inside one parametrized arm would have been invisible. The diff above is on full node ids.
