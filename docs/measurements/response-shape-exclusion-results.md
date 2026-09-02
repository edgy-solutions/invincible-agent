---
id:         response-shape-exclusion-results
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0025 (the can_view-filtered candidate pool); ADR-0031 (instance resolution ladder); the user's ruling to score SET MEMBERSHIP with winner movement secondary
code-site:  agent_fleet/ontology_service/main.py (/resolve), docs/measurements/engine-f-grounding-corpus-v1.json (the 20 phrasings and the pre-written prediction)
summary:    THE EXCLUSION WORKED, ON THE MEASURE IT CLAIMED. Per-row set disjointness, arm A, 20 phrasings: shape-occurrences 24 -> 0, sets containing >=1 response shape 14 -> 0, and ZERO rows returned an empty or absent set — the unhandled case the escalation asked to be flagged separately did not occur. Neo4j independently re-verified UNTOUCHED by me before scoring: 14 fin: classes, 6 response shapes under mesh:Response, 3 minted archetypes. INVARIANT 4 MOVED 8 -> 10 VERB EDGES AND THAT IS MINE, not the delete — today's subject widening added four Program-> edges with every primary intact. Winner movement: FOUR real moves, not five; the apparent fifth was a parsing artifact in my own harness. All three rows predicted to move, moved; two landed on the right class and one moved to a DIFFERENT WRONG class. TWO FINDINGS THAT ARE MINE, both visible only at the set level: `what is our burn rate` cannot be right because `fin:PerformanceMeasurementBaseline` IS NOT IN ITS CANDIDATE SET AT ALL, and `are we getting more efficient` returns 122 candidates with ZERO fin: classes from unrelated ontologies despite `domains=["PROGRAM_FINANCE"]` — a domain-scoping escape that pool[PROGRAM_FINANCE]=8 does not describe.
---

# Response-shape exclusion: results

Arm A (`domains=["PROGRAM_FINANCE"]`, `user_email=alice@example.com`), the 20-phrase corpus, one
draw per row, recording **the candidate set and the winner** on every draw per the standing rule.

## First: Neo4j, re-verified independently before scoring anything

Lane 1's probe said Neo4j was untouched. Checked separately, because this engine is what dies if
that is wrong:

| invariant | measured | expected | |
|---|---|---|---|
| `fin:` OntologyClass nodes | **14** | 14 | OK |
| `fin:` response shapes under `mesh:Response` | **6** | 6 | OK |
| minted archetypes under `mesh:Archetype` | **3** | 3 | OK |
| Engine F verb edges | **10** | ~~8~~ | **moved — MINE, see below** |

**The 8 → 10 is not damage.** Today's subject widening registered `fin:Program` as an additional
subject on four verbs, so the graph now holds four extra `Program → …` edges. **Every primary edge
is intact** (`PerformanceMeasurementBaseline → BurnRateSeries`,
`ControlAccount → VarianceDriverRanking`, `FundingLine → FundingStatusGrid` all present). Recorded
loudly because a changed invariant next to somebody else's delete is exactly the coincidence that
gets misattributed — the number moved for a reason with my name on it, hours earlier.

*Instrument note:* the first run of this check reported invariants 2 and 3 as **0**, because I
queried `SUBCLASS_OF` and the relationship is `subClassOf`. The database emitted an explicit
"relationship type does not exist" warning, and two invariants at exactly zero is this lane's
standing tell for a broken probe. Caught before it was reported as damage — the same defect as
2026-08-31, which is twice.

## PRIMARY — per-row set disjointness. The claim holds.

| | before | after |
|---|---|---|
| shape-occurrences across all sets | 24 | **0** |
| sets containing ≥1 response shape | 14 | **0** |
| **rows with an EMPTY or absent set** | — | **0** |

Not one of the six `fin:` response shapes appears in any candidate set for any of the 20
phrasings. **The shapes left the sets**, which is exactly and only what the exclusion claimed.

The empty-set row is called out because the escalation asked for it: a draw that returns *no* set
is the unhandled case in "assert on the set", and folding it into disjointness would score it as a
success. **It did not occur here** — every row returned a non-empty set.

## SECONDARY — winner movement, floor-annotated

**Four real moves, not five.** All three rows predicted in advance to move, moved:

| phrase | before | after | expected | |
|---|---|---|---|---|
| `rank the biggest contributors to the variance` | `VarianceDriverRanking` | `ControlAccount` | `ControlAccount` | **now correct** |
| `what is the funding status` | `FundingStatusGrid` | `FundingLine` | `FundingLine` | **now correct** |
| `what is our burn rate` | `BurnRateSeries` | `FundingLine` | `PerformanceMeasurementBaseline` | **moved, still wrong** |
| `how fast are we spending` | `FundingLine` | `PerformanceMeasurementBaseline` | `PerformanceMeasurementBaseline` | **now correct, and NOT predicted** |

