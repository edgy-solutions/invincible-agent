# ADR-0022 — DataHub integration: owned wrapper, mining the MCP server as reference

**Status:** Proposed
**Date:** 2026-06-26
**Deciders:** Platform team
**Related:**
  - [ADR-0013](ADR-0013-engine-d-capability-surface.md) — *what* catalog
    capabilities to expose through Engine D. This ADR is *how* we expose
    them: a wrapper we own, deliberately shaped to our architecture,
    rather than a third-party client we adopt wholesale. ADR-0013 sets
    the surface; ADR-0022 settles the question of who builds it.
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — *resolve nouns,
    not callers.* The same discipline applied to the integration layer:
    DataHub's authoritative facts (entity types, GraphQL error shapes,
    field mappings) come from a deterministic source — DataHub itself —
    not from LLM judgment or guess-and-broaden. The wrapper exists to
    thread DataHub's deterministic facts into our architecture in a way
    a generic client cannot.
  - [ADR-0021](ADR-0021-deterministic-content-kind-selection-at-ingest.md) —
    deterministic mapping over LLM classification at ingest. The same
    §1 discipline applied at the integration boundary: deterministic
    class → DataHub entity_type, deterministic enum validation,
    deterministic canonical-form handling. The wrapper is where these
    deterministic threads are wired; a black-box MCP client would
    hide them.
  - [ADR-0017](ADR-0017-presentation-as-predicate.md) — assumed-contract
    elimination: every cross-component contract is explicit, registered,
    and traceable. A third-party MCP server is, by definition, a
    component whose contract we did NOT write and cannot enforce — the
    same shape the assumed-contract class has been built to eliminate.
    Adopting one wholesale would re-introduce that class at the
    catalog-integration boundary.
  - `agent_fleet/datahub_wrapper/main.py` — the wrapper this ADR rules
    on. Its existence predates this ADR; the question now is whether
    to keep building it, replace it with the MCP server, or adopt a
    hybrid.
  - DataHub MCP server (upstream, third-party) — the alternative this
    ADR explicitly chooses to mine-not-adopt. Linked here as the
    reference document this ADR commits to reading systematically,
    not the dependency it commits to taking.

## Context

### What prompted the question

The 2026-06-26 work-cluster log (the same one that produced commit
`d9627dc`) surfaced a `/query_metadata` bug where Engine D silently
swallowed DataHub's GraphQL validation errors. DataHub returned
`HTTP 200` with `{"errors": [...], "data": null}` on invalid
`entity_type` enum values; our parse pattern
(`data.get("data") or {}`) collapsed that to an empty result set;
the smolagent saw "no results", broadened to another invalid
enum value, looped on silent empties while DataHub's actionable
error message was discarded at every step.

That bug — the third DataHub-wrapper bug in the broader rendering
arc — raised the natural question: are we better served replacing
the owned wrapper (`agent_fleet/datahub_wrapper/main.py`) with the
DataHub MCP server, which the upstream team maintains against
DataHub's schema and presumably handles these edge cases correctly?

### What the bug actually reveals

Before deciding the integration philosophy, examine the evidence.
The failure was not "DataHub's API is inadequate" — DataHub told
us precisely what was wrong:

> `Invalid input for enum 'EntityType'. No value found for name 'TABLE'`

The asset was present (the dashboard at
`urn:li:dashboard:(superset,19)` was returned successfully on the
valid-`DASHBOARD` calls). The error message was precise. The
failure was the wrapper mis-handling a response DataHub gave us
correctly: a parse pattern that collapsed the error envelope to
an empty success shape.

**This is wrapper-quality, not capability gap.** DataHub had the
error; DataHub had the asset; the wrapper's parse code discarded
both. The same shape — wrapper-quality, not capability — covers
the other DataHub-related bugs this arc surfaced:

* The smolagent's hallucinated `entity_type` enum values
  (`"TABLE"`, `"VIEW"`, `"dataset"`, `"data_product"`) — closed
  at commit `0050e37` by threading the deterministic
  `idp:* → DataHub entity_type` mapping into Engine A's prompt.
  Wrapper-side fix; the wrapper is where the deterministic
  thread is wired.
* The Customer 360 vs "360 Dashboard" identifier-form mismatch —
  banked at [[resolve-instance-provider-gap]] as a wrapper-side
  token-subset fallback fix. Wrapper-quality.
* The Phase 3 source-attribution plumbing into the cortex-ui
  grounding panel — wrapper threading sources_collected through
  to the supervisor's `subtask_sources` materialization.
  Wrapper-side integration.

