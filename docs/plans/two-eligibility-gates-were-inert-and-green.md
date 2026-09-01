---
id:         two-eligibility-gates-were-inert-and-green
status:     closed
owner:      agent (lane 1) — FOUND AND FIXED 2026-08-31
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/mesh_registrar/main.py (_build_rel_props_for_saga, RegistrationManifest), agent_fleet/utils/mesh_registration.py (register_engine_to_mesh, _emit_to_registrar), agent_fleet/ontology_service/main.py (/plan)
summary:    TWO FINDINGS FROM ONE LOG, both structural, both invisible to a green suite. (1) `arity` and `required_args` reached NO Neo4j edge. The READ half was complete and had been for months - the compat walk RETURNs both, `CompatibleVerb` declares both, its constructor passes both, and `_filter_verbs_by_arity` gates on the result - while the WRITE half existed at zero sites. Every verb read back null, both gates treat null as "never exclude", and the arity gate has been INERT on every cluster since it shipped. Measured on sandbox through the consumer's own view: 0 of 10 verbs on idp#Portfolio carried either property. `required_args` was DECLARED on the manifest and populated and STILL dropped at the property bag. (2) `/plan` shipped no TypeBuilder to `DecomposeQuery`, whose `target_persona` is an `@@dynamic` enum with no static members - so BAML got an EMPTY enum, every task failed to parse, and `tasks: []` came back with reasoning intact. The passthrough then stamped DATA_STEWARD on 100% of queries the fleet ever planned. A/B against the live LLM in-pod: same prompt, same moment, tasks=[] without the TypeBuilder and PORTFOLIO_LEAD with it. THE COMMON THREAD: both had a wrong explanation already written down next to them, and a plausible explanation is stickier than none.
---

# Two eligibility gates were inert, and the tests were green

Both of these came out of a **routing log from the work cluster**, pasted to diagnose
something else entirely (a missing canvas verb). Neither was what anyone was looking for.

## Finding 1 — the gates read properties nothing wrote

`_filter_verbs_by_arity` drops a `single`-asset verb from a set-shaped query.
`_filter_verbs_by_argument_fit` drops a verb whose `required_args` the query cannot
supply. Both read their declaration off `/find_compatible_verbs`.

**The read half was complete.** The compat walk's Cypher RETURNs `r.arity` and
`r.required_args`; `CompatibleVerb` declares both fields; the constructor passes both;
the gates consume both. Four of the seven enumeration sites, all correct.

**The write half existed nowhere.**

| site | `arity` | `required_args` |
|---|---|---|
| 1. `register_engine_to_mesh` (engine-facing) | ✗ | ✗ |
| 2. `_emit_to_registrar` manifest | ✗ | ✗ |
| 3. `RegistrationManifest` | ✗ | ✓ |
| 4. DataHub custom props | ✗ | ✓ |
| 5. **`_build_rel_props_for_saga`** — THE LIVE WRITE | **✗** | **✗** |
| 6. Cypher RETURN | ✓ | ✓ |
| 7. `CompatibleVerb` + constructor | ✓ | ✓ |

An engine could not declare `arity` at all — it was not a field anywhere on the write
path. And `required_args`, which *was* a manifest field, was populated and then dropped:

```
manifest HAS an 'arity' field : False
manifest.required_args        : ['tag']      <- declared, and held
bag has 'required_args'       : False        <- and dropped, silently
```

Measured on the sandbox cluster through `/find_compatible_verbs` — the consumer's own
view, not the graph:

```
10 verbs on idp#Portfolio
carrying arity        : 0/10
carrying required_args: 0/10
```

### It had a tell, and it was not silent

Unusually for this failure class, Neo4j says so **on every single compat walk**:

```
Received notification from DBMS server: ...
  the missing property name is: arity
  the missing property name is: required_args
```

Two warnings, every call, for months. They were read as noise because a DBMS
notification looks like tuning advice rather than a broken feature.

### Why the tests stayed green — and this is the transferable part

