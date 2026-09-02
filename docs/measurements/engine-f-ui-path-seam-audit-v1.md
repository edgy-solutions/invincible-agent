---
id:         engine-f-ui-path-seam-audit-v1
status:     open
owner:      agent
blocked-on: a push to master (image rebuild for cortex-bff and engine-f)
repo:       invincible-agent
ruled-by:   ADR-0019 (Contract D, atomic); ADR-0017 (rendersAs); ADR-0045 (Engine F)
code-site:  agent_fleet/utils/mesh_registration.py:492, agent_fleet/presentation_agent/capabilities.py:32, src/iagent/gateway.py:4330 (_emit_presentation_to_registrar call), agent_fleet/presentation_agent/capability_registry.py:239 (select_archetype)
summary:    EVERY SEAM ON THE FINANCE CARD PATH AUDITED INDIVIDUALLY, 2026-09-01. Seven of eight verified live; exactly ONE stops all six cards, and it is one line already committed (9022c3b) awaiting an image rebuild. The stopping seam is NOT the binding table and NOT the frontend: `fin:` was absent from the CURIE prefix map, so the gateway emitted the subject compact, the registrar MATCHed it against :OntologyClass nodes holding FULL IRIs, and Contract D refused all six atomically — while the POST returned `200 OK, accepted: 29, rejected: []`. Verified: 11/11 triple endpoints present at full IRIs and 0 nodes under compact `fin:`, so the gate was right and the lookup was wrong. Also verified live: all six verbs return `rows` payloads carrying every field their cortex contract refusalReasons name.
---

# Engine F → card: every seam, audited one at a time

**The bar this answers:** *"either all six cards demonstrably draw in sandbox through the real
path, or a named list of exactly which seam stops each one — no 'routing works' standing in for
'the card appeared.'"*

**The cards do not draw yet.** This is the named list, and it is one item long.

## The chain, seam by seam

| # | seam | state | evidence |
|---|---|---|---|
| 1 | phrase → verb routing | ✅ | measured previously; `Program 0.97 → finVarianceAnalysis 0.95` |
| 2 | entitlement — alice reaches `PROGRAM_FINANCE` | ✅ | Topaz `SYNC OK, checked=24 failures=0` |
| 3 | verb executes, returns its declared type | ✅ | all six called live, §2 below |
| 4 | payload satisfies the frontend contract | ✅ | §2 — every field the refusal conditions name is present |
| 5 | ontology classes exist for both triple ends | ✅ | **11/11** at full IRIs |
| 6 | archetypes declared + admitted | ✅ | 3 minted under `mesh:Archetype`; `KNOWN_ARCHETYPES` widened |
| 7 | HUD names the engine | ✅ | `engine-fin → "Engine F (Finance)"` (`e9dd2c7`) |
| 8 | **`rendersAs` rows in cortex's menu** | ❌ **STOPS ALL SIX** | §1 |

## §1 — The one seam, and why it was invisible

`/register_frontend_capabilities` converts each admitted capability into a real graph
registration, expanding the compact subject through `_expand_mesh_iri` first — because the
linker MATCHes `:OntologyClass` nodes that hold **full** IRIs.

That prefix map held `mesh:` and `idp:`. **An unknown prefix is passed through VERBATIM by
deliberate design** — inventing a namespace would fabricate the phantom class Contract D exists
to refuse — so `fin:VarianceDecomposition` reached the registrar compact and missed on the
subject end. Contract D is atomic, so the whole manifest went.

```
POST /register_frontend_capabilities   (cortex's real 29-capability payload, as alice)
  ->  200 OK   {"accepted": 29, "frontend_id": "cortex-ui-desktop", "rejected": []}
```

```
cortex-bff log, same request:
  failed_count: 6   reason_class: gateway-rejected-REFUSED   (Contract D)
  fin:VarianceDecomposition   fin:VarianceDriverRanking   fin:EstimateAtCompletion
  fin:BurnRateSeries          fin:FundingStatusGrid       fin:PerformanceIndexSeries
```

**The gate was right. The lookup was wrong.** In Neo4j:

| | |
|---|---|
| 6 `fin:` subjects + 5 archetype objects, at their FULL IRIs | **11 / 11 present** |
| nodes under compact `fin:` — what the failing MATCH searched for | **0** |

### `rejected: []` is not a claim about the graph

`rejected` counts **admission** refusals — vocabulary the backend has no name for. The six
Contract-D graph failures are logged loudly and **never reach the response body.** A frontend is
told 29 accepted, nothing rejected, while a quarter of its menu is absent from the graph.

### Two menus, and the fix reaches both

| menu | rows | `fin:` | written by |
|---|---|---|---|
| `cortex-ui-desktop` | 23 | 0 | the browser POST, converted by the gateway |
| `__system_default__` | 10 | 0 | `PRESENTATION_CAPABILITIES`, on the presentation agent startup |

`29 − 23 = 6`. Both paths expand through the same map, so **one line repairs both** — but they
live in two images, so **both `cortex-bff` and `engine-f` must redeploy.**

## §2 — The payloads, called live, against the contracts cortex declares

`POST /measure/<fn>` with `{"params": {"program_id": "NP-MERIDIAN"}}`, notional seed:

| verb | archetype | rows | the contract's stated refusal conditions | present |
|---|---|---|---|---|
| `fin_burn_rate` | PERIOD_SERIES | 6 | needs a period label + a numeric amount | `period`, `burn` ✅ |
| `fin_funding_status` | SHORTFALL_GRID | 18 | cell needs a subject + a required amount | `subject_id`, `required` ✅ |
| `fin_performance_indices` | PERIOD_SERIES | 6 | needs a period label + a numeric amount | `period`, `cpi`/`spi` ✅ |
| `fin_variance_analysis` | VARIANCE_TREE | 1 | single root, carrying variance and a name | `variance`, `entity_name`, nested `contributors` ✅ |
| `fin_variance_drivers` | CONTRIBUTION_RANKING | 3 | contributor needs a name and a contribution | `entity_name`, `contribution`, `rank` ✅ |
| `fin_eac_calculation` | FORECAST_MEASURE | 1 | exactly one row; **method mandatory** | `eac`, `method`, `formula` ✅ |

**`fin_performance_indices` carries NO top-level `value_unit`, deliberately** — CPI/SPI are
dimensionless and the row field is `amount_unit` specifically to defeat the projector's `rows[0]`
lift. cortex declares `value_unit` optional, so accommodation A2 holds on both sides.

*Scope: this asserts the fields the contracts' refusal conditions name are PRESENT. Which key
each component reads is a cortex-side fact, unmeasured here.*

## What remains

1. **Push `9022c3b` + `4e69947`** → rebuild `cortex-bff` and `engine-f`. *(Blocked: the push was
   refused by this session's classifier and was not routed around.)*
2. Re-register cortex's menu — a page load, or the headless procedure in
   `adding-an-engine.md` §6b.
3. Assert **6** `fin:` rows under `cortex-ui-desktop`, then drive the six phrasings and read the
   cards. **Not "routing works" — the card.**

## Method note

The first attempt to call the six verbs failed 6/6 with an identical slot-refusal, because the
envelope was flat and `MeasureRequest` nests under `params`. **A uniform extreme result across a
whole battery is this lane's standing tell for a broken instrument** — see
`[[assert-on-the-claim-not-its-neighbour]]` — and it was treated as one rather than reported.
