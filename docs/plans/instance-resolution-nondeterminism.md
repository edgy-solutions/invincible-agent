---
id:         instance-resolution-nondeterminism
status:     open
owner:      agent
blocked-on: nothing — the read is DONE but its HEADLINE IS RETRACTED (within-run only; see the 2026-08-17 correction). ANNOUNCEMENT TO AGENT B, per the shared-surface rule in AGENTS.md: the fix's extraction half will change `ClassifyDomainIntent`'s prompt — the one call that emits BOTH class and identifier — so hold any in-flight class-selection read before it lands. The two halves (qualifier-stripping in matching, identifier-vs-content-word discrimination in extraction) MUST land together: the strict half alone widens the aperture that already admits a content word and makes the two stable false positives MORE reachable.
closed-by:
code-site:  agent_fleet/ontology_service/main.py:1584
repo:       invincible-agent
summary:    RETRACTED 2026-08-17 — the 'no nondeterminism' headline was WITHIN-RUN only. The same query gives opposite answers BETWEEN runs on an unchanged pod, because a 0.006 shift in one candidate score flips both the class and the extracted identifier (temperature-0 is deterministic per PROMPT, and the prompt carries the candidates). MEASURED 2026-08-15, 290 probes, 0 errors, 0 of 29 phrasings mixed WITHIN that run and the trailing-class-noun lead is refuted (bare 67% = trailing 67%). The real defect is the SHAPE of the extracted identifier: the matcher rejects qualified names it owns (`publog.p_cage`, `publog p_cage`) and accepts content words it does not (`cage` -> `p_cage`, so a nonexistent asset returns a confident answer about a real one). Too strict and too loose, same missing idea. Title retained as an id only; see the body.
---

# One query, two groundings

> ## THE SPINE — read this before anything below
>
> **The matcher is too strict on qualified names and too loose on content words, and both halves
> are one missing idea: nothing distinguishes *"this token IS an identifier"* from *"this token
> appears near one."***
>
> Measured 2026-08-15, 290 probes, 0 errors. Everything else in this packet is either evidence
> for that sentence or a hypothesis it replaced.

## ⛔ CORRECTION 2026-08-17 — THE HEADLINE WAS SCOPED TO WITHIN-RUN. BETWEEN RUNS IT MOVES.

**Retracting this packet's own headline before anyone builds against it.** *"290 probes, 0 mixed
outcomes, no nondeterminism"* is true **within a single run** and false across runs.

Six serial probes of `misspell-01`'s exact query, run later against the same deployment:

    ident='p_caeg'  match=empty  ->  6/6 CORRECT ABSTENTION

The 290-probe corpus run recorded that identical row as `ident='cage'`, **resolved 10/10** to
`publog/p_cage`. Same query text, same endpoint, same payload, **same pod — `restarts=0`, no
redeploy between them.**

### The mechanism: a 0.006 score change flips both the class AND the identifier

    corpus run   candidates: Table 0.232  Column 0.208  ->  ident 'cage'    class Table
    now          candidates: Table 0.232  Column 0.214  ->  ident 'p_caeg'  class Column

`Table`'s score is byte-identical. **`Column`'s moved by 0.006, and that was enough to change
which class won and what the extractor emitted.** `ClassifyDomainIntent` is pinned at
`temperature 0`, so the LLM is greedy and deterministic *for a given prompt* — the prompt carries
the candidate list, so **when recall shifts, the prompt shifts, and a temperature-0 call
faithfully produces a different answer.** Determinism in the model is not determinism in the
system.

### What this does to the measurement

**A within-run stability measure cannot see between-run drift**, and this packet reported the
former as the latter. The corpus interleaves repeats (`for run: for row:`), so 10 repeats of one
phrasing span the whole run — good design, and still blind to a substrate that moves *between*
runs. The scope was "one run against one substrate snapshot"; the claim was "the system is
deterministic". That gap is [[a-green-check-proves-only-its-scope]] again, in this packet's own
headline.

**The corrected finding is worse than the original**, not better: the resolver is not stably
right and not stably wrong. It sits on a **knife-edge decision boundary** where a hundredth of a
similarity point flips a nonexistent asset between *honest abstention* and *confident wrong
answer about a real one*. Both of this packet's stable-looking results were real; neither was the
system's behaviour.

### Consequences

* **The false-positive pair is not "10/10 stable".** It is *10/10 under one embedding snapshot*.
  As of this read `misspell-01` abstains correctly — and nothing was fixed to make that true.
* **A THIRD stamp axis reading is required per run, not per session.** The substrate moved
  between two runs on the same day with no deploy and no definition commit between them
  (`a0fb983` added a test file only). The pool *fingerprint* is not enough; the candidate
  *scores* are the thing that moves.
