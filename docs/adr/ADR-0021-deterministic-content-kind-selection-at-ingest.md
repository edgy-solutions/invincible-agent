# ADR-0021 — Deterministic content-kind selection at ingest

**Status:** Proposed
**Date:** 2026-06-18
**Deciders:** Platform team
**Related:**
  - [ADR-0019](ADR-0019-ontology-routing-substrate.md) — the substrate frame.
    *Resolve the subject noun; read an edge.* The substrate is authoritative;
    the LLM extracts content into it but never classifies layers or routing.
    This ADR brings the manufacturing ingest path INTO that frame; today it
    sits OUTSIDE because the manufacturing extractor writes a single
    flat `mfg:ManufacturingStep` kind regardless of source and never stamps
    an `INSTANCE_OF` edge.
  - [ADR-0018](ADR-0018-symmetric-spo-routing.md) — symmetric (S, P) routing.
    Verbs reach instances through their class chain. Without an
    `INSTANCE_OF` edge from extracted content to a chartable kind, no
    `mfg:` verb can reach manufacturing content; the routing layer can see
    the kinds but cannot see the instances.
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — "resolve nouns,
    not callers." This ADR extends the same discipline to ingest: do not
    classify *what kind of content this is* with an LLM. The kind comes
    from a deterministic source; the LLM only extracts fields once the
    kind is fixed.
  - [ADR-0006](ADR-0006-datahub-proposal-inbox.md) §Addendum — source
    authority discipline post-v0.2 cutover. The kind-source mapping
    proposed here is a chartable artifact that the same source-authority
    rule governs: it lives in code, is reviewed, and is the only place
    a new kind can be registered.
  - [Manufacturing schema read (banked 2026-06-18)](#) — the (B) finding
    that grounds this ADR: the 32-field `ManufacturingStep` schema has
    NO field whose bounded value set deterministically maps to a `mfg:*`
    content kind. The 5 classification-bearing fields (`process_category`,
    `hazard_class`, `required_cert`, `is_value_added`, `is_safety_critical`)
    describe step *properties*, not the step's *kind*. Manufacturing has
    no structured analog of the S1000D info-code → kind table.

## Context

### The schema read that triggered this ADR

A read of the manufacturing extractor's 32-field `ManufacturingStep` Pydantic
schema (base 18 declared in [manufacturing.baml](../../doc-tools/baml_src/manufacturing.baml)
+ ~14 proprietary overlay fields injected at runtime via TypeBuilder from
the `MANUFACTURING_OVERLAY_SPEC` secret) asked one binary question:

> Does any field deterministically map to a `mfg:*` content kind, or is
> the kind itself only produced by the BAML extractor's classification
> output (the TypeBuilder dynamic enum)?

The answer was **(B), full stop**: no field, base or proprietary, carries
the step's kind. The 5 (C)-bounded fields describe step *properties*
(functional category, hazard, personnel cert, value-add, safety) — not
the step's kind. The ~14 proprietary fields are more *extracted values*
(torques, lot codes, special-process names) — no hidden classification
enum among them.

The wire format confirms: the existing plugin writes every step as
`a mfg:ManufacturingStep` ([manufacturing.py:375](../../doc-tools/doc_tools/plugins/manufacturing.py))
— a single flat kind, no sub-class discrimination, no `INSTANCE_OF`
edge to a chartable target kind.

### Why this is a substrate problem, not a schema problem

The first instinct is to add a `content_kind` field to the schema and
have the LLM populate it. That answer **violates ADR-0009** ("resolve
nouns, not callers") and pushes routing-relevant classification into
the LLM at extraction time — exactly the failure mode ADR-0019 was
written to close.

The substrate-discipline answer is the opposite: the content kind is a
**routing concern**, not an **extraction concern**. The kind lives at the
ingest layer where it can be sourced deterministically, then dictates
which extractor configuration runs. The LLM then extracts fields whose
**meaning** is already fixed by the chosen extractor. The extracted
instances are stamped with an `INSTANCE_OF <kind>` edge to the chartable
target kind from the substrate — and the routing graph can now reach
them through the existing class chain.

### What kind-sources actually exist today

Reconnaissance of the dagster ingest flow ([definitions.py](../../doc-tools/doc_tools/definitions.py),
[document_parser.py](../../doc-tools/doc_tools/components/document_parser.py),
[semantic_assets.py](../../doc-tools/doc_tools/assets/semantic_assets.py))
confirms **both** kind-sources the architecture needs are already wired
today — just for `domain_type` (plugin selection), not yet for
`content_kind`:

- **(a) Path-encoded kind-source.** Per the S3 sensor configuration,
  documents land under prefixes like `manufacturing/inbound/` or
  `sustainment/inbound/`. The document parser then derives the domain
  from `parts[0]` of the object key (`document_parser.py:55`) and stamps
  it into the manifest as `manifest.metadata.domain_type`. The
  `build_knowledge_graph` asset reads this and dispatches to the
  matching plugin (`semantic_assets.py:88–158`).
- **(b) Metadata-declared kind-source.** A sibling `metadata.json` is
  fetched (`document_parser.py:82`) and its keys are merged into the
  manifest metadata via dict-spread (`**doc_metadata`) AFTER the
  path-derived `domain_type` is set. This means a present `metadata.json`
  with `"domain_type": "..."` overrides the path-derived value (last
  write wins in the dict spread).
- **(c) Run-tag fallback.** If `manifest.metadata.domain_type` is
  missing entirely, `context.run.tags.get("domain_type")` is consulted,
  then `metadata.get("project")`, then hardcoded `"Training"`
  (`semantic_assets.py:88–93`).

The infrastructure for a deterministic kind-source already exists. What's
missing is a) extending it from `domain_type` (plugin selection) to a
finer-grained `content_kind` field; b) the chartable mapping that says
"this kind dictates this extractor-config dictates this target
OntologyClass"; c) the `INSTANCE_OF` stamping at the wire-format layer.

