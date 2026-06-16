# ADR-0020 — Structural disambiguation at weak vocabulary-anchor boundaries

**Status:** Proposed
**Date:** 2026-06-16
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) — the predicate
    graph and "a tool *is* a predicate." This ADR adds a second
    traversal axis to the compat-walk that runs over that graph.
  - [ADR-0008](ADR-0008-routing-fallback-policy.md) — fallback policy.
    The composition-walk this ADR proposes does NOT add a new fallback
    reason; it changes what the constrained verb enum contains *before*
    fallback runs.
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — "resolve
    nouns, not callers." This ADR stays inside the noun-resolution
    frame; it does not reintroduce persona/intent classification.
  - [ADR-0011](ADR-0011-multi-spo-routing.md) — multi-SPO / chained
    routing (deferred). Owns the same composition edges this ADR
    traverses, for a different purpose. Coherence note below.
  - [ADR-0018](ADR-0018-symmetric-spo-routing.md) — Neo4j as the
    (S,P) compatibility reasoner. This ADR extends the Cypher walk
    that reasoner runs.
  - [ADR-0019](ADR-0019-ontology-routing-substrate.md) — the ontology
    is the routing substrate; Contract A teeth keep the LLM inside
    the substrate-derived candidate enum. This ADR preserves that
    discipline — the new traversal stays mechanical; the LLM never
    reasons about the hierarchy.

## Context

### The frame

Routing today resolves a subject from a flat candidate pool of
`:OntologyClass` nodes by semantic/lexical match (`/resolve`), then
walks `subClassOf*` from that subject to enumerate verbs compatible
with it (`/find_compatible_verbs`). The verb the LLM sees is
constrained to that Cypher-derived set — Contract A teeth (ADR-0019).
This pattern works when a content kind has a strong, distinctive
vocabulary anchor in its `:OntologyClass` definition; it is **fuzzy
where two kinds share weak or overlapping vocabulary**.

### The concrete symptom — the trigger

During B4 verb-typing (typing routing verbs against the four mil:*
procedural-content classes — `mil:FaultIsolationDataModule`,
`mil:ProcedureDataModule`, `mil:IllustratedPartsDataModule`,
`mil:DescriptiveDataModule`), the query *"What are the steps to
install the boom?"* resolved to `mro:WorkInstruction` at 0.95
confidence instead of the expected `mil:ProcedureDataModule`.

This was diagnosed not as a routing bug but as a **container/content
ambiguity at the lexical layer**:

- `mil:ProcedureDataModule` is the **document** (the S1000D/40051
  authored data module — what tech writers manage).
- `mro:WorkInstruction` is the **content** (the actual procedural
  steps — what maintainers execute).

The data module *contains* the work instruction. They are two layers
of the same procedure at different granularities, not flat siblings.
The original maintainer-framed question ("steps to install...")
correctly named the content layer; a tech-writer-framed phrasing
("What procedure data module covers boom installation?") correctly
names the document layer. Both resolutions are coherent for their
question's framing — and the resolver picks between them by lexical
coincidence, not by structure. There is no declared relationship in
`mil_extension.ttl` connecting `mil:ProcedureDataModule` and
`mro:WorkInstruction`; they live in different namespaces.

### Why this matters now (and why it doesn't, today)

Today the lexical anchors hold: the full routing matrix runs 22/22
across the four B4 verbs after multi-phrasing probe scans. Single-
audience usage — maintainer queries phrased as maintainers phrase
them, tech-writer queries phrased as tech writers phrase them —
routes to the right layer.

The structural fix becomes load-bearing when **both audiences are
simultaneously live** with their natural phrasings on the same
substrate, with the same predicates. At that point the lexical
coincidence runs out: a query phrased ambiguously will resolve to
whichever class's vocabulary anchor happens to be strongest, which
depends on hand-tuning state, not on what the user actually wants.
That is the failure mode this ADR addresses, in advance of that
condition arriving.

## Evidence — the four-class lexical map (B4 verb-typing probe data)

The B4 verb-typing arc gave each of the four mil:* procedural-content
classes a verb edge, plus a **multi-phrasing probe scan** (3–5
phrasings per verb, surfacing which lexical cues drive subject
resolution). This is the evidence the design decisions below reason
from; it is captured fully here because it is otherwise expensive to
reconstruct.

### Per-class summary

