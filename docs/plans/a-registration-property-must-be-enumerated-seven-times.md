---
id:         a-registration-property-must-be-enumerated-seven-times
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/utils/mesh_registration.py, agent_fleet/mesh_registrar/main.py, agent_fleet/ontology_service/main.py
summary:    THE CHECKLIST, written once so the next feature does not rediscover it four hops at a time. A new registration property reaches the router only if it is named at SEVEN sites, each of which enumerates fields BY NAME. An enumeration that omits a key is SILENT BY CONSTRUCTION - no error, no warning, and the symptom is a verb that appears to declare nothing. Adding `mesh_slots` cost a day and two false "this is the single gate" claims, because four of the seven were found only after an earlier one had been declared complete. Carries two laws: a fix is not finished until you have READ the consumer of what you fixed; and walk the path for embedded DSLs - lift the real string, substitute its parameters, execute it against the real engine, BEFORE deploying.
---

# A registration property must be enumerated seven times

## The checklist

An engine declares something at registration. For that value to reach the router, it must be
named at every one of these. Miss one and the value stops there, silently.

| # | site | file | shape |
|---|---|---|---|
| 1 | the engine's manifest | `agent_fleet/utils/mesh_registration.py` → `_emit_to_registrar` | typed value |
| 2 | **and the call that builds it** | same file → `register_engine_to_mesh` passes it through | — |
| 3 | the gateway's model | `agent_fleet/mesh_registrar/main.py` → `RegistrationManifest` | typed field, defaulted |
| 4 | the Neo4j property bag | same file → `_build_rel_props_for_saga` | **primitive or array of primitives** |
| 5 | the DataHub audit record | same file → `custom_props` | string |
| 6 | the compat-walk `RETURN` | `agent_fleet/ontology_service/main.py` → `_FIND_COMPAT_VERBS_CYPHER` | `coalesce(r.x, default)` |
| 7 | the response model **and its constructor** | same file → `CompatibleVerb` and the `CompatibleVerb(...)` call | defaulted field + explicit kwarg |

Plus, if manual-re-sync parity matters: doc-tools'
`aitool_linker._build_relationship_properties` — **retired** (ADR-0006 §Addendum,
2026-06-13), reaching no live edge, and kept only for launchpad re-syncs.

### Two traps inside the checklist

**The Neo4j one.** A property value may be a primitive or an array of primitives — **never a
map, and never an array of maps**. Anything structured is stored as its JSON string and
decoded on the read side. Measured, in a rolled-back transaction:

```
[{"name": "group_by", ...}]     REJECTED   Neo.ClientError.Statement.TypeError
'[{"name": "group_by", ...}]'   ACCEPTED
["A", "B"]                      ACCEPTED   (control)
```

The tell is already in the codebase and reads as an inconsistency: `synonyms`,
`anti_synonyms` and `domains` are decoded (lists of **strings**); `openapi_schema` — the one
structured payload — is passed through as raw text. **When a file treats one member of a set
differently, the exception encodes a constraint. Read it before copying the majority.**

**The decode one.** On the read side, `list(json_string)` yields **one entry per character**.
Use `iagent_pure.slot_acceptance.decode_declarations`, or the equivalent for your value. This
is the same container-traded-for-elements defect that produced
`422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4` — Python iterates strings happily, and
the wrong answer has the right type.

## Why this document exists

Adding `mesh_slots` took a day. **Four of the seven hops were found only after an earlier one
had been announced as "the single gate on the whole feature"** — twice in a report to the
user, both times handing the work off as blocked on someone else.

The failures were not carelessness at any single hop. They were the same mistake repeated:
**assuming the previous fix completed the chain.** An allowlist that drops an unlisted key
raises nothing. A Pydantic model that drops an extra key raises nothing. A Cypher `RETURN`
that omits a column raises nothing. Every one of them produces a plausible, complete-looking
result, and the observable symptom is identical in all seven cases: *the verb declares
nothing*.

> ### A fix is not finished until you have READ the consumer of what you fixed.
>
> Each of the seven hops was found by opening the next consumer instead of trusting that the
> value now flowed. Applied late twice and correctly five times, in one day, on one key.

## The sibling law, for anything handed to another language

> ### Walk the path: lift the real string, substitute its parameters, and execute it against
> ### the real engine — BEFORE deploying.

`/find_compatible_verbs` returned **500 to every caller** because the slots `RETURN` block was
commented with SQL-style `--`. Cypher's line comment is `//`; Neo4j rejects the entire query.
Three layers of silence over two characters:

* **Python is happy** — it is a string;
* **no test executes the literal** — that needs a live Neo4j;
* **the endpoint logged only `500`**, no traceback, no message naming the cause.

The check that found the fix is the one that would have prevented the outage: pull
`_FIND_COMPAT_VERBS_CYPHER` out of the source, substitute `$MAXHOPS$`, run it. It generalises
to every string this system hands to another language — Cypher, SPARQL, SQL, BAML prompts,
Cypher-in-APOC. `tests/planning/test_slots_reach_the_live_substrate_writer.py` now scans every
Cypher-bearing literal in three modules for `--`.

## The worked example

`mesh_slots`, end to end, is `[[slots-are-extracted-then-dropped-at-dispatch]]`. Verified on
the live graph by name against signatures — five verbs, zero disagreements — and through
Engine O's HTTP surface at 7 of 10 verbs carrying declarations.
