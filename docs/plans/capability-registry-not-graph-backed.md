---
id:         capability-registry-not-graph-backed
status:     open
owner:      agent
blocked-on:
closed-by:
diverges-from: ADR-0017-presentation-as-predicate
code-site:  agent_fleet/presentation_agent/capability_registry.py, src/iagent/gateway.py, agent_fleet/utils/mesh_registration.py
repo:       invincible-agent
summary:    ⚠️ LIVE DEFECT, found by the 2026-08-21 redeploy. The frontend capability registry is a MODULE-LOCAL DICT, and registration and selection run in DIFFERENT PODS — `/register_frontend_capabilities` is served by cortex-bff, `/render_ui` by presentation-agent. Registration can therefore NEVER reach the selector: every caller is anonymous from engine-f's view, the union is always empty, and every answer falls to the labelled floor. CHART_WIDGET is currently unselectable in production for anyone. ADR-0017's own mechanism (rendersAs triples in the shared Predicate collection, read via /search_predicates) was always the design; the in-memory dict was scaffolding that was never written down as a divergence.
---

# The registry cannot be read where it is written

**Witnessed 2026-08-21**, first time the real topology ran with anyone watching. Engine F's
own log, with a `frontend_id` supplied and the seam executing correctly:

```
render_ui: menu-scoped selection frontend_id=cortex-ui-desktop
           source=default-menu  basis=None  -> no frontend has registered — union is empty
```

## The mechanism

| endpoint | workload | image |
|---|---|---|
| `/register_frontend_capabilities` -> `capability_registry.register()` | **cortex-bff** | `cortex-bff:latest` |
| `/render_ui` -> `capability_registry.select_presentation()` | **presentation-agent** | `presentation-agent:latest` |

`_REGISTRY` is a module-level dict behind a `threading.Lock`. Process-local. Two pods, two
processes, two registries — the writer's is populated and never read; the reader's is empty
and never written.

## Why three reviews missed it

1. **An untested topology assumption.** 71 tests exercise the registry IN ONE PROCESS. They
   prove the logic and say nothing about where it runs. A passing suite actively discouraged
   the question — [[a-green-check-proves-only-its-scope]] at arc scale.
2. **An acceptance that named artifacts, not the deployed claim.** The arc closed on
   contracts derived, seam threaded, tests green, files deleted — all real, none of them the
   claim, which was "menu-scoped selection is live."