`tests/test_arity_gate.py` and `tests/test_argument_fit_gate.py` are thorough, well
written, and **build every verb dict by hand**:

```python
def _v(iri, arity=None):
    return {"verb_iri": iri, "arity": arity}
```

They prove the FILTER does what it says when handed a declaration. They **cannot fail
when no declaration can ever arrive**, because they are the thing that supplies it. The
claim was *"a single-asset verb is excluded from a set query"*; the assertion was on the
neighbouring claim that a pure function excludes what it is passed.
`[[assert-on-the-claim-not-its-neighbour]]`, in its most expensive form yet: not a bad
instrument, but a **correct test of the wrong half of a two-half claim**.

### The fix

Both properties now travel all seven sites. `arity` follows the `timeout_s` idiom and is
written only when declared, so an undeclared verb holds no property rather than an empty
string that reads as a value. `required_args` is written as a list of primitives — never
a JSON string, which would make `list()` on the read side yield one entry per character.

`tests/test_eligibility_declarations_reach_the_edge.py` asserts on the CARRY and closes
the loop: it feeds the registrar's real property bag into the supervisor's real gate, so
the key names are the join and a rename on either side goes red. Verified to fail against
`HEAD` before the change.

**This does not by itself activate the gates.** No engine declares either property today,
so both still read null for every verb and still exclude nothing. What is fixed is that
declaring one now works — before, it was a silent no-op, which is the state that would
have burned whoever tried it next. **The properties also only land at REGISTRATION**, so
existing edges stay bare until the engines re-register.

## Finding 2 — `/plan` threw the model's answer away, and blamed the model

`AgentTaskDefinition.target_persona` is typed `PersonaTarget`, declared `@@dynamic` with
**no static members**. `/plan` — the only caller of `DecomposeQuery` — shipped no
TypeBuilder, so BAML received an **empty enum**, no task could carry a legal value, and
every task was dropped at parse.

The tell is in the rendered prompt, not the response:

```
{
  tasks: [ { target_persona: ,          <- nothing after the colon
             sub_query: string } ],
```

The model answered correctly every time. A/B against the live LLM, in-pod, same prompt,
same moment:

```
WITHOUT TypeBuilder (current prod) -> tasks=[]
WITH    TypeBuilder (the fix)      -> tasks=[{'target_persona': 'PORTFOLIO_LEAD', ...}]
```

`/route_and_plan`, 450 lines below, builds the TypeBuilder correctly. The endpoint that
is actually called did not.

### The wrong explanation was already written down

The downstream passthrough carried this comment:

> *gpt-oss via Ollama (and similar reasoning-heavy small models) sometimes populates
> reasoning + extracted_concepts but leaves tasks=[].*

Every clause is wrong. Not *sometimes* — **always**, deterministically, on 100% of calls.
Not the model — the parser. And the consequence was not a degraded plan but a **hardcoded
`DATA_STEWARD`** stamped on every query the fleet has ever planned, including portfolio
ones.

The branch survived because **it looked explained**. `tasks=[]` alongside populated
`reasoning` and `extracted_concepts` is exactly what a small model declining to decompose
would produce, and a plausible story attached to a real symptom stops the search.
`[[a-plausible-negative-is-not-a-considered-one]]` — same shape, one level up: not a
plausible *result* here, but a plausible *diagnosis*.

The passthrough is KEPT as a genuine fallback, its comment corrected to record what was
actually measured. `degraded` in a response is now real signal about the model instead of
a constant.

**Still open, deliberately:** `DATA_STEWARD` as the passthrough's hardcoded persona is a
guess and a wrong one for most domains. Changing it is a routing decision and wants its
own ruling rather than a ride-along on a wiring fix.

## What this cost, and what to take from it

Both defects sat behind an explanation that fit. One was a comment blaming a model; the
other was a DBMS warning that reads like tuning advice. Neither system was silent — both
were **saying the right thing in a register nobody audits**.

