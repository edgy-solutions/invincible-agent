---
id:         column-intercepts-without-verb-coverage
status:     open
owner:      agent
blocked-on: nothing — measured, quantified, and the two repair options are both concrete. The choice between them is a design call the numbers already inform.
closed-by:
code-site:  tests/routing/STEP0_IDP_BUILD_SPEC.md
repo:       invincible-agent
summary:    MEASURED 48% — idp:Column intercepts nearly half of catalog queries and has ZERO compatible verbs, because it hangs off prov:Entity rather than idp:Dataset so no subClassOf walk reaches the nine catalog verbs. The class was restored to the Weaviate pool without the verb migration that was supposed to accompany it.
---

# Half the queries resolve to a class no verb can serve

First corpus run against sandbox, 2026-08-15, 81 non-errored probes across 29 phrasings:

| class | outcome | compatible verbs | probes |
|---|---|---|---|
| `idp:Column` | **no_compatible_verbs** | **0** | **39 (48%)** |
| `idp:Table` | ROUTED | 9 | 27 |
| `idp:Dataset` | ROUTED | 13 | 13 |
| UNKNOWN | subject_unknown | – | 2 |

Instance resolution FIRED on nearly all of these. The subject grounded. The query still died,
because the class it grounded to has nothing that can operate on it.

## Why Column specifically

`STEP0_IDP_BUILD_SPEC.md:86-93` places it deliberately:

```
prov:Entity
├── idp:Dataset
│   ├── idp:Table       ← subClassOf Dataset  (inherits 9 catalog verbs free)
│   └── idp:Dashboard   ← subClassOf Dataset
├── idp:Column          ← prov:Entity DIRECTLY (column-level queries are distinct)
├── idp:Pipeline        ← prov:Entity
└── idp:Job             ← prov:Entity
```

Table and Dashboard inherit the catalog verbs through `subClassOf`. **Column, Pipeline and
Job do not.** The nine verbs are all typed against `idp:Dataset`, and the compat-walk only
climbs — so a Column subject reaches nothing.

## This is the intercept STEP0 predicted, and it is back

That spec is explicit about the consequence, and about the fix it chose:

> **Resolution**: the 4 classes were deleted from Weaviate (Table, Column, Pipeline, Job) …
> The Weaviate retirement is a temporary measure that **gets undone in the same coordinated
> change as the verb migration extension to these subjects.**
>
> don't declare nouns in Weaviate before they have verb coverage, because they'll either
> intercept queries they can't serve or hit the no_compatible_verbs telemetry rise the
> Wave-1 predictions already called out.

**The undo happened. The verb migration did not.** All six classes are in the pool today
(verified by live read — the "only Dataset and Dashboard" status line is two months stale),
and Column now intercepts 48% of catalog traffic with zero coverage. The coordinated change
was uncoordinated.

## It also bounds the "precision override is harmless" claim

`cortex-ui`'s HUD argues, correctly, that a low-recall winner is not self-evidently a broken
selection ([[deterministic-decisions-made-by-llm]]). The measurement narrows that:

- **Harmless inside the subClassOf-covered set.** Work 22:16 picked Table at recall 0.52 over
  Dataset at 0.70, walked to Dataset, rendered the chart. The compat-walk absorbed it.
- **FATAL outside it.** Column is one hop sideways, not up. The same override that costs
  nothing when it lands on Table kills the query when it lands on Column.

So the override's safety is not a property of the override — it is a property of WHERE THE
HIERARCHY HAPPENS TO REACH. That is luck, not design, and it is worth saying because the
"two axes" defence is right about recall and silent about coverage.

## REPAIR SHIPPED 2026-08-15 (source) — awaiting an engine-a image build

Option 1 taken. Engine A now declares four second-registrations against `idp:Column`:
`findSchema`, `traceLineage`, `assessImpact`, `describeAsset` — chosen not by taste but by
`idp_extension.ttl`'s own Column definition ("queries about a specific column's **type,
lineage**, quality, or **downstream consumers**"). "Verbs follow questions", per the
ProcedureStep ruling at `neo4j_expert/main.py:112-140`: when a resolver picks a defensible
class no verb serves and the engine CAN answer it, the engine declares a second registration.
NOT a TTL change — subclassing Column under Dataset is semantically wrong and would also hand
it `enumerateCatalog` and `checkFreshness`, which are meaningless per column.