* **Any before/after comparison of a fix must re-baseline immediately before**, because a
  baseline taken hours earlier describes a different substrate. This is the ADR-0035 lesson
  arriving in the measurement layer: distance from truth is what varies, and here the distance
  is time.

## RESOLVED 2026-08-17 — THE PROMPT'S SAFETY NET IS THE COMPONENT THAT DOESN'T CATCH IT

**B's `fec6739` acknowledged the shared-call announcement and handed over the upstream half; this
section is the other half of the same contradiction, and together they settle the fix's shape.**

`contracts.baml`'s `instance_identifier` contract says two things that the matcher makes
incompatible:

    "a catalog asset path like gold.sales.revenue_summary … copy that exact token here verbatim"

    "Be RECALL-BIASED on Job B: when in doubt about whether something is a name vs. a
     description, extract it. A miss costs more than a spurious extraction — THE ROUTER CAN
     VERIFY WITH THE PHONE BOOK, but it cannot recover from an extraction the model never made."

**Both instructions are reasonable. Both are falsified by the matcher.**

| the prompt says | the matcher does |
|---|---|
| emit qualified dotted paths **verbatim** (`gold.sales.revenue_summary`) | **rejects** `publog.p_cage` |
| over-extract freely, **the phone book will verify** | fuzzy-matches `cage` → `p_cage`, so it **launders instead of verifying** |

> **The prompt's premise — *a spurious extraction is cheap because the phone book verifies* — is
> FALSE given what the phone book actually does.** That single sentence explains both the 42%
> miss rate and the false positives. They are not two defects with a shared cause; they are one
> broken contract read from its two ends.

### Which end gives — and it is not the one this packet assumed

This packet planned "qualifier-stripping in the matcher" plus "discrimination in the prompt".
**The prompt's reasoning is sound *if* the phone book verifies**, so the honest repair is to make
that true rather than to retract the recall bias:

1. **Normalize qualified identifiers** — `publog.p_cage`, `publog p_cage`, `publog's p_cage` all
   carry the name plus a qualifier. Match on the name segment; use the qualifier as
   **corroboration**, not as an obstacle. *Looser exactly where it was wrongly strict.*
2. **Require specificity, so a content word cannot win** — `cage` matching `p_cage` is a
   substring accident. The phone book must be able to say *"this token does not identify an
   asset"* and return nothing. *Stricter exactly where it was wrongly loose.*

**Together those make the prompt's promise true**, at which point recall bias is safe as
designed and the prompt may need no change at all beyond removing the dotted example if (1)
lands differently than expected. That inverts this packet's earlier plan: **most of the fix is
the matcher, and the prompt half shrinks to almost nothing.**

### The landing, unchanged in shape

Still three parts, still coordinated — A's matcher normalization + specificity gate, whatever
residue the prompt needs, and B's cleaned `mesh#InstanceIdentifier` definition. B records that
its `rdfs:comment` is a **near-verbatim duplicate of the BAML field description**, and that the
BAML copy is the one driving extraction: cleaning the TTL alone would leave two masters
divergent with the ineffective one cleaned.

**And B's own qualification is the reason the coordination is real:** B touches no prompt
template, but the candidate classes are injected via TypeBuilder and *their descriptions are the
definitions B rewrites*. Nothing in flight on the file; the content moves anyway.

## ⛔ THE TWO HALVES LAND TOGETHER — fixing the qualifier alone makes this WORSE

**Stated before either half is built, because the qualifier fix is the tempting one.** Seven of
the nine failures name the asset correctly and are rejected, so qualifier-stripping reads as pure
upside: more queries resolve, nothing appears to be given up.

It is not upside on its own. **The false positives are caused by excess matcher tolerance, and
qualifier-stripping adds tolerance.** Strip `publog` from `publog p_cage` and you get a match —
and the identical loosening makes `cage` reach `p_cage` more readily, not less. You would be
widening the aperture that already admits a content word while doing nothing about the missing
discriminator.

**So: no qualifier fix ships without the identifier/content-word discrimination.** Shipping the
strict half alone converts a visible miss rate into more of the one output class this
architecture exists to prevent.

## THE FALSE POSITIVES ARE THE FINDING — worse than the 42% miss rate

**Read with the 2026-08-17 correction above: "10/10 stable" means stable UNDER ONE EMBEDDING
SNAPSHOT.** As of that later read `misspell-01` abstains correctly 6/6, with nothing fixed. The
defect is not that it always does this — it is that a hundredth of a similarity point decides
which of these two behaviours you get.