### Naming correction — banking this NOW so the overnight doesn't bake it in

The first draft of the target kind would have been
`mfg:MunitionsAssemblyStep` (per the substrate residue still present
from the pre-canonical direct-load era). That name is shortsighted the
same way "work instruction = manufacturing" was: it bakes a *specific*
described thing (munitions / effectors / missiles) into a kind name that
should be **general** (any manufactured artifact — sensors, electronics,
mechanical assemblies, munitions). The general manufacturing-work-instruction
kind is `mfg:WorkInstruction`, parallel to `mil:` content kinds in the
S1000D ecosystem. Munitions / sensors / electronics are *what is
described*, not separate kinds. They are properties of the instance, not
of the type.

This decision is **made tonight by the architect** (not deferred to the
overnight): single general `mfg:WorkInstruction` kind. No sub-kinds.
Sub-kinds would be Wave-3 work only if a real question demands routing
munitions-questions differently from sensor-questions; until that
demand materializes, the single general kind is the safe and correct
choice.

## Decision

### Target architecture

```
   kind-source                kind selects                    LLM extracts fields            ingest stamps
   ───────────                ──────────────                  ──────────────────────         ────────────
   metadata-declared    →     extractor-config        →       per-kind field set      →      INSTANCE_OF
     (else path-derived)        (incl. BAML schema +                                          <kind>
     (else HALT,                 prompt + valid-value
      never LLM)                 enums + overlay spec)
```

The kind is **never** produced by the LLM. The LLM only enters the
pipeline AFTER the kind has been determined, and even then only to
extract fields the chosen extractor-config defines. The wire format
post-extraction carries an `INSTANCE_OF <kind>` edge to the chartable
target `:OntologyClass` so the routing graph can reach the instance
through its class chain (ADR-0018 (S, P) walk).

### Precedence rule (deterministic, no LLM in the kind-selection path)

1. **Metadata declaration wins.** If `manifest.metadata.content_kind`
   is set, that's the kind. This is the explicit operator/upstream
   declaration channel — wins over everything else.
2. **Path-derived as fallback.** If `content_kind` is absent, derive
   from the S3-prefix segment after the `domain_type` segment (e.g.
   `manufacturing/work-instructions/<doc_id>/file.pdf` →
   content_kind = `work-instructions`). Path-encoding lets ops drop
   files into a directory and have routing Just Work.
3. **HALT if unclassifiable.** If neither (1) nor (2) yields a kind
   that maps to a registered target class, the ingest job **halts
   loudly** with a named error. Never silently fall through to "the
   default kind" — silent default is exactly how the current
   single-kind hardcode happened, and is the failure mode the
   substrate-discipline rule (ADR-0019) exists to prevent.

This precedence is the manufacturing analog of the path→semantic-domain
fix already shipped (see [feedback_path_vs_semantic_domain](../../../iagent-mesh-sdk/memory/feedback_path_vs_semantic_domain.md)
in the operator memory): explicit declaration wins, path is fallback,
unclassifiable halts.

### The mapping table (chartable, version-able, code-owned)

A single table — colocated with the plugin registry — declares the
authoritative `(kind-source value → kind → extractor-config →
BAML-set → target OntologyClass kind)` mapping. With today's plugins,
the table starts with ONE row for manufacturing:

| kind-source value | kind | extractor-config (TypeBuilder enums + overlay) | BAML-set | target OntologyClass |
|---|---|---|---|---|
| `work-instructions` (or absent → default) | `work-instruction` | default `valid_personnel_roles` / `valid_hazard_classes` / `valid_process_categories` + the `DEFAULT_OVERLAY` from `manufacturing_overlay.py` + any `MANUFACTURING_OVERLAY_SPEC` overlay | `manufacturing.baml::ExtractWorkInstructions` | `mfg:WorkInstruction` |

This is the **only** row needed today; the table grows row-by-row as
new kinds are added. The table itself is the contract: adding a kind
means adding a row (and a target `:OntologyClass` in the manufacturing
TTL), not editing the extractor.