Engine A can genuinely serve these: `search_datahub` returns `columns:` on every asset and
accepts DataHub's `SCHEMA_FIELD` type, so this is a real answer path rather than an
advertised-but-unreachable one — the distinction the IO-manager protocol is careful about.

**Deliberately NOT declared**, recorded as decisions rather than oversights and pinned as
such: `enumerateCatalog` and `checkFreshness` (set-level / table-level), `filterByTag` (a set
operation), and `analyzeDataset` — Engine DA's `query_datahub_asset` takes a DATASET urn, so
a column urn would advertise a read that cannot execute. **A value query that resolves to
Column is a SELECTION defect, not a coverage one** ([[deterministic-decisions-made-by-llm]]),
and papering over it here would hide it.

Still source-only: sandbox runs `restate-analyst:latest` and needs the image rebuilt before
the registrations exist in any cluster. Verified post-upgrade on chart 0.3.37 that the gap is
NOT a staleness artifact — `Dataset 9 / Table 9 / Column 0 / Pipeline 0 / Job 0` on a fully
current deployment with freshly re-registered engines.

**Pipeline and Job remain at zero** and are deliberately out of scope: zero probes resolved to
either in the corpus run, so there is no measured demand. Job in particular needs a run-history
verb that does not exist. Extend when a number says to.

### And the fix surfaced a live instance of the trap it had to avoid

Adding second registrations means obeying the BAML rule the Engine E comment documents: the
TypeBuilder dedupes enum values by NAME, so N registrations of one verb collapse to ONE entry
whose description is whichever was added last — and the classifier then REFUSES the subjects
whose description was dropped. Nothing enforced it.

A new pin (`tests/routing/test_multi_subject_verb_descriptions.py`) found
`mesh:retrieveKnowledge` already violating it: four Engine W registrations shared a
description and `..._work_instruction` carried a manufacturing-specific one — the exact shape
that broke Engine E, sitting in the tree unnoticed. Harmonised; the subject signal was already
in `verb_synonyms`, which are per-registration and not deduped.

`mesh:resolveInstance` is EXEMPT and the pin says why: it is typed against
`mesh#InstanceIdentifier`, which no subject resolves to, so the router reaches it by provider
fan-out rather than by an LLM picking an enum value. Engine D describing catalog paths and
Engine E describing DMCs is correct there — each says what its own phone book knows.

## Two repairs, and the numbers already argue

1. **Extend the catalog verbs to cover Column** (and Pipeline, Job). This is the coordinated
   change STEP0 named and never got. `mesh:findSchema`, `mesh:traceLineage` and
   `mesh:lookupOwnership` are all meaningful on a column; `mesh:describeAsset` arguably is.
   Cost: a verb migration. Benefit: 48% of queries stop dying, and column-level questions
   become answerable for the first time.
2. **Re-shrink the pool** — delete Column/Pipeline/Job from Weaviate again. Restores the
   status quo ante and is what STEP0 did in June. **Rejected** unless (1) is genuinely far
   off: it re-hides the defect, it is the hand-deletion that started this whole thread, and
   it makes column-level questions permanently unanswerable rather than temporarily so.

A cheap third option worth considering as a stopgap, since it is honest rather than hiding:
**let the arity/eligibility gate route a zero-coverage subject to the generalist with a
NAMED reason** instead of the current silent `no_compatible_verbs` fallback — the user is
told "nothing in the mesh answers column-level questions yet", which is true and actionable,
rather than getting a generic non-answer.

## Note on where this was found

Not by inspection — by running the corpus. The trailing-noun hypothesis it was built to test
came back REFUTED on sandbox (18/18 grounded, both phrasings), and this fell out of the
`fallback_reason` column added almost as an afterthought. The measurement found a bigger
defect than the one it was aimed at.