Two rows, 10/10 under the 2026-08-15 snapshot, both resolving to a real asset **nobody named**:

    "…give me a couple cage values from publog's p_caeg"   <- p_caeg DOES NOT EXIST
        extracted `cage` (from the words "cage values")  ->  urn:…publog/p_cage

    "give me a couple values from cage"
        extracted `cage`                                 ->  urn:…publog/p_cage

**That is not a grounding failure. It is a confident, stable, wrong answer about a different real
asset** — the output class the abstention gate, the provenance tiers, and the honest-degradation
rule all exist to make impossible. A miss is visible and recoverable; this is neither.

And it is the *demo's* shape exactly: `misspell-01` is a name that looks right and is not, which
is what [docs/demo-script.md](../demo-script.md) §2 row 5 exists to demonstrate the system
refusing. See the hard block in [docs/demo-day-runbook.md](../demo-day-runbook.md) §A5.


**This is the complaint that matters, stated first.** Asking the same question over and over
and getting a different answer each time is not a rough edge — it is the property that makes
every other issue unfalsifiable. A user cannot tell a fixed system from a broken one, cannot
tell their own phrasing from the system's variance, and cannot report a bug reproducibly. Any
"is it working now?" is answered by a coin flip.

## Three runs, three outcomes, THREE DIFFERENT CAUSES

The variance is not one flaky thing, which is exactly why it read as chaos:

| run | what happened | cause |
|---|---|---|
| 2026-08-14 20:12 | blank card, no answer at all | DA OOM-killed → [[da-collects-before-filtering]]; a crashed subtask skips the UI payload |
| 2026-08-15 01:16 | a confident apology | did not ground — **this packet** |
| 2026-08-15 01:16 | `['00000','00001']` | worked |

Each cause is separately filed. This packet owns the middle row only. Recording the split
because a user experiencing all three sees one symptom — "it gives me a different answer every
time" — and would otherwise chase one fix for three defects.

**Witnessed at work 2026-08-15**, and the evidence is specifically the two 01:16 runs — NOT
the 20:12 one, which was the OOM and is accounted for elsewhere. Two runs, identical query
text — *"give me a couple cage values from publog's p_cage dataset"* — same deployment,
minutes apart:

| run | prompt block DA received | outcome |
|---|---|---|
| A | `### Resolved DataHub URN` + the correct s3 URN | queried MinIO, returned `['00000','00001']` |
| B | `### No DataHub URN resolved` | apologised; **this is the one the UI rendered** |

This is NOT the phrasing effect seen a day earlier, where adding the word "table" tipped the
resolver toward a class reading. Same string, two answers.

## Where the nondeterminism can live

Instance resolution has two entry points and both are LLM-mediated:

- `ontology_service/main.py:1584` — `if not candidates and request.entity_refs:` — the
  preemption path, which fires only when class recall is EMPTY. Whether recall is empty is a
  Weaviate hybrid-search outcome near a threshold.
- `main.py:1638-1640` — the post-class-recall path, which requires `ClassifyDomainIntent` to
  emit an `instance_identifier`. That is an LLM extraction, and it is the likelier source: a
  model that names `p_cage` on one call and not the next produces exactly this split.

`entity_refs` themselves come from `/route_intent`'s BAML `ExtractIntent`, so there are
several sampled steps between the query and a URN. Any one of them is enough.

## Why it matters more than a flaky test would

The failure is invisible: run B produced no error, and — see
[[ui-renders-honest-failure-as-answer]] — reported `status: "success"`. So the user's
experience of a working system is a coin flip, and the losing side is articulate about why it
cannot help. A user who sees B first concludes the asset is not in the catalog.

## MEASURED 2026-08-15 ON SANDBOX — IT DID NOT REPRODUCE, AND TWO CLAIMS HERE WERE WRONG

First live run. 6 phrasings × 5 repeats, concurrent, against sandbox Engine O:

```
phrasing     grounded  class    argmax   recall(win/top)
bare           5/5     Column   Column   0.26/0.26
bare2          5/5     Table    Table    0.23/0.23
dataset        2/2     Table    Table    0.65/0.65
dataset2       5/5     Table    Table    0.91/0.91
table          5/5     Table    Table    0.74/0.74
table2         5/5     Table    Table    0.97/0.97

BARE grounded 10/10   ·   SUFFIXED grounded 17/17   ·   unstable phrasings: NONE
```

**27/27 grounded. Zero instability. Zero precision override** — winner recall equals top
recall in every case, so the LLM picked argmax every time. The trailing-noun effect and the
nondeterminism are both ABSENT on sandbox.

