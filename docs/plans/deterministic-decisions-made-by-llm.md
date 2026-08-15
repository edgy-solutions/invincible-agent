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