Switching to the MCP server would not have prevented the
silent-swallow bug unless the MCP server happens to handle errors
better — and trading a known wrapper we can fix for an unknown
one whose error-handling we'd have to learn first is the
"assumed contract between components" class
([[silent-degrade-composition]], [[ui-surfaces-wrong-path]],
[[verification-must-fail]]) that this project has been built to
eliminate at every other layer. The pattern is consistent: where
we own the contract, we can name and fix the bug. Where we adopt
a contract, we discover its bugs by failure.

### Why the wrapper exists in the first place

The wrapper does things the MCP server almost certainly does not,
because they are specific to this architecture:

| Wrapper integration | Why generic MCP wouldn't carry it |
|---|---|
| Deterministic `idp:* → entity_type` recommendation threaded into the smolagent prompt | MCP server doesn't know about the `idp:*` ontology |
| `mesh:resolveInstance` phone-book preemption (Engine D registered as a provider in the verb registry) | MCP server isn't a mesh provider; doesn't speak `mesh:*` predicates |
| `matched_assets` shape conformed to the cortex-ui `Source` type (label / type / URI / snippet / open_url) | MCP server emits DataHub's native shape, not our grounding-panel contract |
| `_DATAHUB_TO_IDP` inverse-mapping used for class derivation in `/resolve_instance` | MCP server doesn't know our class taxonomy |
| Phase 3 `sources_collected` plumbing into the supervisor's `subtask_sources` Dagster asset | Architecture-specific; lives in the wrapper because the wrapper is where DataHub touches our pipeline |

These are not generic catalog-access capabilities. They are wiring
that bolts DataHub's facts to our routing layer, our substrate, our
phone-book preemption, our grounding panel. The wrapper exists
because we need DataHub access shaped to our architecture; the MCP
server provides DataHub access shaped to generic use. The shaping
is the value, and it is why the wrapper was built.

## Decision

**Keep the owned wrapper (`agent_fleet/datahub_wrapper/main.py`) as
the integration layer for DataHub. Treat the DataHub MCP server as
the authoritative reference for DataHub-correct usage, and port
edge-case handling from the MCP server's source into our wrapper
systematically — not by adoption, by reading.**

The MCP server is, in effect, DataHub's own documentation of how to
call DataHub correctly: it encodes the entity_type enums, the
error-handling, the query patterns, the field mappings that the
upstream team knows and we discover by failure. Mining it
converts "discover by bug" into "port from reference" while
keeping the wrapper conforming to our architecture.

For specific DataHub capabilities that would be expensive to
reimplement (rich query interfaces, lineage traversal, search
ranking the wrapper would have to build from raw GraphQL), the
wrapper may call the MCP server as a *backend tool* among its own
tools — wrapper for integrated/deterministic paths, MCP server for
rich-capability paths we do not want to reimplement. This hybrid
is the escape hatch, decided per-capability after reading what the
MCP server offers — not a wholesale switch.

**The wrapper stays the integration layer; the MCP server is the
reference and (optionally, per-capability) a backend.**

## Alternatives Considered

### Alternative 1: Adopt the DataHub MCP server wholesale (rejected)

Replace `agent_fleet/datahub_wrapper/main.py` with the upstream
MCP server. Engine A's tools call the MCP server directly; mesh
integration (resolveInstance provider, idp class derivation,
source attribution) is bolted on outside.

**Rejected because:**

* The MCP server is a black box whose contract we did not write
  and cannot enforce. When it silently mis-handles something —
  and external contracts always eventually do — diagnosis means
  reading someone else's code instead of reading our own `d9627dc`-
  shaped fix. That is the assumed-contract failure mode this
  project has eliminated at every other component boundary
  (the silent-degrade composition arc, the chart-empty arc, the
  contamination arc); re-introducing it at the catalog boundary
  would be a deliberate regression of the architecture's spine.
* Our deterministic threading lives in the wrapper. The Engine A
  entity_type recommendation, the phone-book preemption, the
  canonical-form handling — these are wired by us into the
  wrapper because the wrapper is where DataHub touches our
  architecture. A generic MCP server cannot thread them; we
  would lose the determinism `0050e37` just fought for.
* The integrations the wrapper provides (grounding panel `Source`
  shape, `subtask_sources` materialization, `mesh:resolveInstance`
  provider registration) are architecture-specific and would
  require *wrapping the MCP server* to restore. The result would
  be wrapper-around-a-wrapper — more layers, more opaque
  contracts, not fewer. Adopting the MCP server would not eliminate
  the wrapper; it would multiply it.

