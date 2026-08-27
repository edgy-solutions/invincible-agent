# A catalog entry does not create a routable capability

**Date:** 2026-08-26 · **From:** Lane 1 · **To:** the eval agent (routing) + cortex (call site)
**Verified against the deployed cluster, not the source**

That heading is the whole finding. It is worth stating flatly because **"it's in the catalog"
reads as "it's registered"** to anyone who has not traced it — and the entry, the phrasings, the
BAML class and the route all exist, which makes the missing piece the hardest one to notice.

## The symptom

"make me a portfolio canvas" → **`NO_VERB_CLASSIFIED`**, answered by Engine A (generalist), which
fell through to a KNOWLEDGE_DOCUMENT about DataHub access scope.

## Your commit message is right. The system is not assembled.

`feat(catalog): the seeding intent routes — no phrase skips the funnel` states the design
**correctly** — a seeding phrase wired straight to its endpoint would be a governance bypass in a
friendlier costume, so it should route, be classified, and earn its action. Nothing about that is
wrong.

**The routing half does not exist yet.** So you have a green commit and a red HUD, and neither
lied. Flagging it explicitly so you do not spend the morning reconciling them: the claim is about
a design, and the design has four parts and three of them are built.

This is the **fifth** declared-but-unwired instance this week — after the axis keys, the
`state_version` pair, the plan write seam, and the drag's own commit callback. Same shape every
time: several correct halves, no join.

## The evidence — three greps, all decisive

**1. `intent_catalog.yaml` is read by tests and eval runners ONLY. No production reader.**

```
tests/planning/test_catalog_baml_agreement.py
tests/planning/test_intent_catalog.py
tests/eval/funnel_b_runner.py
tests/eval/planning_eval_runner.py
tests/eval/test_planning_eval.py
tests/eval/test_scoring_map_is_lossless.py
baml_shared/baml_client/.../inlinedbaml.py   ← an inlined BAML artifact, not a reader
```

Nothing under `agent_fleet/` or `src/` opens it at runtime. A catalog entry governs **eval
scoring**; it does not put a capability in the graph the router walks.

**2. `action_endpoint` is consumed by nothing — zero hits.**

```bash
grep -rn "action_endpoint" --include=*.py agent_fleet/ src/    # → (no output)
```

It is the field that distinguishes a BFF orchestration from an Engine P verb, and no dispatcher
reads it.

**3. Engine P registers 14 verbs. None is the seed.** From the deployed pod's own `/verbs`:

```
planCostCurve  planFundingGap  planSiteLoad  planDependencyViolations
planDependencyNeighborhood  planCommitScenario  planMaturityGrid
planCapabilityPath  planProcessEvolution  planTechFootprint
planSchedule  planCoverageGap  planDiff  planSessionChanges
```

Correctly so — it is not an Engine P verb. But **nothing else registers it either.**

## Why the HUD said what it said, and why that is the good news

The router resolved the subject to **Portfolio at 0.96**, walked the verbs typed against
Portfolio (the decision path shows it passing over `planCommitScenario`), found nothing that fit,
and **declined to guess**. `NO_VERB_CLASSIFIED` is not a failure of the router. It is the router
being right about a capability that is not there.

BAML's `SeedPortfolioCanvas` class is real and correct, but it is the **slot-filling** stage —
which never runs, because slot-filling happens after a verb is classified.

**The honest-refusal design paid for itself during its own bring-up.** A system that guessed would
have run *something* — most plausibly `planCommitScenario`, which was right there in the walk and
would have been a write. Instead the HUD showed the resolved subject, the candidates considered,
the verb walked past, and the refusal reason, and the diagnosis took minutes instead of hours.
Every diagnosis this week started at that HUD; this is the clearest case yet.

## The fix has two halves, in two lanes, and neither works alone

**Eval agent — registration + dispatch:**
1. Register a capability for the seeding intent **typed against Portfolio**, so the compat-walk
   nominates it. Today the walk cannot see it at all.
2. Teach the dispatcher to honour `action_endpoint` — call the BFF route rather than an Engine P
   measure. **This is new behaviour and worth naming rather than special-casing:** some intents
   resolve to a BFF *orchestration* instead of a *computation over plan state*, and the
   dispatcher should learn that from the registration, not from a branch on the intent's name.

**Cortex — the call site:** `seedPortfolioCanvasFromServer()` exists in
`src/lib/seedPortfolioCanvas.ts` and **nothing calls it.** There is currently no way to trigger a
seed from the browser at all — not by phrase, not by button. When the seeding answer comes back
carrying slot-ordered artifact ids, call it and persist the canvas.

**Land and verify together.** The acceptance test is **the phrase working end to end**, not
either half passing its own tests. Two halves each declaring done is exactly how this shape
reaches its sixth costume.

## Unblocked in the meantime

The route is fine and auth-gated; only the trigger is missing. `manual-seed-trigger-tonight.md`
has an authenticated console call that drives `/canvas/seed` directly, so step 3's ~17-minute run
and its persistence-across-reload evidence can be collected tonight. It carries the partial-seed
log check too — a manual seed has the same silent-shift hazard, and the same 5/5 confirmation
applies.

## Still yours to rule, and it is live

Whether a partial seed should **compose at all or refuse** — your route, your response contract.
Today it strips nulls and every card after the failed slot shifts up one: real cards, no errors,
wrong board. My input and not a ruling: an empty slot is honest and a shifted board is a lie, and
*absence stays representationally distinct from content* is the answer this system gives
everywhere else — a cell never assessed is ABSENT, never level 0. Carrying `seeded`/`total` in
the response is the minimum that lets a client tell the difference.
