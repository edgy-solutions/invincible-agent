---
id:         registrar-models-presentation-triples
status:     open
owner:      agent
blocked-on:
closed-by:
implements: ADR-0006-addendum-gateway-v02-sole-writer, ADR-0017-presentation-as-predicate
code-site:  agent_fleet/mesh_registrar/main.py, agent_fleet/mesh_registrar/v2_substrate.py, agent_fleet/utils/mesh_registration.py
repo:       invincible-agent
summary:    THE LAST ARCHITECTURAL PIECE for rendersAs. Presentations cannot reach Weaviate by ANY automatic path today: the gateway's RegistrationManifest models only verb edges (input_uri/output_uri), so register_presentation_to_mesh bypasses it and emits direct-to-DataHub — and the DataHub→Weaviate materializer (doc-tools' aitool sensor) was RETIRED 2026-06-13 when Gateway v0.2 became sole writer. Those emissions are audit records going nowhere. Teaching the manifest the SPO triple shape makes presentations register the way everything else registers: through the sole writer, Contract-D-checked against the archetype classes, landing in the same Predicate collection the 24 verb rows already occupy.
---

# The gateway models verbs. Presentations are triples.

## What is actually broken

Measured 2026-08-21, after the ontology prime landed all six archetype classes
and engine-f re-registered cleanly:

| link | state |
|---|---|
| archetype classes in Neo4j | **6/6 present** |
| presentation URNs in DataHub | **11**, full IRIs on subject/object |
| `rendersAs` rows in Weaviate | **0 of 24** |

Nothing in that table is a bug. Every component did what it was built to do.
The triples land in DataHub and stop, because **the only thing that moves a
registration into Weaviate is the mesh-registrar, and the registrar has never
been told what a presentation is.**

`agent_fleet/utils/mesh_registration.py` says so at the emit site:

> Presentations don't currently go through the mesh-registrar gateway — the
> gateway's `RegistrationManifest` only models verb edges
> (`input_uri`/`output_uri` pair); the `(subject, mesh:rendersAs, archetype)`
> triple shape isn't supported yet. When the gateway adds presentation support,
> mirror the dispatch above.

This packet is that sentence, executed.

## Why the fallback is not a fallback

ADR-0006 §Addendum retired doc-tools' aitool sensor and preserved the asset for
"a one-off manual re-sync via Dagster's launchpad". That path is **also dead**,
for an unrelated reason: the doc-tools pod's `DATAHUB_TOKEN` is invalid, every
GMS call returns HTTP 401, and the asset reported **SUCCESS while skipping**.
Fixed separately (`MeshToolUnreachableError`) so the trap becomes an honest
error — but it is a health item, not this arc's path. Even with a valid token,
routing presentations through a retired sensor would re-open the sync-gap the
Addendum closed. **One substrate, one writer** is the ruling; this is its
mechanism.

## Design

### 1. Manifest schema extension

`tool_kind` becomes the discriminant, defaulting to `"Engine"` so **every
existing caller is byte-identical** — no engine manifest changes, no version
negotiation.

```python
tool_kind: Literal["Engine", "Presentation"] = "Engine"
```

Presentation-shaped fields, all optional at the type level and enforced by a
model validator keyed on `tool_kind`:

| field | engine | presentation |
|---|---|---|
| `verb_iri` | required | — |
| `input_uri` / `output_uri` | required | — |
| `subject_uri` / `object_uri` | — | required |
| `predicate_iri` | — | required, constant `mesh:rendersAs` |
| `archetype` | — | required (BAML enum string) |
| `expected_fields` | — | required list |
| `endpoint_url` | required | **must be absent** |
| `frontend_id` | — | required |

`endpoint_url` must be **rejected** on a presentation, not merely ignored. A
presentation is not callable; accepting an endpoint would let a caller
advertise one and produce a row that dispatch might later try to invoke.

### 2. The IRI convention is INHERITED, not invented

Confirmed empirically against the 24 live rows (2026-08-21):

- **predicate/verb position → compact** (`mesh:rendersAs`, `mesh:queryKnowledgeGraph`)
- **subject/object position → full** (`http://invincible-agent/mesh#OwnershipFact`)

