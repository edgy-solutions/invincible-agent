# B0 — Docs / Tech-Manuals Phase, Step-0 Spec

**Status:** Draft for review. No code lands from this until the Session-2
TTL→Neo4j DAG fix proves out (see §0). This is the requirements artifact —
the question inventory and class skeleton are the spec; the ingest invariants
are the contract.

---

## §0. Hard prerequisite (read first)

`mil_extension.ttl` is a TTL-sourced domain. The Session-1 finding is that
the canonical pipeline's TTL→Neo4j materialization is **unwired**
(`sync_jena_to_neo4j` depends on the XML path, not `ingest_ontology_to_jena`).
Until Session 2 fixes that, **B1 cannot land** — the docs classes would reach
Jena and Weaviate but never Neo4j, and every docs verb would Contract-D-reject
on a fresh registration. So:

- B0 (this spec) can be drafted and reviewed now — it's paper.
- B1 (author + ingest `mil_extension.ttl`) is **gated on the TTL→Neo4j fix**.
- The docs phase is, conveniently, the strongest *reason* the fix matters:
  it's the first big TTL-sourced domain after the fix, and its first ingest
  is itself a fresh-bootstrap test of that fix.

---

## §1. The core architectural rule (the thing that must not be violated)

**Format ingestion writes INSTANCES and CHUNKS only. It NEVER writes
OntologyClass nodes or touches the resolver candidate pool.**

The classes (document *kinds*) come from a thin authored TTL (TBox, §3). The
documents themselves — a specific manual, a specific data module with its DMC —
are instances (ABox), classified deterministically by their own metadata, with
**no LLM anywhere in the classification path**. This is the same TBox/ABox
boundary from the routing arc, now applied to ingestion:

| Layer | What | Where | How populated |
|---|---|---|---|
| TBox (kinds) | `mil:DataModule` + content kinds (`mil:FaultIsolationDataModule`, …) | OntologyClass in Neo4j + Jena | authored TTL via canonical pipeline (§3) |
| ABox (instances) | "TM 1-1520-237-23, DMC-…-520A-A" | `:Procedure`/`:Figure`/instance nodes in Neo4j | format ingest, deterministic (§4) |
| Chunks | the searchable text/figures | Weaviate `DocumentChunks` | format ingest |

Why deterministic-not-LLM: S1000D over-structures everything. The info code
*is* the class assignment; the DMC *is* the instance identity; applicability
*is* the equipment cross-link. There is nothing to infer, so there is no
extractor-hallucination surface — the exact property the Mem0 arc was about.
The formats' rigidity becomes the provenance.

---

## §2. Question inventory (the spec — fill from REAL work questions before building)

Each row decomposes a real user question into subject / verb / backend. **This
list is the demand signal**: a document kind enters the resolver pool (§3) only
when a question needs it AND a verb covers it. Rows marked ⚠ are placeholders —
replace with actual questions your work users ask before B1.

| # | Question shape | Subject (resolves to) | Verb | Backend | Notes |
|---|---|---|---|---|---|
| Q1 | "Search the technical manuals for fuel system diagnostics" | `mil:DataModule` (or its kinds) | `mesh:retrieveKnowledge` | Engine W | **Already routes today** via the manuals baseline. The control. |
| Q2 | "Show me the fault isolation procedure for the APU" | `mil:FaultIsolationDataModule` ⚠ | needs verb (Wave-3-style) | Engine W/E | kind-class declared; enters pool only with verb coverage |
| Q3 | "What's the IPD / parts breakdown for part X" | `mil:IllustratedPartsDataModule` ⚠ | needs verb | Engine W | |
| Q4 | "Tell me about DMC-AE-A-32-…-520A-A" | (instance) | **instance resolution** | DMC phone book | §5 — name, not kind; goes through `resolveInstance` |
| Q5 | "What procedure covers replacing the hydraulic pump on tail 42" | (instance → `mil:hasPart` cross-link) | **composition** | multi-hop | ADR-0011 territory; the join is `mil:hasPart` (typed in the TTL). Canary row, expected-generalist until composition lands |
| Q6 ⚠ | _(real work question)_ | | | | |
| Q7 ⚠ | _(real work question)_ | | | | |

Two rows are structurally important and not optional:

- **Q4 is the DMC phone-book row.** "Tell me about DMC-…" is a *name*, not a
  kind — same shape as "tell me about gold.sales.revenue_summary." It resolves
  through the instance-resolution layer (the DMC phone book, §5), not class
  resolution. Predict: instance-resolved, provenance shows the DMC provider.
- **Q5 is the composition canary.** "Procedure for the part that's failing" is
  a genuine instance→equipment→procedure chain — ADR-0011's revisit trigger.
  It is an **expected-generalist** row until composition lands. It exists to
  *document the gap as known* and to be the tripwire when chain-shaped
  questions start appearing in fallback telemetry.

