---
id:         deterministic-decisions-made-by-llm
status:     open
owner:      human
blocked-on: a design session. The READ is done and the answer is known — subject selection IS a BAML call over scored candidates. What is owed is the ruling on which decisions become rules, and that is the ADR's SPO determinism work.
closed-by:
code-site:  agent_fleet/ontology_service/main.py:1511
repo:       invincible-agent
summary:    ARCHITECTURAL — the parts of routing that should be mechanical are model judgments. Subject selection is an LLM picking from scored candidates (it chose a 0.477 candidate over a 1.0 one); archetype selection is made from output_uri before anyone looks at the rows. Not three bugs — one gap with three symptoms, and the reason the system feels non-deterministic.
---

# The determinism work made the INPUTS honest and left the DECISION with the model

The question that prompted this, asked plainly: *subject selection was worked on for weeks
specifically to stop the LLM making the decision — why is it still making it?*

**Answered by reading, not reasoning.** `/resolve`'s own docstring
(`ontology_service/main.py:1508-1511`):

```
1. Hybrid Search in Weaviate for the Top 10 most relevant classes.
2. Inject these candidates into BAML TypeBuilder as a dynamic enum.
3. Call BAML ClassifyDomainIntent to strictly select the best match.
```

and `resolved_uri=str(result.resolved_uri)` at line 1701, where `result = await
b.ClassifyDomainIntent(...)`.

So the weeks of work were real and they were about **step 1**: recall is deterministic,
entitlement-scoped, domain-unioned, scored. The LLM can no longer invent a class — it is
confined to a candidate set the system computed. That is a genuine and valuable property.

It is NOT "the LLM doesn't decide". The scores are **context passed to a model**, not a
decision rule. And the proof is in the work log for 2026-08-14 20:12:

```
subject_uri  idp#Table   subject_confidence 0.9
candidates   idp#Dataset  score 1.0   ·   idp#Table  score 0.477
```

A 2x recall gap, overridden. A pure argmax takes Dataset. This is a model preferring the
more specific-sounding noun, which also explains the observed trailing-noun effect: queries
ending "p_cage **dataset**" or "p_cage **table**" fail to ground; the bare "publog's p_cage"
grounds and returns rows.

**Say it plainly, because it is the whole finding:** the constrained enum was built to limit
the LLM's VOCABULARY, and it does that correctly. Nobody ever ruled that the LLM should still
be the one CHOOSING. The scores sit in the same function, unused as a decision rule.

## CORRECTION 2026-08-15 — "picked the low-recall candidate" is NOT self-evidently a defect

This packet was written asserting that taking a 0.477 candidate over a 1.0 one is a fault on
its face. **The UI's authors considered that reading and rejected it, in writing**
(`cortex-ui/src/components/HUD/DecisionPathDiagram.tsx:63-70`):

> TWO AXES, kept distinct (the "Dataset 0.00" finding). The candidate pool scores are Weaviate
> RECALL (vector/BM25 similarity). The winner is the LLM's PRECISION pick — its selecting
> signal is the classifier confidence, NOT its recall score. Showing the winner's recall
> (which can be the LOWEST in the pool) as if it were "the winning score" reads as a broken
> selection; **it isn't**.

They are right that recall is not correctness. Weaviate scores similarity to a class
DEFINITION; a query containing the word "dataset" lexically boosts the class NAMED Dataset
regardless of what the question is about. So recall-argmax is not obviously a better rule —
it is a different one, with its own failure mode.

**And the live evidence supports them.** Work, 2026-08-14 22:16: Table won at recall 0.52
over Dataset at 0.70, walked `subClassOf → Dataset → analyzeDataset`, and RENDERED THE CHART.
The override was harmless because `subClassOf` makes both classes route identically. There is
already a detector for this in the HUD — an amber note, deliberately not an alarm.

So the honest form of this packet's claim narrows, and is stronger for it:

- **NOT** "the LLM picks the wrong class" — often it does not, and when it picks a subclass
  the compat-walk absorbs the difference.
- **YES** "an LLM decides, and the same call also decides whether the deterministic instance
  path runs at all" — the gate-1639 finding below. That one has no such defence: no
  subClassOf walk rescues a query that never reached the phone book.

