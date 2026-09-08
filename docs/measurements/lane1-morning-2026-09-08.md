# Lane 1 — morning list, 2026-09-08

Written overnight, ordered by what needs a human rather than by size.

## 1. NEEDS YOU FIRST — seven engines are serving UNREGISTERED, and I caused it

`helm upgrade` to revision 102 (the Dagster CPU sizing, mine) restarted the release. Seven
engines came up in an eleven-second window; Keycloak came up 47–58 seconds later. Registration
is startup-only with a bounded retry, so all seven exhausted their attempts against a Keycloak
that was not answering, and none retried.

**engine-cost, engine-d, engine-e, engine-fin, engine-p, engine-w, data-analyst.**

`invincible-agent-91` found it on engine-cost and said plainly it had sampled rather than
swept. The census over all 39 running pods found seven; six of them nobody had looked at.

**Routing still works** — proven, not assumed: a pick reached engine-p at 03:28, four hours
into this state, and returned an answer. The Neo4j compat-walk holds the earlier registration.
What is lost is any registration **change** since 23:16Z — a new verb, a changed endpoint, a
changed slot declaration — **per engine, and it must be checked rather than assumed.**
`invincible-agent-91` queried Neo4j properly (a registration is a relationship carrying
`endpoint_url`, not a node) and found **all nine cost verbs registered right now**; that
lane's loss set is empty. I had written that this outage blocked `cost:PriceComposition`.
It does not — the blocker is `mesh:StepLadder` and `mesh:NamedHole`, declared and unprimed.

**A roll of the seven fixes it.** Not done: your freeze, seven deployments is not a
lane-owned component, and no peer — including me as coordinator — can grant that.

Full write-up, including the evidence that a roll would discard:
`docs/measurements/unregistered-fleet-2026-09-08.md`.

**The durable question is not the roll.** Registration is startup-only against a dependency
with no ordering guarantee, so the same race recurs on every full-release upgrade and its tell
is silence. My recommendation: **a readiness probe that fails while UNREGISTERED**. That would
have made last night a red pod instead of a four-hour quiet. Ordering is cheapest and weakest.

### If you test archetypes this morning, read this line first

From `cortex-ui-60`, and it will save an hour. `NAMED_HOLE`, `WithheldPanel` and `StepLadder`
were declared in the TTL last night, and `ELICITATION`, `NAMED_HOLE` and `STEP_LADDER` are
frontend capability rows cortex posts at page load. **Every one is a registration *change*
since 23:16Z** — exactly the class this outage loses while existing verbs keep routing.

So an ask, a hole or a build-up will render as a plausible `KNOWLEDGE_DOCUMENT`, which by eye
is **indistinguishable** from the archetype never having registered — the bug cortex spent
yesterday afternoon fixing. The natural wrong conclusion is "cortex's rows didn't land again."

The discriminator is one console line that already exists (`App.tsx`):

```
[ADR-0017] frontend capabilities — sent: N accepted: N for cortex-ui-desktop [names]
```

- `accepted` < `sent`, or a name present there and absent from the graph → **the outage.**
  Nothing for cortex to fix, and re-registering will not help until the roll.
- a row missing from `sent` entirely → **cortex's.**

That line prints names beside both counts precisely because a bare count read as correct
through a rejection once before.

## 2. Landed overnight

| | |
|---|---|
| `023ba49` | `/route_intent` was a fourth model call, running *before* the skip could stop it — gateway 5.4s → 0.29s on a pick |
| `127b397` | `forkserver` + preload — step spawn 5–7s → 2s, and it kept the ask's parallelism, so `in_process_executor` is unnecessary rather than interim |
| `af1cdd6` | the projector read four properties nothing wrote, twice a second, for months |
| *(pending)* | `classify_called` recorded rather than inferred; `verb_eligibility` extracted for the direct path |

**Measured result: a pick is 24s, from ~5 minutes yesterday morning.** Gateway 0.26s, Dagster
launch 8.4s, run 13.1s, write+dispatch 1.5s.

## 3. The direct path — speced, started, needs no decision

Of that 24s, **about 1 second is work**. The launch gap alone is 8.4s before an op runs.
Bypassing Dagster removes ~21.5s and leaves a **~3s floor** (gateway + engine + write +
projection), which is the corrected target — my earlier "9s outside" double-counted the launch.

Started: `filter_verbs_by_arity` and `predicate_from_compat_record` extracted to
`iagent_pure.verb_eligibility`, so the BFF calls the same two rules rather than a second copy.
Next: `_find_compatible_verbs` (it takes a Dagster context only to log what it already
returns), then the BFF dispatch itself.