See also `[[a-registration-property-must-be-enumerated-seven-times]]` (the checklist these
two properties violated at five of seven sites) and
`[[read-the-consumer-of-what-you-fixed]]` (the law that produced the sandbox measurement:
`/find_compatible_verbs` was read as the consumer's view rather than the graph queried
directly).

---

## ✅ ROLLED AND MEASURED ON SANDBOX — 2026-09-01

`9d25db7` (the carry) + `ac0b837` (the first declaration) + `f65c5ce` (the probe map).
Rolled through `scripts/roll-litany.sh` in dependency order — **mesh-registrar first**, so
the engines re-register against the fixed registrar rather than before it — then engine-p,
then engine-o. Five legs each, `fail=0`, and **every image digest changed**, so these were
new images rather than restarts:

```
mesh-registrar  8b577ecf -> 2537174e
engine-p        c917bc18 -> fc8f03fb
engine-o        7f2159db -> 867d413c
```

### Finding 1 — the carry, measured as a transition

Through `/find_compatible_verbs` on `idp#Portfolio`, the consumer's own view:

| | before | after |
|---|---|---|
| verbs | 10 | 10 |
| carrying `arity` (non-null) | **0/10** | **1/10** |
| carrying the `required_args` key | **0/10** | **10/10** |

The 1 is exactly the one verb declared — `planDependencyNeighborhood`, value `single`.
`required_args` is now present on every edge as `[]`, which the gate reads as
unconstrained and which makes the edge self-describing.

### The gate, run on the REAL dicts the live compat walk returned

```
set-shaped query -> DROPPED 1: ['mesh:planDependencyNeighborhood'],  KEPT 9
instance query   -> DROPPED 0                                        (conservative direction holds)
```

**Lumpy, not uniform** — 1 of 10, 9 kept, 0 in the other direction. A uniform result here
would have been the tell that the instrument, not the system, was answering.

**THE HONEST BOUNDARY:** the gate function was fed the live response and run out of process.
What is proven is the CARRY and the JOIN — the property survives registration, reaches the
edge, comes back through the compat walk under the key the gate reads, and the gate acts on
it. What is NOT exercised here is the supervisor's own three-line call site
(`query_is_set = not subject_instance_id`), which is unit-tested and unchanged. A full route
through the dagster supervisor would close that last link.

### Finding 2 — `/plan`, verified in production

Same probe, same cluster, before and after the roll:

```
before:  tasks=[{'target_persona': 'DATA_STEWARD'}]   degraded='synthesized_passthrough_zero_tasks'
after :  tasks=[{'target_persona': 'PORTFOLIO_LEAD'}] degraded=None
```

The passthrough no longer fires. `degraded` is now real signal about the model rather than a
constant.

### A prediction that was wrong, recorded because it was nearly reported

The `the missing property name is: arity` warning was going to be the proof that the write
landed. **Sandbox never emitted it** — a compat walk was triggered and the full log checked,
and it appears on the work cluster but not here. So that tell is cluster-specific and was
never available as a before/after on sandbox. The carriage numbers are the measurement; the
warning was a neighbour of the claim, not the claim.


---

## ⚖ THE DERIVATION LANDED, AND A ROLL LIED ON THE WAY — 2026-09-01

`f417de6` replaced the one-verb probe with `arity_for()`: a measure is **single** when it
has a slot that is both REQUIRED and a REFERENT — it cannot run without one named
instance. Four of fourteen.

### The blast radius was measured against the corpus, not asserted

| | |
|---|---|
| target of ALL 14 TIER 3 phrasings | the four single verbs |
| target of any Tier 1 (22) or Tier 2 (12) phrasing | **none of them** |

And Tier 3's own header, written by hand from demo failures months earlier, is the same
predicate: *"the measure requires an id that nothing can resolve … Architecture item,
post-demo. Do not script these."* **Two independent derivations of one set** — the corpus
found it from failures, `arity_for` finds it from signatures. That agreement is worth more
than either alone.