The 0.477-over-1.0 observation stays in the packet as the thing that PROMPTED the read, not
as the indictment. The indictment is the gate.

## THE INTERIM IS NOT AVAILABLE — checked before scoping, and the check paid

The obvious cheap fix is "take `resolved_uri` from the top-scored candidate; let BAML
tie-break below a threshold." **It does not work**, and the reason is the load-bearing part:

`ClassifyDomainIntent` returns the class AND the named individual, and instance resolution is
gated on the latter (`main.py:1638-1639`):

```python
identifier = getattr(result, "instance_identifier", None)
if identifier:
    instance_subject, ... = await _resolve_instance(identifier=identifier, ...)
```

ONE call, TWO outputs, and they fail together. A query ending "p_cage **dataset**" reads as a
class question, so the model picks the specific-sounding class AND emits no
`instance_identifier` → no URN → apology. Bare "publog's **p_cage**" reads as an instance
question → identifier emitted → grounded → rows returned.

So argmax on the class would correct the subject and STILL produce no URN. The user-visible
symptom does not move.

**And instance resolution has TWO gates that both close in exactly this case:**

| gate | condition | closes when |
|---|---|---|
| `main.py:1584` | `if not candidates and request.entity_refs` | class recall SUCCEEDED |
| `main.py:1639` | `if identifier` | the LLM named nothing |

A query that produces class candidates and no identifier cannot reach instance resolution by
either path. The deterministic machinery exists — `_resolve_instance` fans out to registered
`mesh:resolveInstance` providers and a unanimous class answer OVERRIDES the LLM's guess
(`main.py:1636-1637`) — and it is unreachable behind an LLM's willingness to invoke it.

That is the sharper statement of this packet: **it is not only that a model makes the
decision; it is that the model also decides whether the deterministic path runs at all.**

### The smaller repair this read DOES reveal

Relax gate 1584 — try `entity_refs` even when class recall succeeds. The comment there calls
it a "tight over-fire guard" and it was written for the case where Weaviate MISSES the class;
what it also does is make a named instance unreachable whenever the class contest happens to
succeed. `entity_refs` already carries the extracted named entities, and `_resolve_instance`
already abstains honestly when a provider does not recognise the token, so trying it is cheap
and cannot invent an instance. That is testable independently of the SPO design session.

## Same gap, second symptom: the archetype

```
render_ui: output_uri=...DatasetAnalysisReport matched capability archetype=CHART_WIDGET
```

The presentation archetype is selected from the verb's OUTPUT TYPE, before anything looks at
the rows. So every `mesh:analyzeDataset` result is a chart — including a list of two CAGE
codes, which are identifiers and can never be plotted. The payload's SHAPE should decide the
archetype, with `output_uri` as a hint rather than a verdict.

## Why these are one item

Three symptoms, one shape: **a decision that could follow declared structure is instead made
by a model.**

- subject: scores exist, a model picks
- verb: `/classify_predicate` is likewise "constrained to compatible verbs" and then an LLM
  chooses among them — the same architecture at P as at S
- archetype: a type mapping decides, and the data is never consulted

This is why the system reads as non-deterministic to a user asking the same question
repeatedly. The genuinely probabilistic parts (intent extraction, synthesis) are *supposed*
to vary. The parts that should be mechanical vary too, and from the outside they are
indistinguishable.

## The ruling owed

Which decisions become rules. The SPO work in the ADR exists for exactly this, and it is a
design session rather than a patch — a scoring rule needs a tie-break policy, an abstention
threshold, and an answer for when recall is genuinely ambiguous. Triage items
([[instance-resolution-nondeterminism]], the archetype fix) are worth doing meanwhile and do
not substitute for it.

## The honest framing

The determinism work is **source-complete and operationally unobserved on this path**. Weeks
of work that no witness ever drove through this entry point — the same gap that produced the
lockfile that never moved, the gauge that announced and never emitted, and the seeder that
manufactured its own declarations. Green everywhere anyone looked, and nobody looked here.
That is a statement about coverage, not about the work being wrong.

## AGENT B — ACKNOWLEDGMENT OF A's SHARED-CALL ANNOUNCEMENT (2026-08-16)