| Class | Verb | Engine | Vocabulary anchor | Anchor strength | Probe-scan finding |
|---|---|---|---|---|---|
| `mil:FaultIsolationDataModule` | `mesh:retrieveKnowledge` | W | "fault", "diagnose", "find the fault" | Medium | "fault" + "diagnose" route cleanly; "describe the troubleshooting procedure" leaks across to `mro:WorkInstruction` (WI's hand-tuned "describe procedure" hint catches it) |
| `mil:ProcedureDataModule` | `mesh:queryKnowledgeGraph` | E | "procedure", "data module", "S1000D" | Weak | "procedure" alone loses to WorkInstruction; ships clean only on tech-writer multi-word phrasings ("procedure data module covers ...") |
| `mil:IllustratedPartsDataModule` | `mesh:retrieveKnowledge` | W | "parts", "illustrated", "breakdown", "IPD" | Strong | Holds against "describe" cue; "part number" correctly routes to `mil:Part` instance (kind-vs-instance behavior, not a misroute) |
| `mil:DescriptiveDataModule` | `mesh:retrieveKnowledge` | W | "what is", "tell me about", "describe" | Medium-and-over-broad | Genuine "what is" queries route cleanly; three leak-test probes designed to measure DDM over-attraction all HOLD against DDM |

### Verb 4 leak-test probes (the over-attraction measurement)

DDM was the predicted messy keystone — "describe" is the most common
query verb in English. Verb 4's probe scan was deliberately
constructed with three leak-test probes whose *correct* target was
NOT DDM but whose phrasing used "describe" framing. The results
size the over-attraction risk.

| Probe | Phrasing | Correct target | Resolved → | Verdict |
|---|---|---|---|---|
| L3 | "Describe how to install the boom" | `mro:WorkInstruction` or `mil:ProcedureDataModule` | `mro:WorkInstruction` @ 0.85 | **HELD** against DDM |
| L4 | "Describe the parts of the boom assembly" | `mil:IllustratedPartsDataModule` | `mil:IllustratedPartsDataModule` @ 0.95 | **HELD** against DDM (IPD's "parts" anchor wins) |
| L5 | "Describe the troubleshooting procedure for the helmet" | `mil:FaultIsolationDataModule` or `mro:WorkInstruction` | `mro:WorkInstruction` @ 0.85 | HELD against DDM, but **leaked across FI↔WI** (a separate weak boundary, not DDM's fault) |

### The bounded finding

**DDM over-attraction is bounded.** Strong-anchor classes (IPD's
"parts," WorkInstruction's hand-tuned hints) defeat "describe" alone.
The fuzziness is localized to specific class pairs — it is **not** a
general "describe-pulls-everything-to-DDM" failure that would
require redesigning the whole routing layer.

### The three named weak boundaries

These are the specific class pairs where lexical disambiguation does
not suffice and where structural disambiguation will earn its keep
when it lands. Everything outside these three pairs resolves
correctly by lexical anchor today.

1. **`mil:ProcedureDataModule` ↔ `mro:WorkInstruction` (container/content).**
   The original B4 verb 2 finding. The data module contains the work
   instruction; the relationship is semantically true but
   structurally unmodeled. Today: maintainer phrasing "steps to
   install" wins `mro:WorkInstruction`; tech-writer phrasing
   "procedure data module covers" wins `mil:ProcedureDataModule`.
   Disambiguation by lexical coincidence works only as long as no
   maintainer asks about modules and no writer asks about steps.

2. **`mil:ProcedureDataModule` ↔ `mil:DescriptiveDataModule`.**
   Verb 2 probe 1 finding ("Describe the procedure data module for
   the microphone boom installation" → `mil:DescriptiveDataModule`
   at 0.86). PDM's "procedure" anchor is too weak to hold against
   DDM's "describe" cue when both appear together. Asymmetric with
   IPD: "describe the parts data module" (verb 3 probe P4) holds on
   IPD because IPD's "parts" anchor is strong; PDM has no equivalent
   distinctive cue.

3. **`mil:FaultIsolationDataModule` ↔ `mro:WorkInstruction`.**
   Verb 4 leak probe L5 ("Describe the troubleshooting procedure
   for the helmet" → `mro:WorkInstruction` at 0.85). FI ships
   demo-clean for "fault" + "diagnose" phrasings; if a real user
   asks "describe the troubleshooting procedure," WorkInstruction's
   hand-tuned "describe procedure" hint catches it instead.

### The document↔content/instance duality — confirmed as a general pattern

Three independent observations during B4 confirm that the
document↔content/instance distinction is a **general pattern across
the manuals ontology**, not a one-off PDM↔WI quirk. This is the
keystone evidence for the ADR's mechanism, because it identifies the
shape of the structural fix.

1. **Verb 2 — PDM↔WorkInstruction container/content.** The document
   contains the content. (The original finding.)

2. **Verb 3 probe P3 — "What is the part number for the boom
   cable?" → `mil:Part` instance, not IPD document.** "Part number"
   pulls to the Part-instance class, not to the parts-breakdown
   document. Kind-vs-instance behavior at the lexical layer; the
   "instance side" of an IPD document is the Part it lists.

3. **Verb 4 — "Describe procedure TEST-1234 and show me its
   diagram" routes via `mesh:resolveInstance`** (Engine E exact-
   matches TEST-1234 as a Test Procedure 1234 instance at score
   1.0). The class-vocabulary contest is preempted entirely
   because the query named an identifier.

Generalized: every document kind has its instance-layer counterpart,
and queries naturally route to whichever layer they actually ask
about. Where named identifiers are present, the **instance-resolution
fan-out** handles the disambiguation. Where they are absent, lexical
anchors handle it — except at the three named weak boundaries above.

## The key insight — what makes this ADR low-risk

**The system already insulates named-identifier queries onto the
right layer.** It does this via the instance-resolution fan-out: a
named DMC, wpno, part number, or procedure code fires
`mesh:resolveInstance` (Engine E + Engine E's DMC capability +
Engine D, all called in parallel with a structured abstention
contract) *before* any class-vocabulary contest happens. The
class-vocabulary contest only runs when no identifier was named.

This means **this ADR is not inventing a structural-disambiguation
mechanism.** The system already exhibits one, for named queries.

The ADR's job is to **generalize that insulation to unnamed or
described queries at the three weak boundaries.** The mechanism for
unnamed queries cannot be instance resolution (there is no identifier
to look up). But it can mirror the principle: when a query's subject
is ambiguous between a document and its content (or between two
nearby content kinds at a known weak boundary), give the routing
layer a way to *reach the verbs of the related layer through a
structural relationship*, rather than requiring the LLM to guess at
the layer from lexical cues.

That is a small, additive, scoped extension of the existing
compat-walk — not a redesign.

## Decision

Add a **second traversal axis** to `/find_compatible_verbs`'s Cypher
walk.

Today the walk traverses one edge type — `subClassOf*` (inheritance),
capped at hop depth 5. The set it returns is the union of verbs typed
against the subject's class and its ancestors.

The decision is to **also traverse declared composition edges**
(`mil:hasContent`, `mil:hasPart`, and analogous named relationships)
so that verbs typed against the *related layer* are reachable from a
subject when the structural relationship between the two layers is
declared in the TTL.

Three properties of this decision keep the change low-blast-radius
and preserve existing soundness:

1. **The traversal is mechanical and Cypher-deterministic.** The LLM
   still receives a flat, substrate-constrained candidate verb list.
   The safety veto stays in the Cypher layer (Contract A teeth,
   ADR-0019); the LLM never reasons about the document↔content
   hierarchy. No new model-trust surface.

2. **The traversal is scoped to the named weak-boundary relationships
   only.** This is **not** a general "walk all object properties."
   Only the relationships explicitly declared as composition
   (initially: `mil:hasContent` between `mil:ProcedureDataModule` and
   `mro:WorkInstruction`; analogous edges for the other named weak
   boundaries) participate. Everything else stays where it is.

3. **The TTL declares the relationship and the substrate enforces it.**
   `mil_extension.ttl` gets a small set of new `owl:ObjectProperty`
   declarations naming the composition edges, with `rdfs:domain` and
   `rdfs:range`. The compat-walk reads from the same Neo4j substrate
   the noun graph already does (ADR-0019's noun-graph contract). No
   new data path.

The verb the LLM ultimately sees in `/classify_predicate`'s enum is
still the result of the Cypher walk over the substrate, deduped to a
flat list. The structural disambiguation is invisible to the LLM by
construction.

## The three design parameters

These are the actual decisions the implementing session has to make,
with their failure modes named so the implementing scope is clear.

### 1. Direction — container→content, content→container, or both

Determines which verbs become reachable from which subjects:

- **Container→content** (e.g. `mil:ProcedureDataModule` reaches
  `mro:WorkInstruction`'s verbs): a tech-writer-framed question can
  also dispatch to the content-layer verb. Useful when the user
  asks about the module and answering correctly requires the steps.
- **Content→container** (e.g. `mro:WorkInstruction` reaches
  `mil:ProcedureDataModule`'s verbs): a maintainer-framed question
  can also dispatch to the document-layer verb. Useful when the
  user asks about steps and answering correctly requires the data
  module's context (DMC, applicability, supersession).
- **Both**: full bidirectional reach.

**Failure modes**:
- *Wrong-direction-only chosen* — the dual-audience case this ADR
  was meant to insulate doesn't actually solve, because verbs aren't
  reachable in the question shape the user is using.
- *Both-direction chosen carelessly* — the verb enum doubles for
  every query that touches either layer, and the dedup rule
  (parameter 3) becomes load-bearing for correctness, not just
  polish.

**Soft recommendation (flagged here for the implementing session,
not decided)**: start with **container→content**. The container-
asking case is the tech-writer audience, which is the smaller and
more identifiable cohort; reaching content verbs from the container
is the broader insulation. The reverse direction can be added later
if maintainer-asking-about-module evidence appears in the field.

### 2. Depth — bounded, explicitly UNLIKE inheritance's `subClassOf*`

The composition traversal is **bounded to one hop** (or, more
precisely, to the depth named in the TTL's relationship declaration —
which is currently always one for the three weak boundaries this
ADR addresses).

This is **explicitly unlike** `subClassOf*`'s unbounded traversal.
Inheritance is safely transitive for routing — a verb typed against
`mro:Procedure` correctly reaches all its `mro:ProcedureStep`
subclasses; that is exactly the substitutability inheritance models.
**"Part-of" is not safely transitive for routing.** A
`mil:ProcedureDataModule` *contains* steps; a step *references* a
tool; a tool *has* parts. Walking that chain unbounded means every
"data module" query exposes verbs for steps, tools, parts, and
diagrams — the LLM sees an enum of dozens, classification accuracy
collapses, and over-routing risk goes from "bounded" (today's matrix
22/22) to "open."

**Failure modes**:
- *Unbounded composition traversal* — described above. The most
  damaging failure mode this ADR could ship.
- *Right depth but wrong scope* — if the bounded depth is one but
  composition edges proliferate across the TTL beyond the three
  weak boundaries this ADR addresses, the same flooding happens at
  the breadth axis instead of the depth axis. The scoping in the
  Decision section is **load-bearing**; the implementing session
  must not silently expand the participating edges beyond the
  named set.

### 3. Dedup precedence — inheritance-reached vs composition-reached verbs

When the same `verb_iri` is reachable via both an inheritance path
and a composition path (the same verb is typed against an ancestor
*and* against a related layer), the compat-walk's existing dedup
rule has to extend to break the tie.

The existing rule today: when the same `verb_iri` appears multiple
times in the walk's output, the row with the **most-specific
`input_uri`** (the closest ancestor in `subClassOf*`) wins. The LLM
sees a flat deduped enum; the traversal-axis provenance is not
exposed.

The extension: when an inheritance-reached row and a
composition-reached row share a `verb_iri` and there is no clean
most-specific-`input_uri` winner (because one comes from a
`subClassOf*` path and one from a `hasContent`/`hasPart` path),
**pick the inheritance row.** Inheritance is the more-grounded
reachability — the subject *is* an instance of the ancestor; with
composition, the subject *relates to* the related class. The LLM
still sees a flat deduped enum with no provenance for which
traversal axis produced each verb.

**Failure modes**:
- *No dedup* — the LLM sees duplicate enum entries and either
  refuses or picks arbitrarily; the constrained-enum guarantee
  breaks.
- *Wrong precedence* — the composition-reached verb wins over the
  inheritance-reached one, and queries that should route to the
  subject's own-layer verb instead route to the related layer's
  verb. Subtle and hard to detect from logs because the dispatch
  endpoint will often differ from the intended one but still be
  *a* valid endpoint.

## Non-urgency and the trigger to revisit

This ADR ships as **Proposed**, not implemented.

**Today**: matrix 22/22 across four B4 verbs (commits `186fe11`,
`77b443e`, `865497d`, `00c8161`). Tech-writer-framed and
maintainer-framed phrasings each route correctly to their own
layer's verb. The lexical-anchor approach (strong-anchor classes
hold their own boundaries; the three named weak boundaries are
stable because the audience-mix is single-shape in current usage) is
doing the disambiguation work, and the structural fix would be
solving a problem the matrix does not yet exhibit.

The structural fix becomes load-bearing when one of the following
triggers fires:

1. **Real-usage evidence of weak-boundary misroutes.** A demo
   session, a telemetry sample, or a regression spike shows queries
   where one of the three named weak boundaries failed in practice
   — e.g. a maintainer's "steps to install" got dispatched to the
   document layer (wrong for the framing), or "describe the
   troubleshooting procedure" landed on `mro:WorkInstruction` when
   the user actually wanted fault-isolation diagnostic content.

2. **The manufacturing or multi-audience track going live.** Tech
   writers and maintainers both querying the same substrate with
   their natural phrasings turns today's bounded-fuzziness into an
   active correctness problem at the three weak boundaries.

3. **A new weak boundary surfaces** during verb-typing of another
   content-kind family. The multi-phrasing probe gate (now a
   standing rule from B4 verb 3 forward) will surface it; if a
   fourth weak boundary appears, the implementing session can
   address all four in one structural pass rather than chasing them
   incrementally.

In the interim, the four B4 verb commits demonstrate the
lexical-anchor approach holding; the multi-phrasing probe gate
continues to surface new evidence as new verbs are typed.

## Coherence with ADR-0011 (multi-SPO / composition routing)

ADR-0011 defers chained-SPO routing (multi-hop traversal across
object properties) until the operational case for it emerges. The
mechanism this ADR proposes — Cypher composition-edge traversal in
`/find_compatible_verbs` — **traverses the same `mil:hasContent` /
`mil:hasPart` edges** that ADR-0011's chain-query composition (the
Q5 canary) will reuse when it lands.

The two features are distinct:

- **This ADR (ADR-0020)** makes verbs of a *related layer* reachable
  from a subject. Single-hop, single-SPO. The routing layer's
  disambiguation gets richer.
- **ADR-0011** chains *multiple SPOs* across the same edges.
  Multi-hop, multi-SPO. The supervisor's planning layer gets
  richer.

They share substrate. The TTL declarations for composition edges
(`mil:hasContent`, `mil:hasPart`) are written *once* and consumed
by both features. If this ADR is implemented before ADR-0011, the
TTL declarations should be shaped to be reusable for chain
traversal (properly named `owl:ObjectProperty` with `rdfs:domain`
and `rdfs:range`, **not** bolted-on flags or out-of-band annotations).
If ADR-0011 is implemented first, this ADR's compat-walk extension
reads the same edges from the same substrate; the implementing
session for whichever lands first should treat the shared-substrate
concern as a **hard design constraint**, not a coincidence to be
revisited later.

Flag explicitly: do not let either feature ship in a way that names
the composition edges differently, scopes them differently in the
TTL, or assumes one feature owns them. The edges are substrate;
both features are readers.

## Hard scope

This ADR is **the design and the evidence**. It is intentionally not
the implementation.

**Out of scope for this ADR's commit**:
- No changes to `/find_compatible_verbs` or any other Cypher.
- No changes to `mil_extension.ttl` or any other ontology TTL.
- No new substrate edges in Neo4j or Weaviate.
- No new test cases for the not-yet-implemented composition
  traversal.
- No changes to existing matrix rows or probe scans.

**The implementing session** (a future, separately-scoped piece of
work) starts by reading this ADR and:

1. Confirms the trigger condition (real-usage misroute evidence, OR
   multi-audience track going live, OR a fourth weak boundary
   surfacing) — implementation without a trigger is premature.
2. Decides the three design parameters (Direction, Depth scope,
   Dedup precedence) against the trigger condition's actual shape.
3. Writes the TTL `owl:ObjectProperty` declarations for the
   composition edges scoped to the named weak boundaries.
4. Extends `/find_compatible_verbs`'s Cypher with the second
   traversal axis, bounded per parameter 2.
5. Extends the dedup rule per parameter 3.
6. Adds probe-scan rows covering the now-structurally-disambiguated
   weak boundaries, replicating the multi-phrasing-gate discipline
   the B4 verb-typing arc established.
7. Closes ADR-0011's coherence note by reading both ADRs together
   before touching the shared edges.

This ADR's job is to **make the future session inexpensive**: the
four-class lexical map is captured, the three weak boundaries are
named with their evidence, the general pattern (document↔content/
instance duality) is identified across three independent
observations, the mechanism is sketched, and its failure modes are
called out by parameter. None of that needs to be re-derived from
scratch.

Stop at the written document.