Contract, unchanged from the ruling: verifier and `/find_compatible_verbs` in front, same
writer with `derived_from`, routing record still captured for the HUD,
`assert_every_engine_answered` folded inline, `force_poll` after the write. Seal is
byte-equality against a run-produced artifact, with the one-option menu and the
`needs_instance` single-asset case in the set.

## 4. Multi-valued `derived_from` — mine, and cortex has already made its side safe

ADR-0050 §6.2 needs one child, **N** parents (one per panel). Today the field is
`Optional[str]` and the projector takes `[0]`, so a canvas artifact would record one panel,
drop the rest, and look fine — one parent is a valid answer to a query for one parent.

This is **not** the edge that started working yesterday; that one is one-child-one-parent,
which singular supports correctly. The fold is unaffected either way.

`cortex-ui-60` found that all four of their readers treated the field as a scalar, so landing
the array would have silently stopped the fold — no throw, every fixture green. They fixed it
first (`38fb22c`); the type now admits `string | string[] | null`, so I can land the edge
without coordinating the hour.

Two design points taken from them, both better than my own plan:
- **`askParentOf` replaces "the parent".** With N parents only one is the answered question;
  the rest are panels. Reading `[0]` is a coin flip on edge order that passes today and picks
  a panel tomorrow. Ask for the ask **by name**.
- **Assert the arity, not membership.** A writer storing two and a projector returning one
  gives a valid-looking single parent. `"q1" in parents` passes; `len(parents) == 2` does not.

## 5. Carried from other lanes — need you, not me

- **`invincible-agent-91`:** the three prime declarations all resolve (SPARQL against running
  Fuseki, not a grep). `mesh:StepLadder` and `mesh:NamedHole` are declared and do **not**
  resolve — committed after the prime ran. Three items for the next prime, not one.
  Also: `cost_price_composition` **should refuse** — six draw, that one refuses by design, and
  a record scoring it as a miss will be wrong.
- **`invincible-agent-32`:** Engine B is retired, not stalled — my dispatch asked where it
  stood and was two days stale. Their removal-list seal immediately proved the list was blind:
  eleven hand-written entries against sixteen tracked references, and the two missed ones were
  CI still **building the retired engine's image on every run** and docker-compose still
  standing it up. **Unassigned, deliberately:** dropping the langgraph-support row from the CI
  build matrix. One commit, no deploy — left because CI is shared and three lanes were pushing.
- **`cortex-ui-60`:** templated canvases already have a ratified spec (ADR-0050); my dispatch
  said they had none. They correctly did **not** prototype against a ratified ADR. Two asks
  for you: a second ratified template (§9.2 decides the registry question on evidence and
  there is one row), and whether "no adoption by existing canvases" is intended or merely
  unstated.
- **`invincible-agent-94`:** declined `slot_declarations` as outside their lane, and measured
  it anyway. **375 non-comment lines, not 86**, and seven engine-unique functions, not six.
  My premise was wrong: F and P agree down to the docstrings, so it is **one** divergent
  implementation (C), not a three-way fork — a materially smaller job.

## 6. Still carried, unchanged

- **Every timeout in the repo was calibrated on quartered hardware** — the 75m helm guard, the
  60m `ingestTimeout`, the arm64 probe timings, the 30s `/resolve`. Measure the next real
  prime, then re-derive from it. Not from reasoning.
- **`K8sRunLauncher`** after picks are off the run path, or it regresses the click (pod
  creation is 10–30s).
- **`frontend_capabilities_graph_registration_failed`** — the client reports 32 of 32 accepted
  while the gateway rejects two manifests. Advertised-unconsumed; mine.

## 7. Method note

Five instrument failures across four lanes yesterday, all one family: **measure a sample,
speak about the population.** Mine were `head -10` on a ranked list, `tail -3` on a
string-sorted release list, `grep -m1` on an eight-core big.LITTLE SoC, and benchmarking nodes
through pods with different cgroup quotas. 32's was a hand-written list of eleven against
sixteen. 91's was an ASK helper reading `results.bindings` so every probe silently read NO —
caught by the *uniform negative column*. 94's found a real file that was the wrong file,
because grepping a concept's **name** finds what mentions it, not what implements it.

Three of the four causes behind yesterday's slowness were environment configuration — a CPU
limit, an affinity mask, a logger level — and the suite was green through every one of them.
It was green at five minutes per click and it is green at twenty-four seconds.