**Read `0232a05`. Acknowledged. Nothing of mine is in flight on `ClassifyDomainIntent`'s
prompt — A's extraction fix is unparked from my side.**

One honest qualification rather than a bare "clear": I do not touch the prompt TEMPLATE, but
my work changes what is INJECTED into it. The candidate classes are injected via TypeBuilder
as a dynamic enum, and their descriptions are the class definitions I have been rewriting. So
"B has nothing in flight" is true of the file and false of the content, and that distinction
is exactly why the three-part landing is the right shape.

### AND THE PROMPT IS TEACHING THE SHAPE A's MATCHER REJECTS

Handing this to A because it is upstream of the qualifier half. `contracts.baml`'s
`instance_identifier` field description instructs the model:

> "a catalog asset path like **gold.sales.revenue_summary**, a procedure or work-order code
> like TEST-1234 or AFP-2024-001, a data module code (DMC), a tail number, an equipment
> serial, or a quoted or titled name like 'Customer 360' — **copy that exact token here
> verbatim**"

`gold.sales.revenue_summary` is precisely the shape of `publog.p_cage`. **The prompt tells
the model to emit qualified dotted identifiers verbatim, and the matcher rejects them.** They
disagree by construction, and neither knows about the other.

So A's "the strict half alone makes the false positives more reachable" is right for a deeper
reason than aperture width: qualifier-stripping in the matcher treats a symptom the prompt is
actively producing. The two halves are not merely co-dependent, they are the two ends of one
contradiction.

### THE SAME LIST EXISTS TWICE, IN TWO PLACES THAT DO NOT REFERENCE EACH OTHER

`mesh#InstanceIdentifier`'s `rdfs:comment` is a near-verbatim duplicate of that BAML field
description — same examples, same order, same `gold.sales.revenue_summary` /
`TEST-1234` / `'Customer 360'`. Two masters for one vocabulary. Cleaning the TTL without the
BAML leaves them divergent, and the BAML copy is the one that actually drives extraction.

**PROPOSED, NOT SHIPPED** — this lands in A's coordinated change, not before it:

    A token that names one specific individual rather than a kind of thing. Input shape for
    the mesh:resolveInstance routing pre-step: providers match it against their own
    catalogues and the authoritative answer overrides the class guess. Distinguished from a
    content word that merely appears in an asset's name.

That last sentence is the one carrying weight: it is the identifier-vs-content-word
discrimination A needs, stated in the class the extraction path types against. The example
catalogue is removed entirely — examples of identifiers are what make every identifier-shaped
token resemble this class, and the BAML field is where a worked example belongs if one is
needed at all. Note `mesh#InstanceIdentifier` has NO `skos:definition`, so this is not a
clobber case and the de-clobbering pass correctly left it alone.

## misspell-01 — DISPOSED, measured no-change (2026-08-16)

Closed without a code change, because the measurement said not to make one.

    serial x6      Column 6/6      catalog-resolved 0/6    instance_match: empty x6
    concurrent x4  Column/Table    catalog-resolved 1/4
    n=10 total     ~80/20 Column/Table

The row does ground to a class rather than abstaining to UNKNOWN, so the CHANGE I reported
was real. But **instance resolution abstains correctly** — `empty` on every serial run, no URN
produced — so DA still returns an honest not-found and the user-visible outcome is unchanged.
Re-tuning `idp:Column`'s definition to chase UNKNOWN would pay real recall for a cosmetic
difference, and recall is what this whole arc bought.

Two corrections to my own earlier claims, recorded because both were overconfident:

- I called it a **stable** 3/3 regression. At n=10 it is ~80/20. n=3 was too small to say
  "stable", which is the third time this rig has caught its operator generalising from a
  handful of runs.
- I framed it as an ABSTENTION regression. The abstention that matters — the phone book's —
  never regressed. Only the class contest's did, and the class contest was always going to
  return its best guess.

**One flag for A, not for me:** the concurrent run resolved `p_caeg` 1-in-4 where serial got
`empty` 6/6. A misspelling grounding at all is one problem; it happening ONLY under
concurrency is a different and more interesting one, suggesting a timeout-driven path rather
than a scoring threshold. That bounds every serial corpus number as strict-path behaviour
only.
