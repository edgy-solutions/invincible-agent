---
id:         presentation-contract-enumeration
status:     open
blocked-by-ruling: RESOLVED 2026-08-20 - see the AMENDMENT in docs/adr/ADR-0017-presentation-as-predicate.md. Transport is per-UI capability REGISTRATION (not a shared schema file); the contract's single home is the COMPONENT LAYER and the registration payload is derived from component exports.
owner:      agent
blocked-on:
closed-by:
trigger:    D4 TIGHTENING - capability_admission.KNOWN_ARCHETYPES deliberately encodes the D4 defect: it admits the UNION of BAML's SemanticArchetype and the five archetypes the interpreter dispatches without the enum declaring them (GROUPED_REVIEW, APPROVAL_TASK, TRIAGE_TASK, WORKFLOW_OBSERVATION, INSTANCES_BY_PROPERTY). Enforcing the enum would refuse archetypes the UI genuinely renders, punishing users for a backend inconsistency they did not create. WHEN THE ENUM IS REPAIRED, THE VALIDATOR'S VOCABULARY MUST TIGHTEN TO MATCH - a validator that permanently encodes a defect becomes that defect's guardian.
repo:       invincible-agent
summary:    ADR-0017's capability publication carries expected_fields (NAMES) but no types or cardinality, so every consuming contract lives in a React component and the backend mirrors it by hand. Enumerated 2026-08-19 from the components' actual prop types and key handling. THREE FINDINGS OUTRANK THE ENUMERATION - presentation_agent/capabilities.py hand-duplicates the ENTIRE UI capability registry with no seal; chart_normalizer.py (194 lines) mirrors a shape ChartWidget NO LONGER REQUIRES; and the dispatch boundary is typed `any`.
---

# The presentation contract, enumerated

