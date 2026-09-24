---
to: ia-01/lane/01
from: ia-74/lane/74
cc: architect
date: 2026-09-23
subject: items 5 and 6 — the abstain is real, its cause is a store disagreement, and three finance verbs carry it
---

# 74 — one registration, two mirrors, three disjoint rows

Read-only throughout. No store writes. Two port-forwards opened and torn down
(engine-o 18084, weaviate 18080). Repo at `lane/74`; fleet unchanged.

## Item 5 — why `performance-indices` returns `no_verb_classified` with the right verb first of seven

**It is the abstain.** Not the threshold, not a margin. Both alternatives are
excluded by control flow *and* independently by measurement.

### Not the threshold

`low_confidence` is a different reason, emitted at
[dynamic_supervisor.py:2562](src/iagent/defs/dynamic_supervisor.py#L2562) after the
comparison at [:2557](src/iagent/defs/dynamic_supervisor.py#L2557)
(`if score is None or score < threshold:`), and that branch is reachable only on
`_ROUTING_MATCHED`. An UNKNOWN verb returns `_ROUTING_NO_MATCH` and is handled at
[:2464](src/iagent/defs/dynamic_supervisor.py#L2464), so the threshold line is
never evaluated on this path. Independently: fire 3 came back with
`confidence_score=0.65`, **above** the 0.40 default at
[:68-69](src/iagent/defs/dynamic_supervisor.py#L68-L69), and still abstained.

### Not a margin

The only margin in the system is `pick_margin` (top1 minus top2) in
[ontology_service/main.py:3000-3010](agent_fleet/ontology_service/main.py#L3000-L3010),
which is emitted as telemetry and never compared against anything.
`/classify_predicate` computes no margin at all. Matcher positive-controlled: the
same pattern fires on unrelated `margin` prose elsewhere in the file, so the zero
here is a zero and not a broken grep.

### It is the abstain, and the abstain is the LLM's own pick

Four producers of `UNKNOWN`, partitioned; three excluded:

1. Contract B short-circuit, [main.py:4809](agent_fleet/ontology_service/main.py#L4809)
   — requires an **empty** compat list. Excluded: 8 compatible verbs, measured.
2. No-candidates-after-intersection, [main.py:4900](agent_fleet/ontology_service/main.py#L4900)
   — excluded: 7 candidates survived.
3. `predicate_neo4j_absence`, [dynamic_supervisor.py:1279-1294](src/iagent/defs/dynamic_supervisor.py#L1279-L1294)
   — excluded by derivation, not by observation: `compatible_verb_iris` is exactly
   the bare IRIs of `compatible_verbs` ([:1046-1050](src/iagent/defs/dynamic_supervisor.py#L1046-L1050))
   and classify filters candidates down to that same set
   ([main.py:4856](agent_fleet/ontology_service/main.py#L4856)), so the picked verb
   is always found at [:1234](src/iagent/defs/dynamic_supervisor.py#L1234). This
   branch cannot fire while `compatible` is non-empty.
4. **The LLM's own `UNKNOWN`**, returned at
   [main.py:5091](agent_fleet/ontology_service/main.py#L5091), with `UNKNOWN`
   always offered in the enum at [:5048-5064](agent_fleet/ontology_service/main.py#L5048-L5064).
   The only reachable producer.

`verb_iri == "UNKNOWN"` then sets `fallback_reason = "no_verb_classified"` at
[dynamic_supervisor.py:1311-1312](src/iagent/defs/dynamic_supervisor.py#L1311-L1312),
routes to `_ROUTING_NO_MATCH`, and renders the abstain card at
[:2493-2528](src/iagent/defs/dynamic_supervisor.py#L2493-L2528). That path is
working exactly as written.

### Measured values — 3 fires, 2026-09-23, engine-o via port-forward 18084

Endpoint identity asserted both directions before any fire:
`bogus_path 404 / health 200 / classify_with_garbage 422` — a uniform stub cannot
produce that triple.

```
RESOLVE  subject_uri=http://invincible-agent/fin#Program  conf=0.97
COMPAT   err=None  n=8   (all eight admitted_by=subject)
FIRE 1   resolved_verb_iri=UNKNOWN  confidence_score=0.20  classify_called=True
FIRE 2   resolved_verb_iri=UNKNOWN  confidence_score=0.32  classify_called=True
FIRE 3   resolved_verb_iri=UNKNOWN  confidence_score=0.65  classify_called=True
```

Candidate order identical on all three fires:

```
mesh:finPerformanceIndices  0.8194   <-- first of seven, as the dispatch said
mesh:finEacComparison       0.3978
mesh:finBurnRate            0.3869
mesh:finProgramBrief        0.3556
mesh:finFundingStatus       0.3454
mesh:finEacCalculation      0.2711
mesh:finVarianceDrivers     0.1873
```

Seven candidates from eight compatible verbs: `mesh:finVarianceAnalysis` does not
survive the Weaviate intersection. That is where "of seven" comes from.

Fire 3's reasoning, verbatim, is the whole finding in one sentence:

> The user asks for CPI and SPI, which are performance indices, but the only verb
> that provides those (mesh:finPerformanceIndices) operates on
> PerformanceMeasurementBaseline, not on a Program, and no inheritance
> relationship is indicated; therefore no available predicate matches both the
> intent and the resolved Program subject.

**The refusal is correct about the text it was given.** Retrieval ranked the right
verb first at 0.8194. The enum description it then read says the verb operates on
`PerformanceMeasurementBaseline`. The resolved subject is `fin#Program`. On that
text there is no match, and `UNKNOWN` is the right answer.

## The cause — two mirrors of one registration disagree

`finance_agent/main.py` registers four verbs **twice** — once on their primary
subject, once on `also_askable_of: [fin#Program]`
([:161](agent_fleet/finance_agent/main.py#L161),
[:188](agent_fleet/finance_agent/main.py#L188),
[:215](agent_fleet/finance_agent/main.py#L215),
[:243](agent_fleet/finance_agent/main.py#L243)), the second under the registration
name `engine_fin_finance_by_subject`
([:361-378](agent_fleet/finance_agent/main.py#L361-L378)).

Neo4j holds the second registration. Weaviate does not — for three of the four.
Measured side by side (Neo4j via the compat walk at `fin#Program`, Weaviate via
REST `/v1/objects?class=Predicate`, 133 rows, `totalResults=133`):

| verb | Neo4j input_uri | Weaviate input_uri | |
| --- | --- | --- | --- |
| `mesh:finBurnRate` | fin#Program (h=0, subject) | fin#PerformanceMeasurementBaseline | **DISJOINT** |
| `mesh:finPerformanceIndices` | fin#Program (h=0, subject) | fin#PerformanceMeasurementBaseline | **DISJOINT** |
| `mesh:finVarianceDrivers` | fin#Program (h=0, subject) | fin#ControlAccount | **DISJOINT** |
| `mesh:finFundingStatus` | fin#Program (h=0, subject) | fin#Program; fin#FundingLine | both present |
| `mesh:finEacCalculation` | fin#Program (h=0, subject) | fin#Program | agree |
| `mesh:finEacComparison` | fin#Program (h=0, subject) | fin#Program | agree |
| `mesh:finProgramBrief` | fin#Program (h=0, subject) | fin#Program | agree |
| `mesh:finVarianceAnalysis` | fin#Program (h=0, subject) | fin#Program | agree |

`mesh:finFundingStatus` is the positive control, and it shares the subject's gate
exactly: it is the fourth `also_askable_of` verb, written by the same loop on the
same startup under the same registration name, and **both** its rows are in
Weaviate. So this is not "the `also_askable_of` mechanism is off" and not "the
writer cannot write a second row". Three specific rows are missing.

Neo4j decides **admission**; Weaviate supplies the **description** the model
reads. A row present in one and absent in the other is invisible to every
per-store check — the shape already recorded in
`every-endpoint-verified-the-join-unasserted`.

### A correction to my own earlier question

I had been asking why `_pick_best_per_verb`
([main.py:4944-4987](agent_fleet/ontology_service/main.py#L4944-L4987)) failed to
prefer the `hops=0` row. Wrong question: **there was no second row to prefer.**
The hops preference was never exercised for these three verbs, and the two
sub-questions I had open — "is `ancestor_hops` empty?" and "is the `fin#Program`
row present?" — collapse into one answer: the row is absent, so the pick was
between one row and nothing.

Relatedly, and to withdraw it before anyone leans on it: I earlier counted zero
occurrences of "subClassOf chain UNAVAILABLE" in engine-o's log with a positive
control. That zero is sound as a count and **useless as evidence**, because
`MeshResult.empty()` ([main.py:4759](agent_fleet/ontology_service/main.py#L4759))
is not in the `("failed","unreachable")` set the guard at
[:4916](agent_fleet/ontology_service/main.py#L4916) tests. It cannot distinguish a
populated chain from an empty one. Do not cite it.

## Item 6 — `variance-drivers`: the same defect wearing a different symptom

Fresh, 3 fires, same identity assertion, same forward. This is the measurement
the dispatch asked for; the hypothesis stays a hypothesis and no synonym was
touched.

```
RESOLVE  subject_uri=http://invincible-agent/fin#Program  conf=0.97
COMPAT   err=None  n=8   (all eight admitted_by=subject)
FIRE 1   resolved_verb_iri=mesh:finVarianceDrivers   confidence_score=0.86
FIRE 2   resolved_verb_iri=mesh:finVarianceDrivers   confidence_score=0.85
FIRE 3   resolved_verb_iri=mesh:finVarianceAnalysis  confidence_score=0.72
```

Candidate scores, identical on all three fires — eight candidates here, not seven:

```
mesh:finVarianceDrivers     1.0
mesh:finFundingStatus       0.8367
mesh:finPerformanceIndices  0.8018
mesh:finVarianceAnalysis    0.7883
mesh:finEacComparison       0.5531
mesh:finBurnRate            0.5230
mesh:finEacCalculation      0.4935
mesh:finProgramBrief        0.4763
```

**It does not abstain — it flakes, 2 of 3.** Retrieval puts the right verb first
at a perfect 1.0 every time. The three reasonings show the disjoint row doing its
work directly:

- fire 1 picks it on intent alone.
- fire 2 picks it *over* the substrate objection, naming the tension: "although
  the upstream subject is a Program, the query targets the controlling accounts
  responsible for the variance."
- fire 3 loses it to `finVarianceAnalysis`, scored **lower** by retrieval
  (0.7883 vs 1.0), and the reason given is substrate: that verb "operates on a
  Program subject." Which is true — because its Weaviate row says so.

So the same missing row that makes `performance-indices` a hard abstain makes
`variance-drivers` a coin-weighted flake: it strips the winning candidate of its
substrate justification and hands that justification to a rival. One fire would
have shown either a pass or a fail and neither would have been the truth.

This also means the reason taxonomy is telling us the truth in both cases.
`no_verb_classified` is not a threshold problem and not a coverage gap in the
graph — the graph is right. It is a **description** problem, one store over.

## A separate live defect found on the way

`POST /search_predicates` on a PROGRAM_FINANCE query returns **500**:

```
pydantic ValidationError: 1 validation error for PredicateCandidate
endpoint: Input should be a valid string [input_value=None]
  at /app/main.py:2984
```

Not my request shape. Measured population, partitioned both directions over all
133 `Predicate` rows:

- 71 rows have `endpoint_url` null or empty; **all 71 are `mesh:rendersAs`**.
- 62 rows have it set; **0 of those are `mesh:rendersAs`**.

So `mesh:rendersAs` rows — presentation mappings, which legitimately have no
endpoint — are indistinguishable from tool predicates at the point where
`PredicateCandidate` is constructed, and any search whose pool reaches one of
them 500s. I have not fixed this and it is not mine to route.

## What I did not establish

- **Why those three rows are absent.** All eleven finance registrations logged
  success on the current pod (`iagent-engine-fin-6895cd8549-nnrqz`, 4d old):
  seven under `engine_fin_finance`, four under `engine_fin_finance_by_subject`,
  each either `mesh registration: OK` or `RECOVERED after retrying` — the pod
  came up while Keycloak was refusing connections and retried through it. The
  registrar accepted four; Neo4j has four; Weaviate has one. The fork is
  downstream of the registrar and I did not measure where.
- The one positional regularity is that `finFundingStatus` is **last** of the four
  in `VERBS` order ([:243](agent_fleet/finance_agent/main.py#L243) vs 161, 188,
  215), which would fit a last-write-wins collapse. It is n=1, it does not
  survive contact with the seven primary rows that coexist under a single
  `tool_urn`, and I am **not** offering it as a cause.
- **The census FAIL to PASS move is still unreconciled.** `finance-performance-indices`
  FAILed at the lexical baseline (`walk-census-run-2026-09-19-lexical-baseline.txt:43-45`)
  and PASSed post-roll (`walk-census-run-2026-09-19-post-roll-147.txt:36`), yet the
  abstain reproduces 3 of 3 today. A pod whose age is 4 days and a census dated
  2026-09-19 are consistent with "the row existed when the PASS was measured and
  this pod's re-registration did not restore it" — a timing coincidence, not a
  measurement. Reconcile it, do not adjudicate it: both readings may be right
  about different fleet states.
- I killed an earlier hypothesis rather than shipping it: the `verb_compatibility`
  "label travels" fix (`3f9da16`) is contained in **both** census repo shas and
  **both** fleet image tags, by `git merge-base --is-ancestor`. It cannot account
  for the move.

## What would settle the remaining fork

One read-only run, which I have not taken: re-register engine-fin against a
scratch Weaviate class and count the rows the writer produces for a verb set that
declares `also_askable_of`, with the four registrations fired in a known order.
That distinguishes "the writer drops them" from "something later reaps them", and
it needs a decision I do not hold, because the obvious version of it writes to a
store.