**Correction 1 — the pool precondition was based on a stale document.** This packet said
sandbox could not reproduce the defect because four classes were hand-deleted. A live read
says the pool has all six (`Column, Dashboard, Dataset, Job, Pipeline, Table`). The STEP0
status line ("only idp:Dataset and idp:Dashboard", 2026-06-11) is two months old and no
longer true — the pool was restored at some point. **The restoration described above is
already done.** I asserted a precondition from a document instead of a read, and built a hard
gate around it.

**Correction 2 — the gate guarded the wrong axis.** `--require-pool` passed, correctly, and
caught nothing, because the divergence is in the CODE. Sandbox Engine O runs
`ontology-service:latest`, last restarted **2026-08-10** — five days and several redeploys
behind work. A `:latest` tag makes the version unfalsifiable from outside, and `/health`
returns `{status, jena_reachable}` with no build identity, so **a corpus result against it is
unattributable**. That is the very "measuring a different system" failure the pool gate exists
to prevent, arriving through the door the gate does not watch.

So the read is NOT done — it is *pending a rig that resembles work*. Sandbox needs the
redeploy the operator has already identified: new charts, containers, doc-tools, dag-tools,
pub-tools. Until then a green corpus run on sandbox says nothing about work.

### THAT BLOCKER IS CLEARED — read 2026-08-15, and the stale fact was the restart date