---

## §3. The class skeleton — `mil_extension.ttl` (TBox) — SHIPPED, VALIDATED

The ontology exists and parses (74 triples, `mil_extension.ttl`). Namespace
`mil: <http://edgy-solutions.com/ontology/mil#>`, **authored full-IRI from day
one** (so it never joins A3's compact-form debt). It bridges S1000D, IADS, and
DITA onto the IOF backbone. **Not ingested anywhere yet — trailblazing.**

The design decision that shapes everything: **two orthogonal axes.**

### Axis 1 — SOURCE FORMAT (ingest provenance, NOT routing)

How a module was authored. Siblings under `iof:InformationContentEntity`,
distinguished by parser/source. These exist for lineage and are **held out of
the resolver candidate pool** — they are not routing subjects.

- `mil:DataModule` (S1000D) — also the root of the content hierarchy below.
- `mil:IadsNode` (IADS XML)
- `mil:DitaNode` (DITA task/topic)

### Axis 2 — CONTENT KIND (the routing-visible hierarchy)

What the content IS. Subclasses of `mil:DataModule`, derived deterministically
from the S1000D information code (`mil:hasInfoCode`). These are the subjects
user questions resolve to.

- `mil:DescriptiveDataModule` (info code 0xx) — "what it is."
- `mil:ProcedureDataModule` (2xx/5xx/7xx) — "how to do it." Maps onto the
  existing `:Procedure`/`:ManufacturingStep` instance labels (§4 mapping).
- `mil:FaultIsolationDataModule` (4xx) — "why it's broken / find the fault."
  Engine E's diagnostic lane.
- `mil:IllustratedPartsDataModule` (9xx) — "what parts / IPD."
- `mil:Diagram` — figures, schematics, wiring.

An instance ends up `INSTANCE_OF` its **content kind** (Axis 2, for routing)
and carries `mil:hasInfoCode` plus a source-format marker (Axis 1, for
lineage). The info code is the deterministic bridge between the two axes — read
it at ingest, assign the content kind, no model inference.

> ⚠ **Confirm the info-code ranges** (0xx/2xx/4xx/5xx/7xx/9xx → kind) against
> the actual S1000D issue in use. The families are standardized but boundaries
> shift issue-to-issue. The `mil:hasInfoCode` definition in the TTL encodes the
> mapping; that's the single source to verify and, if needed, correct.

### Material artifacts + composition join keys

- `mil:Tool`, `mil:Part` (under `iof:MaterialArtifact`) — instances cross-
  linked to data modules.
- `mil:requiresTool`, `mil:hasPart` (object properties) — **the join keys the
  composition layer (ADR-0011) will walk.** "What procedure covers replacing
  part X" traverses `mil:hasPart`; "what does this procedure require"
  traverses `mil:requiresTool`. Typed now, so Q5's composition is over named
  predicates, not hand-waved edges. This is the plumbing for the §2 canary.

### Bulk-declare decision (made) + the rule it must respect

**Decision: bulk-declare** the full content-kind hierarchy now from the
standardized info-code taxonomy (rather than grow-on-demand). Defensible here
because the taxonomy is a published standard, not an ad-hoc domain.

**But the Wave-3 rule still binds:** declaring a kind-class in the TBox does
NOT add it to the resolver candidate pool. A content kind becomes *resolvable*
only when a verb is typed against it (§2, B4). Until then it exists for
instance `INSTANCE_OF` edges and future coverage, but is **held out of
Weaviate's candidate pool** — same discipline as the held-out
idp:Column/Pipeline/Job. Skipping this reintroduces the zero-compatible-verbs
→ silent-generalist failure.

Concretely on day one: only the kind on the already-routing
`retrieveKnowledge` path (the Q1 baseline) is pool-ready. `ProcedureDataModule`,
`FaultIsolationDataModule`, etc. are declared and instance-linked but
pool-held until B4 gives each a verb.

Optional later: **DoCO** (SPAR, CC-BY) for sub-document component structure
(section/figure/caption typing) if chunk-level structure earns it. Not Wave-1.

---

## §4. Ingest design (ABox) — deterministic, guarded

Format ingest (S1000D XML, DITA, MIL-STD-40051) maps to instances + chunks:

1. **Class assignment from metadata, not text.** Read the info code → map to
   the §3 kind-class. Deterministic table, no LLM. A DMC whose info code is a
   fault-isolation code becomes `INSTANCE_OF mil:FaultIsolationDataModule`,
   full stop.
2. **Instance identity = DMC.** The Data Module Code is the instance IRI. One
   DMC, one instance node. Idempotent on re-ingest (MERGE by DMC).
3. **Equipment cross-links from applicability.** S1000D applicability + parts
   references → `mil:hasPart` / `mil:requiresTool` edges to `mil:Part` /
   `mil:Tool` instances, and SNS-based links to equipment instances
   (`urn:instance:…`). These are the **typed** join keys (declared in the TTL)
   that make Q5's composition possible later — the edges exist as data, over
   named predicates, even before the composition verb does.
4. **Chunks to Weaviate `DocumentChunks`** with class + DMC metadata, for
   Engine W's `retrieveKnowledge`.

**Instance-label ↔ class-name mapping (the one decision inside B2):** the
prime script's existing instance constraints (`:Procedure`,
`:ManufacturingStep`, `:Figure`) and the §3 kind-classes
(`mil:ProcedureDataModule`, etc.) must be deliberately mapped — an explicit
`INSTANCE_OF` correspondence — or the layers drift (the instance graph says
`Procedure`, the concept graph says `ProcedureDataModule`, and nobody
remembers if they're the same). Decide and write the mapping; don't let it be
incidental.

### Guarded invariants (standing tests, as load-bearing as the pipeline)

- **G1 — ingest never writes TBox.** A test that fails if the format-ingest
  path writes any `OntologyClass` node or any row to the resolver candidate
  pool. This is the §1 rule made enforceable; it's the most important guard
  in the phase.
- **G2 — every ingested instance has an `INSTANCE_OF` edge to a declared
  kind-class.** No orphan instances; no instances pointing at phantom classes.
- **G3 — class assignment is deterministic.** Same DMC → same class, no model
  call in the path (assert by construction / code-path test).

---

## §5. The DMC phone book — instance-resolution provider #3

The docs pipeline registers `mesh:resolveInstance` over DMC/document-instance
identifiers, through the gateway, exactly as Engine D (catalog assets) and
Engine E (equipment instances) did. Per the instance-resolution recipe:

- **Hard criterion: zero Engine O changes.** Third application of the
  generality gate. If onboarding the DMC phone book requires touching the
  router, the instance-resolution design failed — stop and report.
- Ship its known-good probe (a real DMC → its kind-class) AND a router-side
  integration probe (the DMC resolves through `/resolve` end-to-end with
  `instance_resolved=true`, provider = the docs provider) on day one. The
  router-side probe is non-optional — the positive-control amendment requires
  the integrated-path test, not just the component.
- This is what makes Q4 work, and it's why "show me DMC-…" needs no new router
  logic: it's the phone-book pattern with a third provider.

---

## §6. Build order (each gated on the prior; B1 gated on §0)

1. **Session 2's TTL→Neo4j fix lands** (prerequisite — not part of this phase
   but blocking it).
