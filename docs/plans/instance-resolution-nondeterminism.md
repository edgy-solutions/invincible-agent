---
id:         instance-resolution-nondeterminism
status:     open
owner:      agent
blocked-on: nothing — the discriminating read is a repeat-N run of one query, counting grounded vs ungrounded.
closed-by:
code-site:  agent_fleet/ontology_service/main.py:1584
repo:       invincible-agent
summary:    THE USER-FACING DEFECT — asking the same question repeatedly returns different answers. Same text, same deployment: one run grounds and returns rows, the next reports "No DataHub URN resolved". A system that is not reproducible for identical input cannot be debugged by the person using it, and cannot be trusted by anyone.
---

# One query, two groundings

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

### RULE — AN IMAGE DIGEST PINS THE CODE, NOT THE SUBSTRATE. BOTH AXES OR NEITHER.

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