The check named above (Engine O's image identity and restart time) was run:

```
POD         sandbox/iagent-engine-o-5d688646fb-5dwqm
START       2026-08-15T04:18:07Z          <- ~12h ago, NOT 2026-08-10
IMAGE       …/ontology-service:latest
IMAGE_ID    …/ontology-service@sha256:fe90b0472e0a4c2360e7a983940e1df070a8b77548876b9dd3d04b292afa27dd
PULLPOLICY  Always
```

**The "last restarted 2026-08-10, five days and several redeploys behind work" claim above is
stale.** Engine O restarted at 04:18Z on 2026-08-15 — *after* the chart 0.3.37 upgrade recorded
in `5f3b4e1` (committed 00:28Z) — and with `pullPolicy: Always`, so the restart pulled fresh.
**The corpus read is runnable today.**

**And the digest is part of what the packet said was missing.** The objection was not really the
`:latest` tag; it was that `/health` returns `{status, jena_reachable}` with no build identity,
so *"a corpus result against it is unattributable"*. `imageID` supplies a falsifiable code
identity — and it is **half** of attribution.

### RULE — THREE AXES, OR THE NUMBER IS NOT ATTRIBUTABLE

**Amended 2026-08-15 (second time, same day): there is a THIRD axis, and it is the one that
silently voided every grounding number this packet had.**

    CODE       image digest (imageID)       -> which build is answering
    SUBSTRATE  pool fingerprint (stamp())   -> what classes it can choose from
    INSTANCES  catalog contents             -> whether ANYTHING could have grounded

`iagent-minio/publog-lake/publog/p_cage` and its upstream `_raw/cage` had **never been
materialized on sandbox** — defined by pub-tools, never built here — so DataHub had no such
dataset and *every* probe returned `instance_match: empty` regardless of phrasing. A grounding
rate measured against that catalog is not a low rate; it is **no measurement at all**, and it
reads as a clean run because the pool gate passes and the health check is green.

**This retroactively voids every sandbox grounding number taken before 2026-08-15T17:45Z**,
including this packet's own earlier runs and that morning's smoke run. They describe a system
that could not have grounded whatever the resolver did.

The original two-axis form of this rule follows; it stands, it was simply one axis short.

### AN IMAGE DIGEST PINS THE CODE, NOT THE SUBSTRATE. BOTH AXES OR NEITHER.

Stated as a rule rather than a note because the next person will reach for the digest alone,
and there is now a concrete demonstration that it is insufficient. Within hours of the digest
read above, `2f617fd` rewrote the `idp:Column` and `idp:Pipeline` definitions in
`setup/ontologies/idp_extension.ttl`, re-ingested them, and **measurably moved which class wins
a contest — with the image digest unchanged.**

    CODE axis        image digest (imageID)          -> which build is answering
    SUBSTRATE axis   pool fingerprint (stamp())      -> what it is answering FROM

**A corpus result is attributable only when BOTH are recorded.** They move independently: a
redeploy changes the digest and not the definitions; a re-ingest changes the definitions and not
the digest. A run stamped with only one of them is pinned against a system that could have
changed along the other axis without leaving a trace in the stamp — which is the same
*"measuring a different system"* failure the pool gate was built to prevent, arriving through
the axis the gate does not watch.

This is why `stamp()` records the pool fingerprint AND `/health` rather than either alone. The
digest is the missing third field, not a replacement for the first.

**What this does NOT establish, stated so the gate is not declared closed twice:** the digest
proves *what sandbox is running*, not that it *equals work's build*. Cross-cluster equality
needs work's digest read on the work cluster, which is a human action there. So "a rig that
resembles work" is answered in the direction that was actually blocking — sandbox is current
rather than five days stale — and the equality claim remains unmade.

**What shipped in response:** `stamp()` in the runner records the pool fingerprint, `/health`,
and a mandatory-by-convention `--stamp` free-text note naming what was measured. A result
that cannot say what it ran against is not evidence, and this run proved that the hard way.

## ~~STRONG LEAD~~ — **DEAD, refuted on numbers 2026-08-15. Do not re-chase.**

**bare-identifier 20/30 (67%) · trailing-class-noun 40/60 (67%). Identical.** The trailing class
noun has no effect on grounding. Kept below only so the reasoning is legible and nobody
re-derives it from the same observation — it was a good hypothesis from a small sample, and the
sample was drawn from a catalog that contained no `p_cage` at all.

<details>
<summary>the original lead, retained for the record</summary>

## STRONG LEAD (2026-08-15): it may be a deterministic misparse, not noise

Every failing query ended with a trailing class noun — "p_cage **dataset**", "p_cage
**table**". The one that grounded and returned rows was bare: "publog's **p_cage**".

And there is a mechanism that would explain it exactly. `ClassifyDomainIntent` emits the class
AND the `instance_identifier` in ONE call, and instance resolution only runs when the
identifier is present (`main.py:1638-1639`). A trailing class noun tips that single decision
toward "this is a question about a KIND of thing", which simultaneously selects the
specific-sounding class (Table over Dataset, 0.477 over 1.0) and emits no identifier. Both
observed symptoms, one cause.

If that holds, this packet is MIS-TITLED — it is not nondeterminism, it is a deterministic
misparse with a nameable trigger, and the repair is upstream of selection entirely. See
[[deterministic-decisions-made-by-llm]] for the gates involved.

**Do not design the fix before this read.** Ten runs of each phrasing, compare grounding
rates. If the bare form grounds ~10/10 and the "dataset" form ~0/10, it is deterministic and
the word is the trigger. If both are ~50%, it is genuinely sampling noise and this title
stands. Either way the cheapest hypothesis is settled first.

</details>

## The rig — built 2026-08-15, and its precondition is a hand-deletion

`tests/routing/resolver_corpus.yaml` (29 phrasings, 9 axes, seeded with the real work
queries) and `scripts/run_resolver_corpus.py --base-url … --repeat N`. Six columns per run,
because a corpus recording only the chosen class would have missed the defect it exists for:
resolved class · the instance identifier the SAME call emitted · candidate scores · whether
`_resolve_instance` was reached · the argmax counterfactual · `fallback_reason`. `--diff a
b` compares two deployments.

**IT REFUSES TO RUN AGAINST THE WRONG POOL, and that gate is the point.** `idp:Table`,
`Column`, `Pipeline` and `Job` were hand-deleted from sandbox's Weaviate on 2026-06-11
(`STEP0_IDP_BUILD_SPEC.md:172`) and work has them. Against a two-class pool every row
resolves to Dataset unopposed, the trailing-noun effect CANNOT appear because the noun's
target is not a candidate, and the run reports a healthy picker while measuring a different
system. A simulated diff of the two pools shows the trailing-noun rows grounding 100% in the
small pool and 0% in the full one — the corpus certifying the opposite of the truth. That
number would be worse than no number, so the check is a hard gate.

**The session's first finding is the blocker on its last one.** Four classes removed by hand,
never folded into a reproducible path — which is why work got them back and sandbox did not —
and the un-reproduced deletion is now the ceiling on the only measurement that settles this.
[[bootstrap-state-debt]] arriving not as inconvenience but as the measurement's validity.

### WHO OWNS WEAVIATE'S CLASS COLLECTION — read 2026-08-15, by evidence

Nothing had ever written this down, which is exactly why a hand-deletion survived two months
undetected: an unowned collection has nobody to notice it drifted.

| collection | owner | evidence |
|---|---|---|
| `Predicate` | **mesh-registrar** | work's registrar log — 404 then `POST /v1/schema` as first writer; `v2_substrate._ensure_predicate_collection` |
| `OntologyClass` | **doc-tools ontology ingest** | `doc_tools/assets/ontology_assets.py:64` `sync_ontology_to_weaviate`, called at :411 from the ingest asset; creates the collection at :94-97 |

Not the registrar. **Not the seeder** — which matters, because the seeder is the component
that manufactured `DispositionReview` as a side effect ([[seeder-manufactures-declarations]]),
and teaching it four more special cases would have been the wrong repair on a component with
a record for exactly this.

### AND THE RESTORATION NEEDS NO CODE

The write is an **"Idempotent Upsert"** (`ontology_assets.py:113`) and `idp_extension.ttl`
declares all six classes. So the canonical pipeline ALREADY produces the correct pool — which
is precisely why work's fresh bootstrap has all six and nobody had to intervene. Sandbox is
missing them because **nobody re-ingested the idp partition since the hand-delete**, not
because the reproducible path is absent.

    Restoration = trigger the ontology ingest for the idp_extension partition.

**THE TRIGGER PATH, read before running** (because a green job that primed the wrong slice
is the failure mode this session has hit repeatedly):

    python setup/prime_databases.py --upload-only --trigger-ingest

`trigger_ingest_jobs()` iterates the FULL `CANONICAL_TTL_MANIFEST`, which contains the
`idp_extension` entry, so the idp partition IS covered — partition key
`s3_key.replace("/", "__")` = **`idp__idp_extension.ttl`**. `--upload-only` skips the Neo4j /
Jena priming and the wipe, so this is the least invasive form that still runs the canonical
path. Expect ~13 partitions serially at 30-60s each (roughly 7-13 minutes).

`clear_ontology_graphs()` runs first and drops **Jena domain graphs only** — never Weaviate.
It is an append-idempotency guard (doc-tools POSTs rather than PUTs, so a re-prime would
otherwise double blank-node structures), and it drops only graphs the manifest can reproduce.
Weaviate is untouched by it; the class rows arrive via the idempotent upsert.

A single-partition launch from the Dagster UI works too and is faster, but skips
`clear_ontology_graphs()`, so the idp TTL re-appends into the DATA_ENGINEERING Jena graph.
Harmless for the Weaviate pool this restoration targets; noted so the choice is informed.

Work's fresh bootstrap is the existence proof; sandbox uses the same mechanism rather than a
special case. That satisfies both riders below by construction: it IS the reproducible path,
and there is no hand-POST anywhere in it.

**Acceptance is the corpus's own gate going green** — six classes in the pool,
`--require-pool` passing, no hand-POST in the path. The gate built to protect the measurement
becomes the restoration's definition of done.

**And why that gate checks CONTENTS rather than existence:** Engine O creates the
`OntologyClass` collection if it is absent (`ontology_service/main.py:894`), so
empty-but-existing is a reachable state that reads healthy to anything testing existence.
`--require-pool` asks what candidates actually come back, which is the only check that
distinguishes a populated pool from a collection that merely exists. That was designed before
this detail was known and is justified by it after the fact.

Two rules for the restoration, both easy to violate:

1. **It goes through the reproducible path**, not a hand-POST mirroring the hand-DELETE.
   Putting them back by hand fixes the pool and preserves the debt. Whatever seeds the
   Weaviate class collection is where it lands, so the next fresh sandbox gets all six
   without anyone remembering.
2. **The pool matches work until the SPO ruling lands.** With the classes restored, sandbox
   will start resolving to `idp:Table` and refusing Dataset-typed verbs — the intercept that
   motivated the original deletion. **That is the defect becoming reproducible, which is the
   entire point.** The pressure to re-delete will be real the first time a demo query fails
   on it. Anyone who wants sandbox green again gets it by fixing SELECTION, not by shrinking
   the candidate set.

## RE-SCOPED 2026-08-15 after `2f617fd` — the read survives, its baseline does not, and one half of the STRONG LEAD is now answered

**Read the resolver arc's latest commit before running this.** `2f617fd` rewrote the `idp:Column`
and `idp:Pipeline` definitions and re-ingested them, which moves the measurement's substrate.
Running the read as originally written would produce a number answering a question that had
stopped being the question.

### What changed, and why it does NOT close this packet

`2f617fd` fixed a **recall** defect: Weaviate embeds `"<label> — <definition>"`, and `idp:Column`'s
definition contained quoted user *questions* plus a dotted identifier (`orders.amount`), so any
question — and any dotted asset name like `publog.p_cage` — scored similar to it. `idp:Pipeline`
named `Datasets` twice and stole its sibling's traffic.

**That is the CANDIDATE-RANKING mechanism. This packet's defect is the IDENTIFIER-EMISSION
mechanism**, and they are different code paths:

    recall               Weaviate similarity over definitions   -> which candidates are offered
    identifier emission  ClassifyDomainIntent (main.py:1638)    -> whether _resolve_instance runs

A run that reports *"No DataHub URN resolved"* failed at the second, whatever the first ranked.
`2f617fd` measured **class agreement** (argmax vs LLM), never **grounding rate**, so nothing it
reports bears directly on *"the same question returns rows once and an apology the next time."*

### The half of the STRONG LEAD that IS now answered — and it sharpens the read

The lead proposed ONE cause for TWO symptoms: a trailing class noun tips `ClassifyDomainIntent`
toward *"a KIND of thing"*, which **both** selects the specific-sounding class **and** emits no
identifier.

The class-selection symptom now has a demonstrated cause of its own — definition wording, in a
different layer, fixed independently. **So the two symptoms have come apart**, and that is
informative rather than disappointing:

> **If the trailing-noun grounding effect survives `2f617fd`, its cause is NOT the class
> contest** — the class contest has been repaired at the recall layer — **and the hypothesis
> narrows to identifier emission alone.** If it disappears, the two symptoms shared the recall
> cause after all and this packet is largely closed by someone else's commit.

Either outcome is worth the run, which it was not before: the old read could not distinguish
these, because both mechanisms moved together.

### The re-scoped read

1. **Grounding rate, not class agreement.** Ten runs each of the bare form (`publog's p_cage`)
   and the trailing-noun form (`p_cage dataset`), counting `instance_resolved` true/false. This
   is unchanged from the original specification and remains the discriminating measurement.
2. **Stamp BOTH axes.** Image digest AND pool fingerprint — see the rule above. Any number from
   before `2f617fd` is not comparable to one after it, and only the stamp records which side of
   that line a run sits on.
3. **Add the abstention row.** `misspell-01` (`p_caeg`, an asset that does not exist) regressed
   from UNKNOWN to a stable `Column` resolution. It belongs in this read because it is the same
   question — *does the resolver know when to decline* — and because it is
   [demo-script](../demo-script.md) §2 row 5, the failure demo. Filed as a first-viewer risk in
   [[first-viewer-critical-path]] and [docs/demo-day-runbook.md](../demo-day-runbook.md) §A5.
4. **Do not let the resolver arc change definitions while this is in flight** — the ownership
   rule now recorded in `AGENTS.md`. This measurement is the one thing that arc can invalidate
   without touching a file this packet owns.

## PROBED 2026-08-15 AFTER MATERIALIZATION — THE LEAD IS REFUTED, AND ITS DIRECTION IS BACKWARDS

**n=1 per phrasing. This is an anecdote, not a rate** — the repeat=10 run is what turns it into
one, and nothing should be fixed until it lands. Recorded now because the mechanism is legible
and it changes what the fix would even be.

Two probes, same asset, same deployment, minutes apart, against a catalog that now contains
`p_cage`:

| query | extracted `instance_identifier` | `instance_match` | resolved |
|---|---|---|---|
| `…from publog p_cage` | **`'publog p_cage'`** | `empty` | **NO** |
| `…from publog's p_cage dataset` | **`'p_cage'`** | `fuzzy` | **YES** → correct URN |

**Both resolved to class `Table`. The class contest is not involved.**

### The cause is IDENTIFIER EXTRACTION, and it is deterministic

`ClassifyDomainIntent` extracts `"publog p_cage"` — **schema qualifier included** — from the
bare space-separated form, and that string does not fuzzy-match a URN whose name segment is
`publog/p_cage`. The possessive form yields a clean `"p_cage"`, which matches. Same call, same
asset; the difference is the *content* of the emitted identifier, not whether one was emitted.

### This inverts the STRONG LEAD twice

The lead predicted: *a trailing class noun suppresses identifier emission, so the bare form
grounds and the trailing-noun form does not.* Observed:

1. **An identifier is emitted in both cases** — `instance_fired` was true throughout. Emission
   is not the failure.
2. **The trailing-noun form is the one that RESOLVED.** The bare form failed.

So the hypothesis is not merely unconfirmed; **its direction is backwards.**

### Which means this packet is MIS-TITLED, as it suspected

It is not nondeterminism. It is a **deterministic extraction defect with a nameable trigger** —
*the extracted identifier retains a qualifier the matcher cannot handle.* That is a far smaller
and more fixable target than "instance resolution is nondeterministic", and it sits squarely in
the extraction/matching layer.

**Rename deferred until the rate lands**, because the honest title depends on what the repeat=10
shows: if some phrasings are also *unstable* across repeats, both defects are real and the title
needs to say so rather than trade one wrong name for another.

## THE READ, RUN 2026-08-15 — 290 probes, 0 errors, **0 nondeterminism**

**In-cluster** (no port-forward), repeat=10 over 29 phrasings, scored on `instance_id != ""`.
All three stamp axes recorded: code `sha256:fe90b047`, pool fingerprint 6/6, instances
materialized 17:45Z.

    phrasings with MIXED grounding outcomes:  0 / 29
    errored probes:                           0 / 290

**Every phrasing is 10/10 or 0/10.** There is no coin flip. The user-visible complaint that
opened this packet — *"asking the same question repeatedly returns different answers"* — does not
reproduce at n=10 per phrasing on a rig with the asset present.

### The STRONG LEAD is refuted on the numbers

    bare-identifier       resolved 20/30   (67%)
    trailing-class-noun   resolved 40/60   (67%)

**Identical.** The lead predicted bare-high / trailing-zero. The trailing class noun has no
effect on grounding whatsoever.

### What the defect actually is: THE SHAPE OF THE EXTRACTED IDENTIFIER

`instance_fired` was true on 260/290 probes and only 150 resolved — **110 probes emitted an
identifier that could not be matched.** Sorting by the identifier's shape makes the rule crisp:

| extracted identifier | resolves? |
|---|---|
| `p_cage`, `P_CAGE` | ✅ bare name, any case |
| `minio-svc.publog-lake/publog/p_cage` | ✅ full path |
| `publog.p_cage` | ❌ **dotted qualifier** |
| `publog p_cage` | ❌ **space-separated qualifier** (2 rows) |
| `publog's p cage` | ❌ possessive + split name |
| `publog` | ❌ schema alone — extractor took the wrong token |
| `cage_code` | ❌ a COLUMN name when the question was about its table |

**Two distinct sub-defects, and they belong to different owners:**

1. **MATCHING — a qualified name is not stripped.** `publog.p_cage` and `publog p_cage` name the
   asset correctly and unambiguously; the matcher simply cannot see past the qualifier. Seven of
   the nine failures are this.
2. **EXTRACTION — the wrong token is chosen.** `bare-join-01` yields `publog` (the schema) and
   `column-01` yields `cage_code` (a column) when the target is the table. That is
   `ClassifyDomainIntent` picking the wrong noun, not the matcher failing.

### AND THE MATCHER IS SIMULTANEOUSLY TOO LOOSE — two confirmed false positives, 10/10 stable

| row | query | extracted | resolved to |
|---|---|---|---|
| `misspell-01` | *"…cage values from publog's **p_caeg**"* (asset does not exist) | `cage` | **`publog/p_cage`** |
| `colastable-01` | *"give me a couple values from **cage**"* | `cage` | **`publog/p_cage`** |

The extractor takes `cage` from the phrase *"cage values"* — a content word, not the asset name —
and the fuzzy matcher accepts it as `p_cage`. So a question about a **nonexistent** asset returns
a confident answer about a **real, different** one. (`owner-03` is the same shape:
`customer_silver` → `customers_raw`.)

> **The matcher is too strict on qualified names and too loose on content words.** It rejects
> `publog.p_cage`, which is the asset's correct qualified name, and accepts `cage`, which is a
> word from the sentence. Both halves are the same missing idea: nothing distinguishes *"this
> token IS an asset identifier"* from *"this token appears near one."*

**Caveat, stated because it is mine:** both false positives resolve to `p_cage`, which this
session materialized at 17:45Z. **Materializing did not create the defect — it made it
observable.** Against the previously-empty catalog every probe returned `empty`, so no false
positive was reachable and this would have read as clean.

### Consequences

**This packet is MIS-TITLED and the finding is smaller and more fixable than the title claims.**
Not nondeterminism — a deterministic identifier-shape defect with two named halves.

**The `id:` stays `instance-resolution-nondeterminism`.** It is cited from other packets and from
code comments, and the citation seal exists precisely so identifiers survive renames; an id is a
handle, not a claim. The summary and title carry the corrected finding instead.

**Demo row 5 is confirmed broken at n=10.** `misspell-01` — the failure demo's exact shape, a
name that looks right and is not — resolves stably to the wrong real asset. Already flagged in
[[first-viewer-critical-path]] and runbook §A5; this run upgrades it from *reported by another
commit* to *measured here, 10/10*.

## The read that sizes it, before any fix

Run ONE query N times (20 is enough) and count grounded vs ungrounded. That converts "it is
flaky" into a rate, and the rate decides the repair:

- near-100% grounded → a rare sampling excursion; a retry-on-ungrounded may be enough
- ~50% → a genuine coin flip in one step, and the step is findable by logging which entry
  point fired per run
- correlated with anything (cold cache, first call after restart) → not sampling at all

Log the `preemption_path` provenance field that is already threaded
(`class_recall_empty_fallback`) so each run says WHICH path answered it. Without that the
count says there is a problem but not where.

## Note

Determinism is not obviously the right target — instance resolution is deliberately
LLM-mediated, and the abstention gate exists so it can honestly decline. The goal is that it
declines for a REASON, consistently, rather than differing run to run on identical input.
