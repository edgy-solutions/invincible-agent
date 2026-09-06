---
id:         engine-f-ui-path-seam-audit-v1
status:     open
owner:      agent
blocked-on: a human look — every seam is repaired and no card has been seen render
repo:       invincible-agent
ruled-by:   ADR-0019 (Contract D, atomic); ADR-0017 (rendersAs); ADR-0045 (Engine F)
code-site:  agent_fleet/utils/mesh_registration.py:492, agent_fleet/presentation_agent/capabilities.py:32, src/iagent/gateway.py:4330 (_emit_presentation_to_registrar call), agent_fleet/presentation_agent/capability_registry.py:239 (select_archetype)
summary:    EVERY SEAM ON THE FINANCE CARD PATH AUDITED INDIVIDUALLY, 2026-09-01/04. STARTED as one seam and ENDED AS FIFTEEN, because each repair uncovered the next — all three produce the identical observable, a card reading `Knowledge Document / No content available`. SEAM 8 (bindings) IS FIXED AND PROVEN: `fin:` was absent from the CURIE prefix map, so the gateway emitted the subject compact, the registrar MATCHed against :OntologyClass nodes holding FULL IRIs, and Contract D refused all six atomically while the POST returned `200 OK, accepted: 29, rejected: []`. After the one-line fix and a redeploy: cortex-ui-desktop rows 23->29, __system_default__ 10->16, graph-registration failures 6->0, and the selector returns the intended archetype for 6/6 with a biting negative control. SEAM 9 STOPS ALL SIX and is fenced: fill_slots times out at 20s while engine-o extracts the slot correctly and returns 200, so the mandatory slot is unfilled, the disposition correctly becomes an ASK, and an ask card has no output_uri. SEAM 10 STOPS FOUR and is MINE: the six verbs declare four subjects, so a question naming the program grounds to fin:Program where compatible_count=2 and four verbs were never candidates. The classifier is right every time. Also observed, unowned: supervisor_query_job takes 5-6.5 min and the BFF reports dagster_run_failed for runs that log RUN_SUCCESS.
---

# Engine F → card: every seam, audited one at a time

**The bar this answers:** *"either all six cards demonstrably draw in sandbox through the real
path, or a named list of exactly which seam stops each one — no 'routing works' standing in for
'the card appeared.'"*

**The cards do not draw yet.** This is the named list. It began as one item and ended as three —
see the UPDATE section, which supersedes the seam table immediately below.

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
| 8 | **`rendersAs` rows in cortex's menu** | ✅ **FIXED — see UPDATE** | §1 |

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

## UPDATE — the deploy landed, and the real path found two MORE seams

Both images rebuilt and rolled 2026-09-02. **Seam 8 is closed and proven:**

| | before | after |
|---|---|---|
| `cortex-ui-desktop` rendersAs rows | 23 (0 fin) | **29 (6 fin)** |
| `__system_default__` rows | 10 (0 fin) | **16 (6 fin)** |
| graph-registration failures in the BFF log | 6 | **0** |

And the selector, asked directly for each of the six against cortex's real menu:
**6/6 return the intended archetype**, `presentation_source: registered`. Negative control: an
unbound `fin:` class returns `None` / `unrenderable`, so the check bites rather than passing
everything.

**The cards still do not draw**, for two reasons that have nothing to do with presentation. Both
were invisible until the binding was fixed, because the binding failure was masking them — all
three produce the same `KNOWLEDGE_DOCUMENT`.

### Seam 9 — the mandatory slot times out, so every question becomes an ask (stops ALL SIX)

```
routing_decision  verb_iri=mesh:finVarianceAnalysis verb_conf=0.96
WARNING  fill_slots unavailable (engine-o:8084 read timeout=20.0) — running on defaults
```

engine-o extracted it correctly and returned 200 on the same request:
`{"program_id":"Notional Program Meridian"}` at 0.95. **The supervisor had already stopped
listening at 20s.** With the mandatory slot unfilled the disposition correctly becomes an ASK,
an ask card carries no `output_uri`, and `/render_ui` takes `fallback-no-output-uri`.

So a question that NAMED the program is answered by asking which program.
Filed: `[[a-mandatory-slot-does-not-refine]]` — the budget's own comment justifies itself with
*"a slot REFINES a question that will still be answered without it"*, which is true for
spoken-optional and exactly inverted for spoken-mandatory. **Not fixed: the filler is outside
this lane's fences.**

### Seam 10 — four of six verbs are unreachable from a program-shaped question (stops FOUR)

```
classify_predicate no_match  query='What is the burn rate for the Notional Program Meridian?'
  subject_uri=fin#Program  compatible=['mesh:finEacCalculation','mesh:finVarianceAnalysis']
```

`compatible_count=2`. The six verbs declare FOUR subjects — burn rate and indices hang off
`fin:PerformanceMeasurementBaseline`, funding status off `fin:FundingLine`, drivers off
`fin:ControlAccount`. **The classifier is right every time**; it was handed two verbs, neither of
which answers the question. Nothing traverses Program → its PMB.
Filed: `[[four-subjects-means-four-questions]]`. **This one is mine** — the subjects are my
authoring decision.