So the gate turns Tier 3 from *routes, then 400s two hops later* into *never a candidate*,
which is what that tier's standing note asks for.

### Measured post-prime, across all four subject classes

The four verbs are typed on four DIFFERENT classes, so `idp#Portfolio` alone shows 1, not
4 — an expectation stated wrongly before it was checked, and corrected by looking.

```
idp#Portfolio        10 verbs   single: planDependencyNeighborhood   set-query drops 1, keeps 9
idp#Capability        2 verbs   single: planCapabilityPath           set-query drops 1, keeps 1
idp#BusinessProcess   1 verb    single: planProcessEvolution         set-query drops 1, keeps 0
idp#Technology        1 verb    single: planTechFootprint            set-query drops 1, keeps 0
                                        TOTAL 4/14 ; instance-query drops 0 everywhere
```

**Two classes now go to ZERO candidates for a set-shaped query.** That is correct rather
than alarming — the only verb on each cannot run without a named instance — and zero verbs
is a defined ADR-0019 Contract B outcome, not a crash. It abstains where it used to 400.

**They survived the prime.** The pod was started 03:16:09Z with 0 restarts and the prime
finished 04:03:07Z, so these properties were written 47 minutes BEFORE the prime and came
through it. That retires a risk flagged in advance: registration happens at engine startup
only, so a prime that rebuilt verb edges would have silently dropped them with nothing to
re-register. It does not.

## ⛔ AND THE ROLL THAT CARRIED IT PASSED EVERY LEG WHILE THE ENGINE WAS UNREGISTERED

The first attempt rolled engine-p into a window where the whole sandbox was being
redeployed and Keycloak was mid realm-import. Every mint retry got connection-refused:

```
❌ mesh registration: UNREGISTERED (mint failed: Keycloak token endpoint unreachable)
```

**`roll-litany.sh` reported `fail=0`.** Rollout ok, digest changed, SDK present, posture
announced, gauge line produced. Five green legs on an engine that had joined nothing.

**And the measurement that followed was believable.** The verb edges from the previous
registration were still in the graph, so `planDependencyNeighborhood` still read `single`
and the three new verbs read `None` — which looks exactly like *"the derivation only
reached one verb."* It was nearly reported as that. What caught it was the number
disagreeing with a derivation that had just passed its unit tests, and reading the
registration log before believing the graph.

> **A ROLL IS EXACTLY WHEN STALE AND FRESH STOP BEING DISTINGUISHABLE BY LOOKING.** Every
> other check in the litany asks whether the pod SERVES. None asked whether it JOINED, and
> a half-rolled engine serves perfectly.

**LEG 6 added** (`roll-litany.sh`): fail if the pod log carries the UNREGISTERED alarm. It
fails on the alarm's PRESENCE, never on a success line's absence — mesh-registrar and the
other non-registrants emit neither and must keep passing, which is the defect leg 5 had to
be rescued from once already. The alarm had always named its own postcondition test
(`tests/routing/test_resolve_instance_probes.py`); that test was simply never part of a
roll.

Proven both ways: **green** live against a registered engine-p (0 alarms, 16 registrations)
and against mesh-registrar as a non-registrant (0 alarms, 0 registrations, passes);
**red** against the captured alarm text from the roll that passed 5/5 — the unregistered
pod itself was gone by then, so that arm is the predicate rather than a live firing, and
the kubectl plumbing it shares with legs 4 and 5 is live-proven.

### Two neighbours, outside this lane

* **`iagent-realm-reconcile` failed** — *"keycloak never became ready"*. Minting works
  anyway because the realm survived in the Postgres PVC, so the failure is currently
  invisible. On a genuinely fresh environment every engine's registration would fail the
  way engine-p's did, and the litany would have reported `fail=0` for all of them.
* **Keycloak reported `ready=true` while port 8080 refused connections**, still importing
  its realm. That is what let engine-p roll into the window, and what timed out the
  reconcile job.
