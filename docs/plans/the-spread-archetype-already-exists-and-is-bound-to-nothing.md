---
id:         the-spread-archetype-already-exists-and-is-bound-to-nothing
status:     open
owner:
blocked-on:
repo:       invincible-agent (+ cortex-ui for the contract's field list)
code-site:  agent_fleet/presentation_agent/capabilities.py (no row claims COMPETING_MEASURES), agent_fleet/presentation_agent/main.py (_PROJECTED_ARCHETYPES passthrough), cortex-ui/src/components/planning/CompetingMeasures.contract.ts
summary:    STEPS 1-4 DONE 2026-09-15 (binding, field-name join, reference_value emitter, verdict); OPEN for the residue nobody owns yet - 18 mirror rows outside the fin namespace, unpartitioned on purpose, and scope_label declared by the contract and emitted per-row by every finance verb. The archetype three competing forecasts need already exists end to end as COMPETING_MEASURES - projector passthrough, frontend component, contract, glyph - and no capability row claims it, so fin_eac_comparison is bound to nothing. Not a new archetype and not cortex-60's work. Three unasserted joins between individually-correct declarations: the missing row, a projector allowlist that passes lowest_eac/highest_eac while the contract reads lowest_value/highest_value, and a reference_value the frontend declares and nobody emits. Derived rather than grepped, the unbound set is SIX archetypes, not one.
---

# The SPREAD archetype already exists, under another name, bound to nothing

**Filed 2026-09-15 — `lane/91`. This corrects the premise I was dispatched on, and it makes the
work smaller and moves it out of cortex-60's lane.**

The routing was: *"three forecasts side by side is a shape the archetype list doesn't have;
that's the SPREAD archetype the method registry was always going to need, and it goes on
cortex-60's list."*

**The archetype exists.** It is called `COMPETING_MEASURES`, it was added 2026-09-11, and it
exists at every layer:

| layer | artefact | state |
|---|---|---|
| engine | `_eac_comparison_summary` in `measures.py` | emits the envelope |
| projector | `_PROJECTED_ARCHETYPES["COMPETING_MEASURES"]` | passthrough present |
| frontend | `CompetingMeasures.tsx` + `.contract.ts` + `.test.tsx` | component present |
| glyph | `ArchetypeGlyph.tsx:120` | case present |

Its contract header names this exact consumer: *"Its first consumer is estimate-at-completion by
all three earned-value formulas."* And it argues the case R-001 made — *"FORECAST_MEASURE draws
ONE method and refuses to choose silently. This draws the disagreement itself."*

So nothing needs building. What is missing is **three joins between declarations that are each
individually correct**, which is why no per-layer check can see any of them.

## ⚠ AND IT IS ONE OF SIX — I FILED A SAMPLE AGAIN

I wrote "no row declares `COMPETING_MEASURES`" from a grep for that one name. Derived instead,
by diffing the projector's table against the archetype values the capability rows actually
declare:

    IN THE PROJECTOR, CLAIMED BY NO CAPABILITY ROW:
        CANVAS_SEED  COMPETING_MEASURES  INTERVAL_TIMELINE
        MATRIX_GRID  PERIOD_SERIES       THRESHOLD_GRID

**Six**, and `COMPETING_MEASURES` is not a special case — it is the one that happened to have a
verb waiting for it. *A filed defect is a sample, not a census*, and the grep that produced the
sample is the same instrument defect each time: **I searched for a name instead of deriving the
set.**

The opposite direction also has entries, and I am NOT claiming these are defects:

    CLAIMED BY A ROW, ABSENT FROM THE PROJECTOR:
        ASSET_STATE_METRIC  CHART_WIDGET  HAZARD_DECLARATION
        KNOWLEDGE_DOCUMENT  PROCESS_TOPOLOGY

`KNOWLEDGE_DOCUMENT` is the fallback every unbound subject already renders as, so at least one of
those five is absent from `_PROJECTED_ARCHETYPES` **by design**. Whether the other four are is
unchecked, and saying so is the difference between a census and a second sample. Someone who
knows the projector's contract should partition that list: each name either in the table or on
an exclusion list **with a reason**.

The derivation, so the next person runs it rather than greps:

```python
declared = set(re.findall(r'^\s*"([A-Z_]+)":', projected_archetypes_block, re.M))
used     = {c["archetype"] for c in PRESENTATION_CAPABILITIES}
declared - used, used - declared
```

The finance half of the same derivation returns exactly one verb — `fin_eac_comparison` — so
that claim below **is** a census for this engine.

## 1. No capability row claims the archetype

`PRESENTATION_CAPABILITIES` has no row whose `subject_uri` is
`fin:EstimateAtCompletionComparison` — and, checked the other way, **no row anywhere declares
`archetype: COMPETING_MEASURES`.** The archetype has been in the projector for four days bound
to nothing, and the verb whose exact fields its passthrough enumerates is bound to nothing.

This is what `test_every_envelope_field_a_verb_declares_survives_its_archetype_passthrough`
reports as *"bound to no archetype"*, and why the census seal for verdicts skips the verb.

## 2. The projector passes the pair the frontend does NOT read

The engine emits **both** spellings, deliberately, with the reason written beside them:

> *"`lowest_eac` is a DERIVED SUMMARY NAME I coined, not domain vocabulary an analyst would
> recognise — so unlike `eac` it has no claim to stay, and the structural name is the one that
> should be preferred."*

The projector's allowlist kept **only the domain-named pair**:

```
projector  : ... lowest_eac,   highest_eac,   ... value_label, scope_label
contract   : ... lowest_value, highest_value, ... reference_value, scope_label
```

So binding the row without fixing this renders a card whose high/low are blank, while every
layer's own tests stay green — the engine emits the field, the contract declares it, and the
allowlist between them drops it. **The same defect the `verdict` fix closed today, on the same
table, one archetype along.** Four names, and the odd-one-out is the domain-flavoured one inside
a structural archetype whose header says *"nothing here knows that."*

## 3. `reference_value` is declared by the frontend and emitted by nobody

`COMPETING_MEASURES_ENVELOPE_FIELDS` includes `reference_value` — for this verb, the BAC the
spread is a fraction of. The engine emits `bac` **per row** and `spread_percent_of_bac` on the
envelope, but no `reference_value`. A card drawing "spread against the reference" has the
percentage and not the thing it is a percentage of.

Decide whether `reference_value` is the envelope name for BAC here; if so the engine emits it
beside `spread_percent_of_bac`, computed from the same `d_bac` already in hand.

## Why no check caught any of it

**Every endpoint is verified and the join is asserted nowhere.** The engine seals what it emits.
The contract seals what the component reads. The projector seals its own table's shape. An
invariant *between* two declarations is invisible to every per-declaration check, and all three
items here are that shape.

The one instrument that did see anything is the envelope-passthrough seal, and only because it
crosses two of the three layers. **Nothing crosses into the frontend contract at all** — that
file and `_PROJECTED_ARCHETYPES` are two lists of field names in two repositories with no
assertion that they are the same list.

> A seal that crosses a repository boundary is the only kind that can find this class. That is
> the durable item here, and it is bigger than this verb.

## Order, when it is taken

1. Reconcile the projector passthrough with `COMPETING_MEASURES_ENVELOPE_FIELDS` — names first,
   because a row bound before this renders blanks.
2. Decide `reference_value`; emit it if yes.
3. Add the capability row.
4. Give `fin_eac_comparison` its `VERDICT` entry — `_verdict_eac_spread` is already written and
   sealed in `test_every_verb_says_what_it_found.py` — and delete that file's skip, which then
   has nothing left to excuse.

Steps 1–4 are all in this lane's fence. **None of it is cortex-60's**, beyond confirming
`reference_value` and that the contract's field list is the one the component actually reads.


---

# CLOSED 2026-09-15 — and the diagnosis changed TWICE on the way

**Steps 1–4 are done.** The passthrough carries `lowest_value`/`highest_value`/`reference_value`,
the engine emits `reference_value`, the capability row exists, `fin_eac_comparison` has its
`VERDICT` entry, and the census seal's skip is gone. Four seals, 8 of 8 mutations red.

## The first correction: it was never a missing archetype

Dispatched as "a SPREAD archetype cortex-60 needs to build". `COMPETING_MEASURES` already existed
at every layer with this verb named in its contract header as its first consumer.

## The second correction: it was never "bound to nothing" either

I wrote that no registry claimed it. **Wrong.** cortex-ui's `DERIVED_BINDINGS` binds
`fin:EstimateAtCompletionComparison -> mesh:CompetingMeasures`, with the same `object_uri` I then
wrote into the backend row — and it binds **all six** of the archetypes I had listed as unbound.

There are **two mirrors of one binding set**: `PRESENTATION_CAPABILITIES` here and
`DERIVED_BINDINGS` there. The archetype was bound in one and not the other, so:

- the frontend would draw it, and
- the mesh never advertised it, so nothing would route to it.

**Each mirror was complete on its own side.** That is why neither repo's tests saw it, and it is
a sharper statement of the same law: *every endpoint verified, the join unasserted* — except the
endpoints here are two registries that are supposed to be copies.

## The prefix trap, walked into and caught

My first mirror diff reported the 7 cost rows as mismatched. They are not: the backend spells
them `cost:CategoryBreakdown` and the frontend
`http://invincible-agent/cost#CategoryBreakdown`. **Same binding, two spellings**, and this repo
has already paid for exactly that — six `fin:` rows were refused by Contract D for being emitted
compact. Expanding both sides first is why the real diff is 25 shared rather than 18.

`test_the_two_MIRRORS_agree_on_every_fin_subject` expands through the module's own
`_IRI_PREFIXES_FOR_LOOKUP` rather than a transcribed copy.

## The residue, derived and deliberately unasserted

With prefixes expanded, the full mirror diff is:

    FRONTEND BINDS, BACKEND DOES NOT (15)   all mesh: subjects — CanvasSeedResult,
        ContributionSequence, DecisionArtifact, EffectSet, FundingGapSet, HumanApprovalTask,
        InstancesByProperty, IntervalSchedule, LoadThresholdGrid, MaturityMatrix,
        PartObsolescenceReviewBatch, PeriodCostSeries, SlotElicitation, WithheldPanel,
        WorkflowObservation

    BACKEND ADVERTISES, FRONTEND DOES NOT (3)   safety:DeferralRiskCard,
        safety:OrphanedHazardSet, safety:RiskAssessmentDraft

**The `fin:` half is sealed in both directions. The other 18 are not, on purpose.** The pattern is
that engine-namespace subjects are advertised by the backend and `mesh:` vocabulary is bound by
the frontend — but that is **observed in two files, not written down anywhere**, and asserting it
would be this lane ruling on the planning and safety lanes' designs.

Whoever owns those two should partition them: each row either in both mirrors, or on an exclusion
list **with a reason**. The derivation is in the seal.

## And `scope_label` is declared by the contract and emitted by no finance verb

Ten envelope fields are declared; nine now arrive. `scope_label` is on the **rows** of every
finance verb and on the envelope of none — the assembler builds `value_unit`, `value_label`,
`series`, `reference` and `verdict` at envelope level and has never built this one. Fleet-wide,
not specific to this verb.

Listed in `_CONTRACT_FIELDS_SUPPLIED_PER_ROW` with that scope, and **the seal refuses to let it
rot**: the entry fails if the contract stops declaring the field, and fails if it starts arriving
on the envelope. What it does *not* claim is that a card reads it from the rows and is therefore
fine — that is unchecked, and a residue named is not a residue excused.