### The corrected seam table — CURRENT as of 2026-09-05

**Fifteen seams, not three.** The audit opened calling it one, revised to three, and each
repair uncovered the next — because every one of them rendered as the same card.

| seam | state | owner | stopped |
|---|---|---|---|
| 1–7 routing, entitlement, verbs, payloads, classes, archetypes, HUD | ✅ verified | — | — |
| 8 `rendersAs` bindings — `fin:` absent from two prefix maps | ✅ **fixed** | mine | all six |
| 9 `fill_slots` budget applied to spoken-MANDATORY slots | ✅ **fixed** `863a3a4` | filler lane | all six |
| 10 four verbs on subjects no question names | ✅ **fixed** | mine | four of six |
| 11 three minted archetypes never projected → generative renderer | ✅ **fixed** | mine | three of six |
| 12 `PERIOD_SERIES` is a cost curve — the binding was never satisfiable | ✅ **fixed** via `mesh:MultiSeries` | mine + cortex | two of six |
| 13 a rebind INSERTS rather than replaces; the stale binding wins | ✅ **cleared** (4 rows deleted) | mine | two of six |
| 14 projector passthrough dropped `reference` / `verdict` | ✅ **fixed** | mine | two cards' captions |
| 15 `ELICITATION` had no projector path at all → `KNOWLEDGE_DOCUMENT` | ✅ **fixed** `c8db01b` | mine | every menu-less ask |

**Ten of the fifteen were mine.** The two that were not — the filler budget and the
archetype contract — were both found by another lane reading a symptom I had misdiagnosed.

#### What each repair revealed, which is the shape worth carrying

Seam 8 fixed and **nothing observable changed**, because 9 was behind it. 9 fixed and three
cards drew while three fell to a generative renderer — 11. 11 fixed and two cards mounted and
refused — 12. 12 fixed and the old binding still won — 13. 13 cleared and two captions were
missing — 14.

Seam 14 fixed and a finance question that named no program drew as a document rather than an ask
— 15, and it is the one that could NOT have been fixed the way it was dispatched: the table it
was sent to requires a non-empty list, and a menu-less ask has none.

**Seven repairs, each correct, five of which produced no visible improvement at the time.** A
card reading `Knowledge Document · No content available` named none of them, which is
`[[a-degradation-must-name-itself]]` measured rather than argued.

#### The instrument that makes the NEXT one visible

Every seam above was found by reading logs and probing pods, because the card itself said the
same thing in all fifteen cases. `169faef` changes that for one whole class of them:
`selection_basis` now travels on the response as `presentation_provenance` instead of dying in a
`logger.info`.

| basis | means |
|---|---|
| `output_uri+payload` | the declared output matched a registered capability |
| `payload-only (output_uri matched no capability)` | it did not — **the payload chose the card** |

Seams 8, 12 and 14 were all the second case and none of them announced it. **This does not
prevent a sixteenth seam; it makes one legible from the artifact rather than from a pod.**

#### The one that is still open

| | |
|---|---|
| all six payloads satisfy every declared refusal condition | ✅ measured |
| **a person has seen the cards render** | ⏳ **not yet** |

That distinction is the audit's own lesson: this document once said "all six draw" on the
strength of an archetype label and was wrong. It stays `open` until someone reloads.

### One more thing the runs showed

`supervisor_query_job` takes **5–6.5 minutes** per question and the BFF gives up first, reporting
`dagster_run_failed` / `ui_payload_timeout` for runs that go on to log `RUN_SUCCESS`. A failure
the user sees for a run that succeeded is its own defect; unowned and unfiled here.

## What remains

**One thing, and it is not code.** Every seam in the table above is repaired, deployed and
measured. The bar this audit was opened against has one clause left:

> *no "routing works" standing in for "the card appeared."*

1. **Reload the UI and read the six cards.** Not an archetype label, not a payload that
   satisfies its contract — the rendered card. This document has already been wrong once by
   substituting the first for the third, and it was wrong in exactly the direction that reads
   like success.
2. While reloading: **omit a program name.** The typed-ask path (`mesh:AskCard`, `ELICITATION`)
   is primed and on master and has never been walked by a person. Whether the
   `KNOWLEDGE_DOCUMENT` fallback is gone is unmeasured, and it is a different lane's next item
   either way.

*(The original list here — push two commits, re-register the menu, assert six rows — is done:
the commits shipped, the menu carries 6 `fin:` rows, and the six phrasings were driven. It
read as blocked on a classifier refusal that was resolved days ago.)*

## Method note

The first attempt to call the six verbs failed 6/6 with an identical slot-refusal, because the
envelope was flat and `MeasureRequest` nests under `params`. **A uniform extreme result across a
whole battery is this lane's standing tell for a broken instrument** — see
`[[assert-on-the-claim-not-its-neighbour]]` — and it was treated as one rather than reported.