ADR-0017 decided the UI publishes its render capabilities and the backend picks the archetype
from that published menu. `expected_fields` is the seam that exists
(`cortex-ui/src/registry/frontendCapabilities.ts:34` - "Field names this archetype expects to
find in structured_data"). **It carries names. It carries no types and no cardinality.** This
packet supplies the missing layer, extracted from what the components actually do.

## 1 - The typed contract table

Every archetype the interpreter dispatches (`components/registry/SemanticInterpreter.tsx:356`,
switch on `comp.archetype`). Types are the components' declared props; cardinality is what the
component's own guards enforce.

| archetype | component | field -> type | cardinality / guard | cite |
|---|---|---|---|---|
| PROCESS_TOPOLOGY | ProcessTopologyCard | `subject_concept?: string`; `nodes: ProcessNode[]`; `edges: ProcessEdge[]`; `ProcessNode = {id: string, name?, type?, description?: string}`; `ProcessEdge = {source: string, target: string, relation?, predicate?: string}` | nodes/edges default `[]` at the call site; only id/source/target required | ProcessTopologyCard.tsx:32-50; call site SemanticInterpreter.tsx:371-374 |
| HAZARD_DECLARATION | WarningCard | `error: string` (REQUIRED - the card title); `hazards?: HazardEntity[]` = `{id: string, name?, type?, description?}`; severity CRITICAL/WARNING/INFO | error required; hazards optional; severity defaults WARNING | WarningCard.tsx:4-27 |
| ASSET_STATE_METRIC | SupplyTable | `data: Record<string, any>[]` | **>= 1 row required**; empty renders NO_TELEMETRY_DATA_AVAILABLE. **COLUMNS ARE Object.keys(data[0]) - ROW 0 DEFINES THE SCHEMA**, so heterogeneous rows silently lose columns | SupplyTable.tsx:5-19 |
| KNOWLEDGE_DOCUMENT | MarkdownRenderer | `content: string` (markdown, GFM); `subject?: string` | any string; `img` maps to FederatedImage, which resolves `s3://` via cortex-bff /federated_image | SemanticInterpreter.tsx:199-316; mesh/FederatedImage.tsx |
| CHART_WIDGET | ChartWidget | `data: string` - **A JSON-STRINGIFIED ARRAY, NOT AN ARRAY**; `type: BAR/LINE/PIE/SCATTER`; `subject: string`; `sql: string`; `onPublish: (sql, title) => void` | the real contract is inferred - see below | ChartWidget.tsx:22-28 |
| DIGITAL_TWIN_3D | **none** | - | dispatch REMOVED 2026-06-26; falls through to the honest UI COMPONENT NOT FOUND default | SemanticInterpreter.tsx:459-463 |
| GROUPED_REVIEW | GroupedReviewCard | `comp.batch` | not a SemanticArchetype member | SemanticInterpreter.tsx:419 |
| APPROVAL_TASK | ApprovalTaskCard | `comp.task` | not a SemanticArchetype member | :433 |
| TRIAGE_TASK | TriageTaskCard | `comp.task` | not a SemanticArchetype member | :438 |
| WORKFLOW_OBSERVATION | WorkflowObservationView | `comp.projection` | not a SemanticArchetype member | :446 |
| INSTANCES_BY_PROPERTY | InstancesByPropertyView | `payload={comp}` (whole payload) | not a SemanticArchetype member | :452 |

### CHART_WIDGET's real contract - inferred, and MUCH wider than name/value

ChartWidget parses `data` then calls `normalizeChartData(rows, type)`, producing a five-way
discriminated union `NormalizedShape` (ChartWidget.tsx:77-105):

`single {xKey, valueKey}` | `multi {xKey, ...}` | `scatter {xKey, yKey}` | `scatter-multi` | `empty {reason}`

The accept condition is **an array of objects with at least one NUMERIC column**. Refusals are
explicit and typed: "no rows" (:112), "rows aren't objects" (:116), "no numeric column" (:137),
"JSON parse failure" (:279), "not an array" (:281). Keys are **chosen at runtime** -
`xKey = numericKeys[0]`, `yKey = numericKeys[1]` (:151-152) - and plotted via
`dataKey={shape.xKey}` / `{shape.valueKey}` (:344, :378, :385, :430, :441).

**Name/value is not the contract. It is ONE INSTANCE of `kind: "single"`.**

## 2 - The drift inventory

Ordered by consequence, not by size.

### D1 - presentation_agent/capabilities.py hand-duplicates the ENTIRE UI registry. NO SEAL.

The worst instance, and it is not chart-shaped. Every `expected_fields` list in
`cortex-ui/src/registry/frontendCapabilities.ts` appears **byte-identical** in
`agent_fleet/presentation_agent/capabilities.py`:

| capability | cortex-ui | backend |
|---|---|---|
| OwnershipFact | :54 | capabilities.py:72 |
| LineageTopology | :64 | :79 |
| impact | :74 | :86 |
| schema | :84 | :93 |
| freshness | :94 | :100 |
| tag filter | :104 | :109 |
| describe | :115 | :116 |
| enumerate | :129 | :131 |
| DatasetAnalysisReport | :140 | :139 |
| KnowledgeRetrieval | :151 | :147 |

**capabilities.py's docstring claims "The capability table itself stays the single source."** It
is the backend's copy; the UI holds another. **Nothing pins them equal** - no test in `tests/`
references `frontendCapabilities` or `CORTEX_UI_CAPABILITIES`. Two single sources, two repos,
no seal. This is precisely the publication ADR-0017 exists to make unnecessary.

*What breaks if the component changes:* nothing, loudly. A UI-side edit to `expected_fields`
leaves the backend asserting the old menu, and the disagreement stays invisible until a render
is wrong.

### D2 - chart_normalizer.py (194 lines) mirrors a shape the component NO LONGER REQUIRES

`agent_fleet/presentation_agent/chart_normalizer.py:8` states the component "hardcodes
dataKey=name and dataKey=value", and coerces to an array of `{name: str, value: number}`
(:98, :136, :149). **That description is stale.** ChartWidget now infers keys
(`shape.xKey`/`shape.valueKey`) and accepts any array of objects with a numeric column.

*What breaks:* the mirror is now **information-destroying**. Data the component could render as
`multi` or `scatter` is flattened to single-series name/value before it ever arrives. The
backend narrows what the frontend widened - and nothing failed, which is why it went unnoticed.

Line 151 records a real production bug from this mirroring: a row of `name=cage, value="00000"`
passed strings through where Recharts needed numbers. *(That payload resembles the `p_caeg`
family. SAME-FAMILY RESEMBLANCE IS A FLAG, NOT A FINDING - the second-method rule applies before
anyone links them.)*

### D3 - the dispatch boundary is typed `any`

`SemanticInterpreter.tsx:356` - `comp: any`. Every `comp.chart_data`, `comp.metrics`,
`comp.markdown_content` access is unchecked. **TypeScript cannot catch a contract break at the
one place both sides meet**, which is why D1 and D2 can drift silently in a typed codebase.

### D4 - the archetype vocabulary has three populations that do not agree

* BAML `SemanticArchetype` (`baml_shared/baml_src/contracts.baml:513-521`): 6 members.
* The interpreter dispatches **11**, adding GROUPED_REVIEW, APPROVAL_TASK, TRIAGE_TASK,
  WORKFLOW_OBSERVATION, INSTANCES_BY_PROPERTY.
* DIGITAL_TWIN_3D is in the enum and in `answerDisplay.ts:32` but **has no renderer**.

The enum can name a render the UI cannot perform, and the UI performs renders the enum cannot
name.

## 3 - The selection rule, PROPOSED (not built)

Today the archetype is chosen from `output_uri` alone, via the capability lookup - **before
anyone looks at the rows.** Proposed: `output_uri` demoted from verdict to **candidate filter**,
with payload shape deciding among the survivors.

| payload shape (observed, not asserted) | satisfied contract | archetype |
|---|---|---|
| `string` (prose/markdown) | MarkdownRenderer.content: string | KNOWLEDGE_DOCUMENT |
| array of objects, >= 1 numeric column, one natural label column | normalizeChartData -> single/multi | CHART_WIDGET |
| array of objects, >= 2 numeric columns, no natural label | -> scatter/scatter-multi | CHART_WIDGET |
| array of objects, homogeneous keys, mostly non-numeric | SupplyTable.data (row 0 = schema) | ASSET_STATE_METRIC |
| object with nodes[]/edges[] carrying id/source/target | ProcessTopologyCard | PROCESS_TOPOLOGY |
| object with hazards[] or a severity | WarningCard | HAZARD_DECLARATION |
| none satisfied | - | KNOWLEDGE_DOCUMENT (honest prose), never an empty widget |

**Ordering rule:** filter candidates by `output_uri`, keep only those whose contract the payload
SATISFIES, then rank by `persona_fit`/`domain_fit` (already published, already ranking-only).

The last row is load-bearing: `chart_normalizer.py:32` already prefers "the agent's honest TEXT
answer (KNOWLEDGE_DOCUMENT), not an empty CHART_WIDGET". This generalises that instinct into the
rule instead of leaving it as one special case.

## The isomorphism - same disease as the resolver, and the second fix should be cheaper

The resolver's defect: **a deterministic candidate set, with a single voter deciding without
looking at the evidence.** `/resolve` had a real class pool and let one LLM call pick, which is
why the repair was to make the signal good enough that the rule is obvious rather than to make
the voter smarter.

Presentation is the same shape one layer over: the candidate set is deterministic (the published
capability table), and the archetype is chosen from `output_uri` **before the rows are read**.
Same repair - publish the contract, and the choice becomes a lookup rather than a judgement.

**It should be cheaper, for a measured reason.** `answer-latency-tier1` found `composing` is
102.5s, **39.1% of a Tier-1 answer**, spent turning an already-known fact into a card - and that
95-97% of that model's generated tokens are hidden chain-of-thought. **A deterministic archetype
selection removes LLM calls from the render path**, so this fix pays in correctness AND in the
single largest phase of the answer.

## Stop-and-report - the components are NOT inconsistent with each other

Checked, because the brief asked for it. **The components agree among themselves.** Each
declares its props, guards its own empty cases, and degrades honestly
(NO_TELEMETRY_DATA_AVAILABLE; `kind: "empty"` with a typed reason; UI COMPONENT NOT FOUND). There
is no UI defect of the kind that would have made this an enumeration problem rather than an
enumeration.

Every inconsistency found is **backend-vs-component** (D1, D2) or **vocabulary-vs-renderer**
(D4). That is the enumeration's own conclusion and the argument for the publication: the drift
is one-directional because only one side is written down.

## Vocabulary note

This packet uses ADR-0017's own terms - `expected_fields`, capability publication, `output_uri`,
archetype. The label "Hole 4" appears in NO artifact in any repo; it is chat-side shorthand. A
future reader grepping for it would conclude the finding does not exist, so it is deliberately
not propagated here.


---

## RULED 2026-08-20 - registration, not a shared schema file

The publication question this enumeration fed is decided in the AMENDMENT to
`docs/adr/ADR-0017-presentation-as-predicate.md`. Recorded here because this packet's own
section 3 was written before the ruling and reads as if a shared schema were the direction.

**What changed:** the drift finding (ten hand-copied `expected_fields` lists, D1) is a
**transport-independent** defect. Treating "shared schema file" as its remedy conflated two
questions. Transport is **per-UI capability registration into the graph** - this ADR's own full
form, the same machinery as engine verb registration - because a static file is either N files
or a **union that LIES**, letting the backend pick an archetype the calling UI cannot render.

**What survives unchanged:** everything in sections 1 and 2. The typed contract table IS the
material for step 1 of the build order (component exports), and the drift inventory is the list
of things that dissolve. D1's `capabilities.py` and D2's `chart_normalizer.py` are not ported to
the new transport - they stop existing, replaced by a validator against registered contracts.

**What section 3's decision table becomes:** still the selection rule, but scoped. Payload shape
-> satisfied contract -> archetype, now selected *within the calling client's registered menu*
rather than across a global table, with `output_uri` still demoted from verdict to candidate
filter. The table is unchanged; its domain shrank to the caller's menu.

**One clause added by the ruling that this enumeration did not anticipate:** the presentation
decision now binds to the requesting client's registration, resolved at decision time, with the
registration version stamped into the answer envelope. Unregistered callers get a labelled
default menu; persisted answers carry the decision's provenance so a different-capability
consumer can RE-RESOLVE presentation from the data. The archetype is a projection, not truth.