2. **B0 review** — fill the §2 inventory with real work questions; confirm the
   §3 info-code families against the live S1000D edition; decide the §4
   instance-label↔class mapping.
3. **B1 — ingest `mil_extension.ttl`** (already authored, full-IRI, validated —
   74 triples) via the now-wired canonical pipeline. Intermediate gate:
   content-kind classes resolve in Neo4j at full-IRI form. Predict: Q1 still
   routes (control); new kinds present in TBox but **held out of the resolver
   pool** (no verbs yet). **This ingest doubles as the second fresh-bootstrap
   test of the Session-2 fix** — a never-before-ingested TTL-only domain is the
   sharpest "can the pipeline materialize a TTL-only class" assertion.
4. **B2 — ingest pipeline** with G1/G2/G3 guards. A real manual ingests as
   instances + chunks; G1 stays green (nothing hit the TBox).
5. **B3 — DMC phone book** as provider #3, zero router changes, both probes.
   Q4 flips to instance-resolved.
6. **B4 — kind verbs** only as §2 questions demand them (Q2/Q3), each behind
   the hierarchy-context fix if inheritance is involved.
7. **B5 — matrix expansion**: the §2 rows become matrix rows with predictions,
   including Q5 as the expected-generalist composition canary.

---

## §7. Out of scope / triggers

- **DoCO sub-document structure** — only if chunk-level component typing earns
  it; not Wave-1.
- **Composition (ADR-0011)** — Q5 is the canary, not the build. Trigger:
  chain-shaped questions appearing in fallback telemetry. Instance resolution
  is already hop-zero, so the on-ramp exists.
- **Any LLM in the ingest/classification path** — forbidden by §1. If a format
  ever lacks deterministic metadata for classification, that's a finding to
  surface, not a place to insert a model.
- **Adding kind-classes to the resolver pool without verb coverage** —
  forbidden by §3 / the Wave-3 lesson.

---

## §8. Why this is low-risk despite being a big phase

Every piece reuses a proven pattern: the thin-extension TTL (run three times),
the canonical pipeline (about to be made whole), the gateway registration
(v0.2, atomic), the instance-resolution provider (gate 6 proved generality),
the standing-guard discipline (catches G1 violations automatically). The only
genuinely new work is the deterministic info-code→class mapping and the chunk
ingest — and both are mechanical, metadata-driven, model-free. The formats'
structure does the hard part. The architecture has been clearing runway for
exactly this.