### Bringing manufacturing INTO substrate-discipline compliance

Today manufacturing is an **exception** to ADR-0019's substrate frame:
the extractor writes a flat kind that no routing graph can reach (no
`INSTANCE_OF` edge to a chartable target). This ADR makes manufacturing
a **compliant** participant in the substrate frame: LLM extracts fields;
deterministic mapping classifies the kind; ingest stamps the
`INSTANCE_OF` edge; routing walks the existing (S, P) graph and reaches
the instance through its class chain.

### What is implemented vs. what waits for approval

Per the architect's overnight scope:

- **Implement now (Step 4 of this overnight, if reached safely)**: the
  `INSTANCE_OF` stamping for the **single** kind that exists today
  (`mfg:WorkInstruction`). This is safe because there's only one kind
  — the kind-*selection* machinery isn't needed yet; we just stamp the
  kind that's already implicit in the single existing path. This
  closes the loop the (B) finding identified: instances become
  reachable by the manufacturing routing verb.
- **Hold for ADR approval**: the kind-selection precedence machinery
  (metadata > path > halt), the chartable mapping table as a code
  artifact, and any future sub-kind hierarchy. None of these is built
  tonight; the design is captured here and waits for the architect's
  ruling.

## Consequences

**Wins:**
- Manufacturing rejoins the substrate-discipline frame (ADR-0019).
  Routing can reach extracted manufacturing content through the same
  (S, P) walk that reaches every other content type.
- The (B) finding from the schema read is resolved by the architecture
  rather than by adding LLM classification at extraction time — the
  insight that "kind lives at the routing layer, not in the fields"
  becomes a chartable rule.
- The mapping table is the new source of truth for "which kinds exist
  and how each is extracted." Adding a kind is a reviewable table
  edit, not an extractor rewrite. The proprietary overlay continues
  to ride underneath unchanged.
- The precedence rule mirrors a pattern already shipped (path→domain
  fix), so the implementation cost is well-understood.

**Costs:**
- The kind-selection machinery is new code. Modest, but real.
- Every existing manufacturing instance written under the old flat-kind
  regime has no `INSTANCE_OF` edge. A one-time backfill is required to
  make pre-existing instances reachable by the routing graph. The
  backfill is deterministic (`MATCH (s:ManufacturingStep) WHERE NOT
  (s)-[:INSTANCE_OF]->(:OntologyClass {uri: "<mfg:WorkInstruction>"})
  ... MERGE ...`) but is a separate operation, not part of the ADR
  implementation.
- The chartable mapping table introduces a new place future contributors
  must edit when adding a kind. The trade-off is: this is the *one*
  place, vs. today's multi-file edit any new kind would require.

**What does NOT change:**
- The proprietary overlay loaded from `MANUFACTURING_OVERLAY_SPEC`.
  It continues to inject runtime fields onto `ManufacturingStep` via
  TypeBuilder; the kind is set BEFORE the overlay is applied.
- The 18 base BAML fields. The schema doesn't grow a `content_kind`
  field — kind is a substrate concept now, not a schema concept.
- The (E)-classified fields. None of the prose / values / part numbers
  / standards-references the LLM extracts changes.

## Alternatives considered

- **Add a `content_kind` enum field to the BAML schema; let the LLM
  pick the kind.** Rejected. Violates ADR-0009 ("resolve nouns, not
  callers") and ADR-0019 (substrate is authoritative, LLM does not
  classify routing). Adds the same prompt-fragility we removed when
  retiring persona/intent classification.
- **Keep the flat single-kind write; rely on Engine A's generalist
  fallback for manufacturing queries.** Rejected. This makes the
  generalist fallback the *primary* path for an entire content
  domain, which is exactly the inversion ADR-0019 ruled out.
- **Build the sub-kind hierarchy now (MunitionsAssemblyStep /
  SensorAssemblyStep / etc. as children of mfg:WorkInstruction).**
  Rejected for now. The (B)-side question "do questions about
  munitions need to route differently from questions about sensors?"
  has no demand-side evidence today. Sub-kinds without routing
  pressure are speculative ontology debt. The general kind is the
  safe target; sub-kinds become Wave-3 work if and when routing
  pressure materializes (the same content-hierarchy decision pattern
  the `mil:` manuals used).

## Indicators for revisiting

- A real routing question surfaces that needs munitions-questions to
  route differently from sensor-questions or other manufactured-artifact
  questions. At that point the sub-kind hierarchy becomes worth building,
  and the mapping table grows from one row to several.
- A new manufacturing-domain content type lands that isn't a work
  instruction (e.g. a compliance audit, a strategic assessment, a
  capability roadmap). At that point the second row goes into the
  mapping table; this ADR's machinery handles it without redesign.
- Multiple proprietary overlays start to diverge by what they assume
  the underlying kind is. At that point either the kind is too coarse
  (revisit sub-kinds), or the overlays should themselves be kind-keyed
  in the mapping table (extend the table schema).