This is per-POSITION, not per-file. An earlier reading of "compact = stale" was
wrong and nearly landed a regression that would have made presentations the only
row type with a full `verb_iri`. The manifest extension adopts the existing
convention; it does not get a new one. `_expand_mesh_iri` therefore applies to
`subject_uri` / `object_uri` only — exactly as the emit boundary already does.

### 3. Registrar write path

The existing Cypher already writes an edge between two `OntologyClass` nodes and
is shape-agnostic — only the property NAMES differ. The write path maps:

```
subject_uri   -> input_uri     (Contract D: must resolve to :OntologyClass)
predicate_iri -> verb_iri
object_uri    -> output_uri    (Contract D: must resolve to :OntologyClass)
```

Contract D validation is **unchanged and non-negotiable**: both ends must
resolve to existing `:OntologyClass` nodes. This is the guard that refused these
triples for weeks while the archetype classes were undeclared — it was right
every time. The classes now exist; the guard now passes; nothing about the guard
is relaxed.

`_deterministic_predicate_uuid(verb_iri, input_uri)` is reused as-is. NOTE the
known collision: two frontends registering different archetypes for the same
subject collide on `(mesh:rendersAs, subject)`. Deferred deliberately — see
"Known deferral" below.

### 4. Two-species discrimination

The registrar must keep verb rows and triple rows distinguishable at every
layer, and the discriminant must be **in the data**, not inferred:

- `mesh_tool_kind` persists onto the Weaviate row (it already rides in the
  properties bag and is already read — it was declared but unwired on the
  doc-tools side, which is precisely how the first branch got missed).
- `endpoint_url` is the reached-by-**calling** marker; `frontend_id` is
  reached-by-**replying**. A row with neither is malformed and must be refused.

## Test plan — break-on-purpose per species

Landing gate: **each arm proved red before the fix lands.** The failure mode
this arc keeps producing is a guard that is correct for its population and blind
to a species it was never told about, so every arm is written twice — once per
species.

1. **engine manifest unchanged** — an existing engine manifest with no
   `tool_kind` registers exactly as before. *Break:* make `tool_kind` required →
   red.
2. **presentation registers** — a full manifest produces a `rendersAs` row.
   *Break:* drop the `tool_kind` branch → red.
3. **presentation missing its own fields is refused** — the branch must not
   become a bypass. *Break:* skip per-kind validation → red.
4. **endpoint_url on a presentation is refused.** *Break:* accept-and-ignore → red.
5. **Contract D still refuses an undeclared archetype** — the guard is not
   weakened by the new path. *Break:* skip the class check → red.
6. **THE NON-REGRESSION**: re-registering all engines leaves the **24 verb rows
   intact and unchanged**. This is the arm that proves the two species share a
   table without colliding, and it is the one a schema change is most likely to
   break silently.
7. **IRI convention** — subject/object stored full, predicate stored compact,
   asserted against the live convention rather than a literal.

## The gate is UNCHANGED

B's read path unblocks only when a `rendersAs` row **exists in Weaviate** for a
registered presentation — now via the registrar. Not when the manifest accepts
the field. Not when the tests pass. Not when the deploy is green: this arc has
now produced a green hook chain, a green reregister job, and a green linker run,
all while writing nothing. **Count the rows.**

Corollaries banked from this session: *any result set equal to its limit is
unverified until counted*, and *existence cannot prove freshness*.

## What stays as it is

- **Direct-to-DataHub emission stays** — as what it actually is: an audit
  record, not transport. It is not the mechanism and must stop being described
  as one.
- **The doc-tools linker stays retired.** The `MeshToolUnreachableError` fix
  makes it fail honestly; it does not return it to service.

## Known deferral

Weaviate UUID collision on `(verb_iri, input_uri)` when two frontends register
different archetypes for the same subject — e.g. Cortex renders `OwnershipFact`
as `KNOWLEDGE_DOCUMENT` while OpenDDIL renders it as `CHART_WIDGET`. Both hash
to `(mesh:rendersAs, mesh#OwnershipFact)` and the second overwrites the first.
Out of scope here and **must not be silently absorbed**: the union-menu design
in [[capability-registry-not-graph-backed]] depends on both rows existing.
Tracked so the first multi-frontend registration does not discover it as a
mystery.