### Alternative 2: Ignore the MCP server; keep finding edge cases by failure (rejected)

Keep building the wrapper independently of the upstream MCP
server. Discover DataHub's API edge cases (error envelopes, enum
values, field mappings) by production bug; fix each in the
`d9627dc` shape.

**Rejected because:**

* That is the cost we have been paying — three DataHub-wrapper
  bugs in this arc alone (silent-swallow, entity_type
  hallucination, identifier-form mismatch), each a fix after a
  user-visible failure. The MCP server has likely already encoded
  the correct handling for many of these; reading it converts
  "discover by user-visible failure" into "port before failure
  surfaces."
* This alternative is the implicit default; the question this
  ADR rules on is whether to do better. Choosing to mine-and-port
  is strictly cheaper than choosing to ignore-and-discover when
  the reference exists and is freely readable.

## Consequences

### What we get

* **Determinism and our integrations are preserved.** The
  entity_type recommendation, phone-book preemption, grounding-
  panel `Source` shape — all stay wired in the wrapper. Future
  threading lands in the same place; the §1 line holds at the
  catalog boundary.
* **The MCP server becomes a free spec.** Instead of
  reverse-engineering DataHub's API edge cases through production
  bugs, we read the upstream team's encoding of "how to call
  DataHub correctly" and port what we are missing. The wrapper's
  correctness improves as a function of reading the reference,
  not as a function of catching production failures.
* **The escape hatch is available per-capability.** If a specific
  DataHub capability (e.g., a rich lineage traversal) is too
  expensive to reimplement, the wrapper can call the MCP server
  as a backend tool for that one capability while still owning
  the integration. The decision is per-capability, made after
  reading what the MCP server offers.

### What we own

* **Wrapper quality is our responsibility.** Bugs in the wrapper
  (the silent-swallow class, the next analog) are ours to find and
  fix. The mining-from-reference discipline reduces but does not
  eliminate that cost.
* **Maintenance against DataHub schema changes.** DataHub's
  schema evolves; the wrapper has to track it. The MCP server
  presumably tracks it for upstream consumers; if we find,
  reading it, that it handles a deep well of version-tracking
  correctness we would otherwise own, the maintenance math shifts
  toward the hybrid — call it for that correctness while keeping
  the integration layer on top. This trigger is named in the
  follow-up tasks below.

### Follow-up tasks (bank these with triggers)

The decision generates concrete porting work. These are bank-
shaped (findings with triggers); the ADR rules on the *direction*,
the bank holds the *execution*:

* **Port the MCP server's GraphQL-error handling into the
  wrapper.** Trigger: now, against commit `d9627dc`. Confirm
  whether our fix matches the upstream pattern, or whether the
  upstream handles additional error shapes we missed.
* **Derive the `idp:* → entity_type` mapping (and its inverse)
  from the MCP server's authoritative enum.** Trigger: before
  the next time we add an `idp:*` class. Currently the inverse is
  hardcoded at
  `agent_fleet/restate_analyst/entity_type_mapping.py` and the
  forward at `agent_fleet/datahub_wrapper/main.py:_DATAHUB_TO_IDP`
  — the AST-derived test at
  `tests/routing/test_engine_a_entity_type_hint.py` catches
  inter-table drift but cannot catch drift against DataHub's
  actual enum. Deriving from the MCP source closes that gap.
* **Read the MCP server for entity-label-vs-search-string
  matching.** Trigger: the next time we hit the Customer 360 vs
  "360 Dashboard" form-mismatch class (banked at
  [[resolve-instance-provider-gap]]). Does the MCP server do
  fuzzy/subset matching? How? Port the technique into the
  wrapper's `/resolve_instance` token-subset fallback.
* **Audit the MCP server for capabilities expensive to
  reimplement.** Trigger: read-and-decide pass after the
  cert-rebuild lands and the work cluster is stable. If the MCP
  server encodes deep schema-version-tracking correctness, the
  hybrid (call it as a backend for those specific capabilities)
  becomes the durable approach for that subset.

### Status of this ADR

**Proposed.** This decision is made BEFORE the next DataHub-
wrapper work, to give that work a decided direction rather than
drift. The cert-rebuild that gates the work-cluster entity_type
fix is a natural ratification moment: the rebuild incorporates
the right integration philosophy if this ADR is ruled on first,
rather than rebuilt against an undecided foundation and
re-litigated later.

Ratify or revise before the next DataHub-wrapper PR.
