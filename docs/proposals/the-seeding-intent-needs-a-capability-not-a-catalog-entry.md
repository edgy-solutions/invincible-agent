# The seeding intent needs a CAPABILITY, not a catalog entry

**Correction to the dispatched diagnosis.** The dispatch said: "make the dispatcher honor
`action_endpoint`." Traced end to end, **that is the wrong mechanism, and no new dispatch branch
is needed.** The finding is smaller and better than it looked — and its blocker is elsewhere.

## The dispatcher is ALREADY generic over the endpoint

`src/iagent/defs/dynamic_supervisor.py`:

    endpoint = predicate["endpoint"]          # line 1500
    ...
    response = requests.post(endpoint, json=payload, ...)   # line ~1684

It POSTs to whatever endpoint the **registered capability** declares. There is no Engine-P
special-casing, no `/measure/` assumption. A capability whose `endpoint_url` is a BFF route
would be dispatched to correctly **today, with no supervisor change at all.**

So "some intents resolve to a BFF orchestration rather than a measure" is already true of the
dispatcher. It only ever knew endpoints.

## What `action_endpoint` actually is: a fifth declared-but-unwired instance, and it is mine

    intent_catalog.yaml  read by 6 TEST files, ZERO production files
    action_endpoint      ZERO hits across agent_fleet/ and src/

I added that field. It is inert, and it was never going to be read, because **the endpoint the
dispatcher uses comes from the mesh registration — not the catalog.** The catalog is an
eval-harness artifact that describes intents; the graph is what routes them.

**The commit message was right about the design and wrong about the system.** `feat(catalog):
the seeding intent routes — no phrase skips the funnel` states the intended property correctly,
and the routing half does not exist. That is not a false claim about intent; it is a claim about
a system that had not been assembled — the same shape as every other declared-but-unwired
instance this week, now in its fifth costume, and this one is mine. Anyone reading a green
commit against a red HUD should read this paragraph, not re-derive it.

## The HUD was right, and it earned its keep

`NO_VERB_CLASSIFIED` with `Portfolio` resolved at 0.96 and the compat-walk visibly finding
nothing that fits is **exactly correct behaviour**: the subject resolved, the walk ran, no
registered verb matched, and the system declined to guess rather than dispatching to the nearest
plausible thing. The diagnosis fell out of it in minutes. Honest refusal paying for itself
during its own bring-up.

## What the fix actually requires — and the blocker is NOT in this lane

Registering a capability means a `RegistrationManifest` entry, and **Contract D validates that
`output_uri` resolves to an `:OntologyClass` in Neo4j.** It rejects ATOMICALLY: when
`mesh#DecisionArtifact` was missing, all fourteen of Engine P's verbs were refused together, and
the engine kept serving while none of its verbs routed.

The seeding intent returns slot-ordered artifact ids. **There is no mesh class for that today.**
So the chain is:

1. **A new output class in `mesh_system.ttl`** — Lane 1's file. Something like
   `mesh:CanvasSeedResult`, under `mesh:Archetype` per the convention `mesh:ShortfallGrid`
   established (see `planning-archetypes-still-hang-off-mesh-Response.md`).
2. **A prime** to land it — `fold-not-hand-run`; the class and its verification sit ~50 minutes
   apart.
3. **A registrant.** cortex-bff registers NOTHING today; only `agent_fleet/*` engines call
   `register_engine_to_mesh`. Making the BFF a mesh registrant is a new architectural role and
   deserves a ruling, not an improvisation at the end of a build. The alternative — Engine P
   declaring a verb it does not serve, pointing at the BFF — is worse: it puts the declaration
   and the implementation in different services with nothing holding them equal.

**Then, and only then, `action_endpoint` should be DELETED from the catalog**, because the
endpoint will live in the registration where the dispatcher already reads it. Leaving both is
how the two drift and the wrong one wins.

## Two halves, two lanes, one acceptance

The registration half (above) and cortex's call site are one feature.
`seedPortfolioCanvasFromServer()` exists in `src/lib/seedPortfolioCanvas.ts` and **nothing calls
it**, so there is currently no way to trigger a seed from the browser at all — by phrase or by
button.

> Neither half alone produces a working phrase. The acceptance test is the phrase working end to
> end, not either half passing its own tests — which is the cheapest way to keep this from
> becoming the sixth declared-but-unwired instance.

## What works today, so nobody re-verifies it

`POST /canvas/seed` is live, auth-gated, and **measured 5/5** (1049s), returning slot-ordered
ids whose artifacts carry the right archetype per slot:

| slot | archetype | rows |
|---|---|---|
| 0 | INTERVAL_TIMELINE | 14 |
| 1 | PERIOD_SERIES | 8 |
| 2 | THRESHOLD_GRID | 6 |
| 3 | SHORTFALL_GRID | 11 |
| 4 | MATRIX_GRID | 8 |

The endpoint is proven. Only the phrase→capability hop is missing.