**`how fast are we spending` never grounded to a response shape**, so the exclusion was not about
it — yet removing six rows changed its neighbourhood enough to move it onto the right class.
**The exclusion has second-order effects on rows it was not about.** Recorded as an observation,
not a benefit: the same mechanism could as easily have moved a correct row off.

*Discarded, my error:* `are we getting more efficient` appeared to move. It did not — the corpus
stores the before-winner as a full `http://…` IRI and my harness split it on the first `:`, so
"before" printed as `//purl.obolibrary.org/…`. Same class either way. **Four moves, not five.**

## Totals — reported for continuity, NOT interpreted

**15/20 right class, arm A.** My pre-written prediction named `15/20` as the ceiling from this fix
alone, and the integer matched.

**That match is not offered as evidence.** One draw per row, through a selection layer already
measured as non-deterministic at ≥2/20, and the standing finding is that a right-class total is
not a usable instrument at this precision. The number is here because continuity was asked for; it
should not be quoted, differenced, or used as a baseline.

## TWO FINDINGS THAT ARE MINE — both invisible at the winner level

Lane 1's claim was narrow and correct: the shape left the set, and which subject noun then wins is
grounding quality. Both of these are that, and **both are set-level facts a winner-scored run
would have missed.**

### 1. `what is our burn rate` cannot be right, because the right class is not recalled

```
set = [WBSElement, FundingLine, Program, EarnedValueTechnique]        winner = FundingLine
expected = fin:PerformanceMeasurementBaseline                          ← NOT IN THE SET
```

This is not a selection failure and no amount of re-drawing fixes it. **The recall layer never
offered the right answer**, so the winner was chosen from a set that could not contain a correct
outcome. Scored on winners this reads as "still wrong"; scored on sets it reads as **"the recall
layer has a coverage gap for this phrasing"**, which is a different repair — the class definition
or its synonyms, not the sampler.

### 2. `are we getting more efficient` escapes domain scoping entirely

```
domains=["PROGRAM_FINANCE"]   →   122 candidates,  ZERO of them fin:
winner: http://purl.obolibrary.org/obo/BFO_0000144
sample: mil#DitaNode, mil#DescriptiveDataModule, MaintenanceReferenceOntology/Diagram
```

**`pool[PROGRAM_FINANCE] = 8` does not describe what `/resolve` returned for this row.** 122
candidates from unrelated ontologies came back under an explicit single-domain scope. Other rows
in the same run returned 1–8 candidates and were correctly `fin:`-only, so the scoping works on
19 of 20 and is bypassed on one.

This did not affect the primary claim — a set with no `fin:` classes trivially contains no `fin:`
response shapes — and the row was equally wrong before the delete, so **it is pre-existing and not
caused by it.** But it means the pool figure is a statement about the scoped path, not about every
path `/resolve` can take.

### RESOLVED 2026-09-02 by the lane that owns `/resolve` — and it was neither of my hypotheses

I left this as "a threshold fallback that widens, or scoping not applied on one branch — not
determined here." **It is the second, in a form neither guess named:** the cold-start fallback
(`_SPARQL_MAINTENANCE_CLASSES`, `agent_fleet/ontology_service/main.py:411`) selects every
labelled `owl:Class` with **no domain filter in the query at all**. So the requested domain scopes
the hybrid path and is *discarded* by the fallback path.

**Scoping is not bypassed — the fallback never had it.** And the namespace breakdown of those 122
candidates is the tell I did not recognise: IOF 104, mil 10, MaintenanceReferenceOntology 7, obo 1
— the maintenance ontology, which is the **cold-start signature**, on a cluster whose Weaviate is
fully populated. The fallback fires per QUERY when hybrid search returns nothing for that query,
not per deployment.

**And it is the same mechanism that broke d4**, where it fired for every query because Weaviate
was empty for the domain — so every planning question was answered from the maintenance ontology
at plausible confidence. Same code path, same silent substitution, different trigger: d4 made a
design property continuous and it was read as an environment problem. Here it is one row in
twenty on a healthy cluster.

*Not my finding and not my fix — recorded here so this packet does not leave a resolved question
standing open. `[[a-degradation-must-name-itself]]` again: an answer from the wrong ontology at a
plausible confidence is a substitution that announces nothing.*

## What is NOT claimed

* No rate, no budget, no n-of-20 score to be differenced later.
* No claim that the exclusion improved grounding. It removed six classes from the sets, which is
  what it said it would do. Two rows landing correct is downstream of that and is reported per
  row, not aggregated into a benefit.
* Nothing about arm C, which is Lane 1's canary and theirs to read.

## Owed

* The recall gap on `what is our burn rate` — `fin:PerformanceMeasurementBaseline` needs to be
  reachable from that phrasing, and that is a definition/synonym question in this engine.
* The scoping escape on `are we getting more efficient` — belongs to whoever owns `/resolve`,
  filed here with the evidence rather than diagnosed.
* The three-value determinism run (grounded subject, set, winner) the escalation already queued.
