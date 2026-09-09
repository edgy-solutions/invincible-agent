---
id:         canvas-templates-slice-1
status:     in-flight
owner:      unassigned
blocked-on:
closed-by:
code-site:  policy/canvases/portfolio.yaml, src/iagent/canvas_template.py, scripts/generate_canvas_schema.py, .github/workflows/validate-canvas-templates.yml
repo:       invincible-agent
summary:    ADR-0050 slice 1, NON-GATEWAY HALF — landed 2026-09-06 (`a59a9c5`, per git; an earlier revision of this line said 08-23, taken from the session clock rather than the commit). Ratified `policy/canvases/portfolio.yaml` (five panels, verbs read off the seeder's own `measure` field, slots declared as the verbs' REAL signature defaults since §3's carry is blocked), Pydantic models + generated JSON Schema + drift test with positive control, and a merge-gating CI job. Seal 3 recorded FAILING against today's phrase seed — structurally, from source, so it cannot be a lucky pass. GATEWAY HALF IS NOT MINE and is not here: `seedCanvas(template_id)`, `_CALLER_IDENTITY_VERBS`, and the superseded Ruling (a) seal. THREE THINGS OWED, named below rather than implied: verb-EXISTENCE checking (seal 1's other half), the live seal-3 run (~50 min, needs a quiet substrate), and the cortex `TEMPLATES` row §7 requires before the backend advertises a second template.
---

# Canvas templates, slice 1 — the non-gateway half

Decisions live in
[ADR-0050](../adr/ADR-0050-canvas-templates-are-ratified-yaml-a-panel-is-a-pre-resolved-step.md).
This packet is what landed, what did not, and what is owed.

## What landed

| piece | where | note |
|---|---|---|
| the ratified template | `policy/canvases/portfolio.yaml` | five panels, `role` + ordinal only (§7) |
| the models | `src/iagent/canvas_template.py` | pure; `template_ref` per §1.5 |
| the generator | `scripts/generate_canvas_schema.py` | `--check` / `--validate`, help-safe |
| the committed schema | `policy/canvases/canvas_template.schema.json` | generated, self-declaring |
| the drift seal | `tests/test_canvas_schema_drift.py` | 12 tests, positive control first |
| seal 3 | `tests/planning/test_canvas_seed_determinism.py` | structural arm + opt-in live arm |
| the CI job | `.github/workflows/validate-canvas-templates.yml` | `pull_request` — see the departure |

## Seal 3 is recorded as FAILING, and it is recorded structurally

ADR-0050 requires seal 3 to be run against today's seed **and to fail**, because *"a seal that
has never been shown to bite on the thing it was written to catch is decorative."*

**It fails, and the failure is asserted from the seeder's source rather than from one run.** That
is deliberately stronger than a live observation: a single live pass could come back stable by
luck and would then read as the seal passing. Today's `PORTFOLIO_CANVAS_QUESTIONS` declares five
**phrases** and no verb, so each panel's verb is whatever the classifier returned on that run —
the panel set is not merely unstable, it is **not expressible until after the seed completes**.
The seeder's own comment records the instability (*"subject resolution SHIFTS… moved Portfolio
0.86 → Site 0.75 across a single prime"*), and the test asserts that sentence is still there, so
the rationale cannot be quietly deleted out from under the seal.

**The live arm exists and was NOT run tonight.** It is `CANVAS_SEED_LIVE=1`-gated, and the reason
it stayed off is a measurement hazard, not convenience:

* seeding is **sequential by RULING (b)** — ~25 min per seed, so the arm is ~50 min;
* `max_concurrent_runs: 2` plus a reaper gap **deadlocked this queue twice in one day**;
* **a prime was in flight** (`mesh:StatefulSupportResponse`), and a prime *changes subject
  resolution*. Running then would have produced the expected failure **for an unattributable
  reason** — a coincidence wearing a result's clothes, which is the same error class as a
  positive control that passes because it matched the wrong prefix.

Run it on a quiet substrate and paste the two panel sets into this packet.

## The CI job departs from a standing convention, deliberately

`suite-order-independence.yml` is `workflow_dispatch`-only under
[`no-ci-gate-on-the-suite`](no-ci-gate-on-the-suite.md): a never-executed job wired to `push`
burns minutes or goes red for environment reasons and trains people to ignore it.

**This job is wired to `pull_request` anyway**, because §1.3's requirement is specifically
merge-time failure and a dispatch-only job does not deliver it — shipping one and calling §1.3
satisfied would be the decorative seal the ADR is written against. The exemption is narrow: the
job is seconds of hermetic pure Python over ~200 lines of YAML, with no cluster, no database and
no network. **The fallback is pre-committed: one environment-caused red and it demotes to
`workflow_dispatch`.** The standing rule loses to an argument only until it wins on evidence.

## Two corrections the build made to its own inputs

**The generator must not import through the `iagent` package.** `src/iagent/__init__.py` imports
the Dagster definitions, so `from iagent.canvas_template import …` opens Postgres connections and
emits cortex-bff proxy warnings before reaching a Pydantic class — observed on the first run. A
schema is a projection of a type and must not need infrastructure to produce, or the seal only
goes green where infrastructure happens to be reachable. The generator loads the models **by file
path**, and `test_the_generator_is_hermetic` is what stops someone simplifying that back.

**The CI broken-on-purpose fixture violated two rules and was measuring a coincidence.** The
first draft used `_brokenonpurpose` as the `template_id`, which also fails the id pattern — so
the step would have gone red **with the verb check deleted**. Fixed to violate exactly one rule,
and the step now additionally greps for `panels/0/verb` so a failure from any other cause
(missing dependency, moved directory) cannot read as the control working.

## OWED — named, not implied

1. ~~**Verb-EXISTENCE checking.**~~ **CLOSED 2026-09-08** — see *Night of 2026-09-08* below.
   Seal 1's other half now exists as a mesh check and has been RUN.
2. **The live seal-3 run** — still owed, and the blocker changed. See below: it is not a
   scheduling problem, it is a **broken instrument**.
3. **The cortex `TEMPLATES` row.** §7: `CanvasUse` is a closed union with one row, and a second
   `template_id` must be admitted **on both sides, frontend first**. Slice 1 re-expresses the
   existing canvas so nothing new is advertised yet — but slice 2 cannot land before that row
   does, and the ordering trap is already written by name into the archetype registries.
4. **`shared_slots` is empty on purpose.** `program` is §3's worked case and belongs to slice 2,
   gated on the dispatch-boundary slot carry. Declaring one now would fire an ask whose answer
   nothing can bind — a question that costs the user a turn and changes no card.

## The one panel worth reading twice

`plan_funding_gap` declares `group_by: org`. That is the verb's real signature default, and the
phrase it replaces (*"where is funding short by organization"*) was **reworded on 2026-08-28 to
match that default** after the by-initiative wording returned eleven organisations — the verb ran
on its default while the card's question said something else, with no disclosure surface, because
the strip renders routing and not verb params. Declaring it makes the card's parameters legible
instead of true by luck. **Revert to `initiative` only when extraction AND carry both land**; the
acceptance test for that build is this panel returning initiatives.

---

## Night of 2026-09-08 — seal 1 closed from the mesh, seal 3's instrument found broken, second template ratified

### The date correction, and the rule it came from

This packet's summary said *"landed 2026-08-23"*. Git says **`a59a9c5`, 2026-09-06**. The wrong
date came from the session clock rather than the commit, which is the same class as ADR-0046
§8.4's `RULED` line being a day off — and the cost is identical: **a citation naming the wrong
day makes the next search come back empty**, so a real ruling reads as missing. Corrected to what
git says.

Checked, not assumed, against `git show -s --format=%cd`: ADR-0041 (`0bcdead`, 08-17) ✔,
ADR-0043 (`a2c73a5`, 08-22) ✔, composing-levers (`02e0fcf`, 08-23) ✔. And line 102's *"reworded
on 2026-08-28"* is confirmed by `39135c7`, so the one date I was repeating from a code comment
was right — verified rather than trusted.

### Seal 1's other half — CLOSED, and RUN

`tests/planning/test_template_verbs_are_registered.py`. Seal 1 is honestly **two checks in two
places**, and saying so beats pretending one covers both:

| half | where | trigger |
|---|---|---|
| shape (`verb:` is a well-formed IRI) | the schema | merge, hermetic |
| **existence** (an engine actually serves it) | **the mesh** | where the mesh is reachable |

**Eligibility is a CONJUNCTIVE read** — `select-from-authorized-set`'s mechanical form: a verb is
eligible only if it appears in **both** Neo4j and Weaviate. Checking one side would pass exactly
the verb that registers, reports accepted, and never matches. A one-sided presence is its own
named failure here, not folded into "missing", because *"in Neo4j but not Weaviate"* is the
harder fact to diagnose from a symptom.

**Recorded run, live against sandbox on a quiet substrate, 2026-09-08 — all eleven verbs pass:**

* Neo4j: all present as **relationship types** between `OntologyClass` nodes, with the (S,P) edge
  reachable from each panel's declared subject, `provider: engine_p_planning` for the five
  planning verbs. Output types match `measures.py` exactly (`IntervalSchedule`,
  `PeriodCostSeries`, `LoadThresholdGrid`, `FundingGapSet`, `MaturityMatrix`).
* Weaviate: all with `registration_complete: true` and an endpoint resolving to the serving
  engine.
* Both **negative controls** bite: a fabricated verb comes back absent from the same code path.

**The first draft of that check was wrong in the most flattering way**, and it is recorded because
the correction is the lesson: it queried `(:Predicate)` nodes and returned a confident, uniform
`NOT FOUND` for all five verbs. Verbs in this graph are **relationship types**, not nodes. A
uniform extreme from a query whose label does not exist is an instrument failure wearing a
finding's clothes — and it would have been filed as "the template names five unregistered verbs".
The negative control is what makes that unrepeatable, which is why it is not optional.

### Seal 3's live arm — NOT run, and the blocker is not scheduling

The window was quiet and offered. **Pre-flight against the live bff killed the run before it
spent it**, and this replaces the earlier reasons (prime in flight, reaper deadlock, RULING (b)) —
none of which were tonight's problem:

**There is no `/artifacts/{id}` route.** The bff's surface is `/seed/portfolio_canvas`,
`/canvas/seed`, `/canvas/lineage_edges`, `/me/canvases`, `/interview/stream`. The arm recovers
each panel's verb by fetching the artifact by id, because today's seed returns **only** ids. That
fetch 404s — so the arm would have burned ~25 minutes on the first seed and then errored with
nothing recorded.

**And the near-miss is worse than the miss.** Had recovery returned `None` per panel instead of
404ing, both runs would have produced identical all-`None` panel sets and **seal 3 would have
PASSED**. A broken instrument turning a seal green is strictly worse than one turning it red.
The arm now has an explicit **VOID** state — a run that cannot recover verbs is neither pass nor
fail — plus a pre-flight route probe and an all-`None` guard.

`AnswerArtifact` exists as a Neo4j label and is the likely headless recovery path. It is
deliberately **not wired yet**: writing a recovery path I have not proven would reintroduce the
same defect one layer down.

**What the run needs before it is worth a window:** a proven verb-recovery path, the VOID state
(done), and the positive control — `/canvas/seed` is now deployed, so the template path can be
seeded twice (must be **identical**) alongside the phrase path twice (must **differ**). Same
instrument, both answers, one substrate. That is what makes the failure attributable rather than
merely expected, and it roughly doubles the runtime.

### The second template — ratified, and deliberately NOT seedable

`policy/canvases/program_finance.yaml`, six `PROGRAM_FINANCE_ANALYST` verbs, `shared_slots: []`
per dispatch. It exists to be §9.2's second registry row.

**It cannot seed today, and that is a property of the verbs rather than an oversight.** All six
take `program_id` as a **required keyword with no default**; `finEacCalculation` also takes
`method`, whose docstring says *"There is no default"* and which ADR-0045 makes spoken-mandatory.

`portfolio.yaml` could declare its verbs' defaults and be true today **because every planning
verb defaults to portfolio-wide. Finance has no such defaults to declare.** A finance template
that named these verbs with empty slots and looked seedable would merge, pass every check, and
refuse on all six panels at seed time — precisely the empty-panel shape seal 1 exists to catch
and that a file-only check cannot see. So the file says so in its own header rather than looking
ready.

`program` belongs in `shared_slots` and is exactly why §3 names it as the worked case ("six cards
from one ask"). `method` stays panel-local when that lands — it is a per-panel choice, not a board
subject, and promoting it would ask one question to answer a different one.

**The panel most likely to be wrong as declared is flagged in the file**: `finEacCalculation` is
pinned to `method: CPI` only to make the panel expressible, and EAC is spoken-mandatory *because*
the three methods disagree materially — $13.13M / $14.15M / $14.79M against a $12.00M budget on
the engine's own seed. A template that silently picks one is choosing the answer. The alternative
is three EAC panels or a panel-local ask, and that is a ruling, not a build detail.

### OWED, updated

* **The seal-3 verb-recovery path** (`AnswerArtifact` in Neo4j) — the live arm stays void without it.
* **The EAC ruling** — one pinned method, three panels, or a panel-local ask.
* **`program` as a shared slot** for `program_finance`, gated on the dispatch-boundary slot carry.
* Unchanged: the cortex `TEMPLATES` row, frontend-first, before either template is advertised.

---

## 2026-09-09 — A2 REFUSED on evidence, A4 recorded but not yet honourable

Two dispatched items. Neither can be applied as stated, and both premises are disprovable from
code that landed last night. Recorded here because *"why is `program` still not a shared slot"* is
a question that will be asked again.

### A2 — declaring `program` as a shared slot would BREAK the one template that seeds

The dispatch: *"declare `program` as a shared slot on both templates… seeding a finance board
should then raise the one-option `program` ask and bind it into all six panels… it is what makes
`program_finance` seedable at all."*

**There is no ask, and nothing binds.** `gateway.py`'s seed route computes
`_unbound = {required shared slot names} ∪ {every panel's consumes}` and, if that set is
non-empty, raises **409** in its own words: *"declares shared slot(s) … that nothing binds yet, so
every panel would refuse. This is the ADR-0050 §3 carry, not a fault in the template or the
request."* The elicitation half of §3 does not exist yet; what exists is the refusal that stands
in for it.

So the dispatch's effect would be the reverse of its stated purpose:

| template | today | after declaring `program` |
|---|---|---|
| `portfolio` | **SEEDS** — the only one that does | **409, stops seeding** |
| `program_finance` | 501, not yet seedable | 409 — still not seedable, different reason |

`program_finance` does not become seedable; its refusal changes shape. And `portfolio` — the live
demo path, the only template past the `if template_id != "portfolio"` 501 gate — would go from
working to refusing. **That is a regression on the only path that currently produces a board.**

**And `program` is not a planning concept at all.** `program_id` occurs **0 times** in
`agent_fleet/planning_agent/measures.py` and **26 times** in the finance engine's. The five
planning verbs take `scope_initiative_id`, `site_id`, `group_by`, `color_by`, `window`, `as_of` —
no program anywhere. Declaring it on `portfolio` would declare a slot none of its verbs accept,
which is the invented-parameter defect one plane up from the invented-IRI rule.

**What actually unblocks `program_finance`, in order:** (1) the seeder dispatches each panel's
DECLARED verb instead of running the portfolio phrase list — that is the 501 gate's own stated
condition; (2) something binds a shared slot's answer into panels — the 409 gate's condition.
Declaring the slot is the LAST step, not the first, and doing it first converts a clear 501 into a
409 while breaking `portfolio`.

**The peer's `test_the_unbound_shared_slot_refusal_is_UNREACHABLE_TODAY_and_that_is_recorded`
therefore stays green, and stays right.** It was written to go red when a ratified template
declares shared slots, so that the dead 409 branch is not believed to be exercised. It should go
red when the carry lands — not when a template declares a slot the carry cannot serve. Turning it
red today by declaring the slot would be satisfying the seal's letter while defeating its purpose.

### A4 — the EAC ruling is right, recorded, and not expressible by this verb

The ruling: **all three methods on one panel; pinning hides the divergence that is the finding.**
Accepted without reservation — the spread ($13.13M / $14.15M / $14.79M against a $12.00M BAC, ~14%
of BAC) *is* the answer, and it was the reason for declining to pin it in the first place.

**It cannot be honoured from a template.** `fin_eac_calculation` takes `method: EACMethod` — a
single `Literal["CPI","CPI_SPI","REMAINING_AT_BUDGET"]` — and raises `MethodRequired` on anything
else. There is no multi-method affordance in the finance engine. **One panel is one verb
invocation is one method.** A YAML cannot produce three numbers from a verb that returns one, and
`method: [.., .., ..]` would be refused by the verb, not honoured by it.

So the ruling needs an **engine** change — the verb returning all three rows, or a sibling
comparison verb — which belongs to the finance lane. `method: CPI` remains in the file as an
explicit **placeholder**, now labelled as one: the note records the ruling, says the verb cannot
honour it, and states that the panel is inert anyway because the template refuses at seed time.
The placeholder costs nothing today and the ruling is written down rather than quietly unmet.

**What would make this wrong to leave:** if `program_finance` ever becomes seedable before the
engine change lands, that panel emits one method and the ruling is silently violated by a file
that claims to record it. Whoever closes the 501 gate must check this note first — which is why it
is in the panel rather than only here.

---

## 2026-09-09 — SEAL 3 RUN LIVE. Result: VOID (twice), and the second void is a finding on `/artifacts/{id}`

**Seal 3 is still unrun.** It has produced no pass and no fail. Both attempts voided, and saying
so plainly matters more than either answer would have.

### Attempt 1 — a FALSE PASS, caught by the clock and nothing else

Green in **2.48 seconds** against work RULING (b) puts at ~50 minutes. Four tests passed, exit
code 0, no assertion fired. The implausible duration was the only thing wrong-looking about it.

All five seeded questions had failed **HTTP 403 in ~0.1s** (run identity `agent-user` holds
`data-engineers`, not the `portfolio-leads` cell Engine P's verbs live in). The route still
answered **200 with five null `artifact_ids`**. Both runs produced five `unseeded` panels,
compared EQUAL, and the seal reported PASS on a board where nothing seeded.

**The hole was the exemption in `45a2d06`, one commit old.** That guard voids when a panel that
*seeded* records no verb, and deliberately exempts panels the seeder itself reported as failed —
because a failure in run A and a success in run B is a genuine difference. Right, and incomplete:
it holds only while *something* succeeded. Two total failures are two empty sets scored as
agreement. Closed in `8ee159b`: void when no id comes back at all, naming `seeded`/`total` and
every slot's status. **`seeded` and `total` were in the response the whole time and the arm read
neither.**

> **A guard that exempts a case inherits that case's failure mode.** Third instance in this arc,
> all three mine — the two-rule fixture, the label that did not exist, and now this.

**Entitlement finding, independent of the instrument:** any headless harness that seeds as
`agent-user` measures nothing and looks healthy. The 403 arrives *before* routing, so
`policy/groups.yaml`'s own warning — *"the question grounds to nothing and routes nowhere, while
every engine reports healthy"* — applies one layer earlier than where it was written.

### Attempt 2 — a real seed, and a real VOID

Re-run as **alice**, who holds `portfolio-leads` (PORTFOLIO_LEAD · PORTFOLIO_PLANNING) per
committed policy. **No Topaz write was made; this is an identity choice from `policy/users.yaml`.**

Run A seeded for **398s (6m38s)** — real work. It returned five artifact ids. Then the first
artifact read **404'd**, and the arm voided rather than recording a difference:

```
SEAL 3 VOID — artifact urn:li:answerArtifact:seal3-run-a-seed0-06d9592b (ordinal 0):
the seed returned this id and the store does not have it.
```

**The store does have it.** That void is correct about its own limits and wrong about the cause,
which is what a void is for.

### THE FINDING — `GET /artifacts/{id}` cannot read the artifacts it produced

Diagnosis, each step checked rather than inferred:

| step | result |
|---|---|
| artifact in Neo4j? | **yes** — `(:AnswerArtifact {id: 'urn:li:answerArtifact:seal3-run-a-seed0-06d9592b'})` |
| URL-encoding? | **no** — raw and percent-encoded both 404 |
| `PRODUCED_FOR` present? | **yes** → `(:Actor {actor_id: 'a400f096-…'})`, persona PORTFOLIO_LEAD |
| does that actor match the caller? | **alice's token `sub` IS `a400f096-…`** |
| so why 404? | the route does not scope on `sub` |

`_ARTIFACT_BY_ID_CYPHER` matches `(:Actor {actor_id: $user_id})` with
`$user_id = current_user.authz_id`. And `auth.py:184` computes
`authz_id = payload.get(USER_ENTITLEMENT_CLAIM) or sub`, where
`USER_ENTITLEMENT_CLAIM = os.getenv("USER_ENTITLEMENT_CLAIM", "email")` — **read from the code,
not its comment** — and the deployed `iagent-config` **does not set it**. So the read path scopes
on `alice@example.com` while the write path stamped the `sub` UUID.

**Alice has TWO `Actor` nodes, and the routes disagree about which one she is:**

```
actor_id = 'alice@example.com'                        persona DATA_ENGINEER      artifacts:   1
actor_id = 'a400f096-d252-49cc-9336-5f47a5b9e4cd'     persona PORTFOLIO_LEAD     artifacts: 285
```

**285 of alice's 286 artifacts are unreadable through the route, permanently, by their own
producer.** It is not a seal-3 problem, not a timing problem, and not fixable in the arm: it is a
split identity between the write path (`sub`) and the read path (`authz_id`, defaulting to
`email`).

And the failure wears the wrong face — `404 "no artifact {id} for you"`. The route's own docstring
argues 404-not-403 so as not to reveal that an id exists, and separately keeps 503 distinct from
404 because *"we could not look" is not "there is no such thing"*. Both are right. This is the
third member of that family and it is unhandled: **"it is yours and I looked in the wrong place"**
also renders as "there is no such thing".

### What this does NOT settle

Seal 3's actual subject — whether two phrase-based seeds produce the same panel set — remains
**unmeasured**. The structural result stands (a phrase seed cannot express a panel set at all),
and it is still the stronger of the two. The live arm is now blocked on a defect in the read path
rather than on a window, a prime, or the queue.

**Incidental measurement worth banking:** one seed of five questions took **6m38s**, not the ~25
minutes RULING (b) estimates. If that holds, the live arm is ~14 minutes rather than ~50, and the
scheduling constraint around it is roughly 4× less severe than assumed. One observation, not a
claim.
