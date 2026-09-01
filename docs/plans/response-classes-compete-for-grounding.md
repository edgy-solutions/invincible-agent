---
id:         response-classes-compete-for-grounding
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0019 (Contract D, both ends must exist); ADR-0025 (the can_view-filtered candidate pool)
code-site:  setup/ontologies/finance_extension.ttl (the six fin: response shapes), doc_tools/assets/ontology_assets.py (_META_ONTOLOGY_IRI_PREFIXES — the existing precedent for excluding a class kind from the pool)
summary:    MEASURED 2026-09-01 on a one-cell PROGRAM_FINANCE user. Contract D requires an OUTPUT class to exist as an OntologyClass, and every OntologyClass enters the routable GROUNDING pool — so a verb's output shape competes with its own input subject for the question that invokes it. 8 of 20 finance phrasings ground to a response class, which has NO predicate edge, so routing dies with "No predicate edge from subject_uri" while every component reports healthy. FIRST HYPOTHESIS WAS POOL WIDTH AND IT IS REFUTED: narrowing seven domains to one changes nothing (11/20 both). SECOND WAS DEFINITION LANGUAGE — the output definitions described the QUESTION ("Answers how fast money is going out") — and rewriting all six to describe answer SHAPE moved it only 11->12 with PMB 0/6->1/6. The residue is the class NAME itself: fin:BurnRateSeries is labelled "Burn Rate Series" and will always match "what is our burn rate", and a name cannot be written around. THE STRUCTURAL FIX IS EXCLUSION, NOT PROSE: response shapes should not enter the grounding pool at all, exactly as PROV-O's classes are already dropped by _META_ONTOLOGY_IRI_PREFIXES for the same reason (generic definitions vector-outcompeting domain classes). Not this lane's code. Engine P is unaffected only because its outputs are mesh:*-namespaced and its definitions describe refusals rather than asks — it grounds 3/3.
---

# A verb's output shape competes with its own subject for the question that invokes it

**Measured 2026-09-01**, on a one-cell `PROGRAM_FINANCE` user — the population that will
actually exist at work, not a power user.

## The mechanism

Contract D (ADR-0019) requires **both ends** of a verb edge to pre-exist as `owl:Class`. Every
`owl:Class` that the prime ingests becomes an `OntologyClass` node, and every `OntologyClass`
node is a candidate in `/resolve`'s grounding pool.

**So a verb's OUTPUT shape is a groundable subject.** And it is a subject **no verb serves**:

```
find_tool(subject=fin:BurnRateSeries,                verb="burn rate") -> No predicate edge
find_tool(subject=fin:PerformanceMeasurementBaseline, verb="burn rate") -> finBurnRate
```

The question grounds to the right **concept** and the wrong **end** of Contract D. Routing then
finds nothing, and nothing anywhere reports an error — `/resolve` succeeded, the class exists,
the engine is healthy, its eight verb edges are live.

## The measurement, and two hypotheses killed by it

Twenty finance phrasings, three scoping arms, `user_email=alice@example.com` throughout.

| arm | right class | any `fin:` class |
|---|---|---|
| **C** — no `domains` (defaults to `MAINTENANCE`) | 7/20 | 8/20 |
| **B** — alice's seven domains | 12/20 | 19/20 |
| **A** — one cell, `PROGRAM_FINANCE` only | **12/20** | **19/20** |

**Hypothesis 1 — POOL WIDTH — REFUTED.** A and B are identical, before and after the
definition change. Narrowing seven domains to one changes nothing, so the residual misses were
never about competing with MRO/IOF/BFO. (Arm C is the control that also corrects an earlier
error: a run passing neither `domain` nor `domains` measures **MAINTENANCE**, because
`domain: str = "MAINTENANCE"` is the model default and `domains` supersedes it only when
non-empty. That run was reported as an alice measurement and was not one.)

**Hypothesis 2 — DEFINITION LANGUAGE — TRUE BUT WEAK.** The six output definitions had been
written as descriptions of the *question*; `BurnRateSeries` literally began *"Answers how fast
money is going out and when it runs out at this rate"*, which is the sentence a user types. All
six were rewritten to describe the shape of the answer — structure, invariants, what each
refuses. Measured effect: **11 → 12 of 20**, `PerformanceMeasurementBaseline` 0/6 → 1/6.

Real, and far smaller than the diagnosis predicted.

## What the residue says: the NAME is a recall signal, and prose cannot cover it

After the rewrite, the misses are still response shapes:

| phrase | grounds to |
|---|---|
| `what is our burn rate` | `fin:BurnRateSeries` |
| `what is the funding status` | `fin:FundingStatusGrid` |
| `rank the biggest contributors to the variance` | `fin:VarianceDriverRanking` |

`fin:BurnRateSeries` carries `rdfs:label "Burn Rate Series"`. **A class named for the question
will match the question no matter what its definition says.** Renaming it is not available
either: the name is the contract's output URI, it is registered on eight live verb edges, and
it is what cortex-ui's binding rows point at.

**So prose is the wrong lever and further tuning would be corpus-fitting.** Stopping here.

## The structural fix, and it has a precedent in this repo

**Response shapes should not enter the grounding pool at all.** They are reachable through a
verb's `output_uri`; they never need to be reachable as a routing subject.

The precedent is exact: `doc_tools/assets/ontology_assets.py`'s `_META_ONTOLOGY_IRI_PREFIXES`
already drops **PROV-O's** classes from the pool, for the same class of reason —
`setup/prime_databases.py` records that W3C-quality generic definitions *"vector-outcompete
domain classes with weaker definitions"*, and that a user asking *who authorized this?* would
route to `prov:Bundle` before `AuthorizationDecision`. This is that argument applied to a
different class kind: an output shape outcompetes the subject whose verb produces it.

**Not this lane's code** — the filter lives in doc-tools. Two candidate discriminators, and
choosing between them is the ruling this packet asks for:

1. **By parent** — anything `subClassOf mesh:Response` (or `mesh:Archetype`) is excluded from
   the grounding pool. Clean, declarative, already true of every response shape in the fleet.
2. **By edge role** — exclude any class that appears only as an `output_uri` and never as an
   `input_uri`. More precise, and it self-maintains; but it needs the verb edges to exist,
   which makes it an ingest-order dependency.

## Why Engine P does not have this defect

Probed 3/3 to subject nouns. Two reasons, and only the second generalises:

* its outputs are `mesh:`-namespaced, so they read as platform shapes rather than domain nouns;
* its definitions describe **structure and refusals** — *"Refuses a payload with no periods"* —
  never the ask.

The second is why Engine F's rewrite was correct even though its measured effect was +1: it
brings finance in line with the convention Engine P already follows. **The exclusion is what
closes the gap; the rewrite is what stops it being self-inflicted.**

## What is already true

* All six `fin:` output definitions describe answer shape, committed and primed (`af81511`).
* The eight verb edges, the fourteen classes and the three archetypes are live and verified.
* `fin:Program` grounds **8/8** — the subject nouns work when nothing shadows them.
* Nothing here blocks a finance question whose subject is a Program, which is four of six verbs.
