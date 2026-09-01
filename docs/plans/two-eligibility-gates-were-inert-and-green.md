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