3. **A known divergence that never became an indexed item.** Slice 2b's docstring flagged the
   registry as runtime state needing a runbook line. That flag described EPHEMERALITY ("empties
   on restart") when the truth was REACHABILITY ("never populated across the boundary"). It
   lived in a module docstring, which is where this project's own doctrine says claims go to
   be forgotten. **This packet is the line that should have existed.**

Also worth recording: the seam packet pre-recorded the `frontend_id=None` trap in detail. The
actual regression came through a door nobody listed — the guard was written for the wrong
failure.

## The repair: converge with the ADR that named it

`register_presentation_to_mesh` (`agent_fleet/utils/mesh_registration.py:394`) already emits
`(subject_uri, mesh:rendersAs, object_uri)` triples into the shared Weaviate `Predicate`
collection, retrieved by `/search_predicates`. Its own docstring states the intent: *"Engine F
(and any other component that knows how to render a shape) advertises its capabilities through
this helper."* That is graph state — it crosses pods because it is not in any pod.

The in-memory dict was scaffolding. Converging removes the divergence AND the defect in one
move, rather than bolting a shared store beside an ADR that already specified one.

Open design questions for the build, not assumed:
* how the triple carries `frontend_id` (a discriminator the current helper has no field for);
* how it carries the TYPED CONTRACT (the helper takes `expected_fields` — names only, which is
  the exact gap the contract work closed);
* freshness/staleness — a graph row outlives a pod, so re-registration must overwrite rather
  than accumulate, and the registration version needs to reach the decision.

## RULED 2026-08-21 — GRAPH AUTHORITATIVE, contract as its own node

**Option A, with one modeling adjustment that dissolves most of its apparent cost.**

### Why graph-authoritative, and not "component authoritative + fetch"

**The symmetry argument is decisive.** Engines already publish `input_uri`/`output_uri` into
the graph at registration, and the supervisor routes FROM THE GRAPH — nobody fetches from an
engine at route time to ask what it accepts. The graph is the authoritative snapshot of what
was published; the component is the PUBLISHER, not a runtime dependency. A fetch-based
presentation path would break that symmetry for presentation alone.

**And "the component stays authoritative" would have been illusory.** cortex-ui is the
CALLER. A render-time fetch lands on cortex-bff or wherever an uploaded contract is parked —
so it does not keep the contract with the component, it creates A SECOND STORE and calls it
the component. Then there are three: graph, store, client, with the graph demoted to an index
that can silently diverge. That is the Hole 4 finding again — a live approximation of the UI's
capabilities held somewhere other than the declared source of record — with an implicit "the
fetch keeps them synced" doing the enforcement.

### The adjustment: DO NOT inline the contract into the Predicate row

Contracts are DOCUMENTS (encodings, cardinality, refusal vocabulary). Stuffing a typed
document into row properties creates serialization surface exactly where compact-vs-full form
drift has bitten this project repeatedly.

Instead: **the contract is its own node, CONTENT-ADDRESSED, and the `rendersAs` triple
references it by hash/version.** The row-shape change shrinks to ONE reference field; the
contract becomes a first-class graph citizen with its own identity.

### This answers the other two open questions almost for free

* **Q3 (staleness) —** registration writes the contract node and REPOINTS the reference
  atomically, MERGE-overwrite on the row. A redeploy that drops a capability removes the row;
  one that changes the contract writes a NEW node and repoints. Content-addressing yields
  DRIFT DETECTION as a side effect: a hash mismatch between what the client would publish and
  what the graph holds IS the staleness signal, and it fires AT REGISTRATION TIME rather than
  at render time. (The fetch alternative is quiet in the worst way: a row pointing at a
  contract that changed underneath it serves the NEW contract under the OLD row's authority.)
* **Q1 (frontend discriminator) —** it lives in CONTRACT CONTENT, not triple semantics. The
  triple keeps meaning "this shape renders as that archetype"; client applicability is a
  property of the contract. Whether to add it becomes a separate decision instead of a fork.

### ⚠️ The honest cost, recorded rather than waved away

**Graph-authoritative means the graph schema now VERSIONS WITH THE CONTRACT VOCABULARY.** When
the refusal vocabulary grows a term, that is a graph-migration concern, not merely a component
redeploy.

That price is paid AT CHANGE TIME, WITH A VISIBLE MIGRATION. The fetch alternative's price is
paid CONTINUOUSLY on the render path and collected SILENTLY when the sync assumption fails.
Recorded here so the first person to hit the migration knows it was chosen, not overlooked.

### A tell worth keeping

Under the fetch option the two-process witness would NOT have proven the fetch edge without
extending it to three parties. **The option that makes an existing acceptance criterion
sufficient is usually the one whose architecture matches what is actually being claimed.**

## ⚠️ BLOCKER FOUND 2026-08-21 — the graph path itself is dead

**Premise-checked before building on it, and the ground is not there.** The ruling assumes
Engine F can read capabilities from the shared `Predicate` collection. It cannot today,
because presentation registrations never arrive in it.

Verified against the live system, not inferred:

| step | state |
|---|---|
| `register_presentation_to_mesh` called | ✅ works — direct DataHub emit, confirmed by running it in the pod: `✅ Registered … as (mesh:DiagProbe -> mesh:rendersAs -> mesh:KnowledgeDocument)` |
| registrations reach DataHub | ✅ **11 presentation mlModels** present (10 real + 1 diagnostic) |
| DataHub -> Weaviate `Predicate` sync | ❌ **0 rendersAs rows** — 24 Predicate rows, all engine verbs |

So the emit half works and the SYNC half does not carry presentations. Engine F's startup
loop is fine; its per-capability logs simply do not surface (a logging-config quirk in the
lifespan, NOT a functional failure — the DataHub entities prove the emits happened).

**The likely mechanism, not yet confirmed:** the `Predicate` row shape is verb-shaped —
`verb_iri`, `input_uri`, `output_uri`, `endpoint_url`. A presentation has NO `endpoint_url`,
and its triple is `subject -> mesh:rendersAs -> object` rather than input/output. doc-tools'
`aitool_linker` builds Predicate rows from the DataHub properties, and presentations may be
dropped or mis-shaped there. **That is a doc-tools change, a different repo and lane.**

### What this means for the build

The graph-authoritative ruling stands — the reasoning (symmetry with engine registration, the
second-store illusion, content-addressed drift detection) is unaffected. What changes is the
ORDER: the read path cannot be built until presentations actually land somewhere Engine F can
read. Two candidate resolutions, neither assumed:

1. **Fix the sync** so `rendersAs` rows reach `Predicate` (doc-tools; needs the row shape to
   admit a presentation, or a sibling collection).
2. **Read from DataHub directly** at registration/refresh time, treating Weaviate as an
   optimisation rather than the source. Cheaper to land, but it puts a DataHub dependency on
   the presentation path and should be weighed against the engine-side symmetry that motivated
   the ruling.

**Recorded rather than chosen, because picking here would repeat the mistake this packet
exists to document: building on an assumed topology.**

## RULED 2026-08-21 — the row shape, and why `endpoint_url` stays empty

The sync repair is the convergent fix; reading DataHub directly from the selector is a detour
that becomes debt. It would put a catalog API call **inside the render decision path** —
latency on every answer, a new runtime dependency for Engine F, and DataHub load-bearing at
request time for nothing else. More decisively: the ruling's point was ONE SUBSTRATE FOR ALL
REGISTRATIONS, and a DataHub-direct read is a SECOND READ PATH WEARING THE GRAPH'S CLOTHES —
the two-masters shape again, the day the sync gets fixed anyway.

### Why a presentation has no endpoint — the question the shape turns on

`endpoint_url` on a verb row is **the callable-ness of the thing.** When Engine A registers
`mesh:lookupOwnership` with `endpoint_url: http://engine-a:8081/execute`, that URL is where
the mesh GOES TO INVOKE the capability. The registrant is a server at a stable address,
waiting to be called, and routing writes the address down so dispatch knows where to send work.

**A presentation inverts every part of that.** `ChartWidget rendersAs mesh:PeriodCostSeries`
does not mean "call this URL to get a chart rendered." Nobody dispatches to the UI — the UI
ASKED THE QUESTION and is already holding the answer's socket. The renderer is not a service
at an address; it is JavaScript in whichever browser tab initiated the request. There is no URL
where the mesh could POST a payload and receive rendering. **The endpoint is the requesting
client itself, reached by REPLYING, not by CALLING.**

So the triple's honest content is: *a frontend of this identity, currently registered, can
render this output type under this contract.* Identity and contract, no address — because the
transport back to the renderer is the response channel that already exists.

### `frontend_id` is doing the endpoint's JOB, in the other direction

A verb's `endpoint_url` answers **"where do I send work?"**
A presentation's `frontend_id` answers **"whose reply channel does this decision bind to?"**

Both are the registrant's identity-for-dispatch; one is an ADDRESS, the other a KEY. That
near-symmetry is why the verb-shaped row ALMOST fits — and the mismatch is exactly the field
where the analogy breaks.

**Do not stuff a placeholder URL into `endpoint_url`** (the UI's public origin, say). The row
would parse and would mean nothing: nothing ever calls it, and the first person to treat it as
callable inherits a lie. That is [[a-borrowed-name-is-a-claim]] in schema form — **a field
nobody calls is a claim nobody audits.**

### The proposed shape

    frontend_id, subject_uri (archetype), output_uri, contract_version

— the key that scopes selection, the two ends of the triple, and the version the envelope
stamps. Structurally a SIBLING of the verb row with `endpoint_url` swapped for `frontend_id`,
which argues for a discriminated row type in `Predicate` or a small parallel collection, and
AGAINST forcing it into the verb shape with a placeholder.

**Sequencing is unchanged:** confirm the drop mechanism in doc-tools FIRST, then propose the
shape, then fix. B's read path resumes only when a `rendersAs` row exists in Weaviate for a
registered presentation — the substrate proves it can carry the data before anything builds on
reading it.

### Footnote for the far future, and it is a real discriminator

If a SERVER-SIDE renderer ever exists — headless chart generation for a mailbox path — **that
one has a real endpoint and registers verb-shaped**, because it genuinely is a callable
service. The distinction is not "presentation vs verb"; it is **"reached by calling vs reached
by replying"**, and today's UIs are all the second kind. A future row with both a
`frontend_id` and an `endpoint_url` is not a contradiction to resolve — it is two different
species that happen to share a table.

## Definition of done — a DEPLOYED witness, not a green suite

**The rule this packet exists to enforce:** an arc whose claim is about deployed behaviour
closes on a deployed witness. Item 1 waited for the live UI witness; this arc did not, because
the suite was thorough enough to feel like enough — thoroughness on one axis hiding absence on
another.

So: **a TWO-PROCESS witness.** cortex-ui registers through cortex-bff; a `/render_ui` call to
presentation-agent selects from that menu and reports `presentation_source: "registered"` with
a `selection_basis` of `output_uri+payload`. Both fields, per ADR-0042 §5 — `presentation_source`
alone says a menu was consulted, not that your output type was found on it.
