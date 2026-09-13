---
id:         the-sixteen-master-reds-named
status:     open
owner:      invincible-agent-01
blocked-on:
closed-by:
repo:       invincible-agent
summary:    The sixteen reds that reproduce on master, each named with what it actually waits on. THE HEADLINE IS THAT NONE OF THEM IS WAITING ON A RULING. They are waiting on live graph state (7), a source defect with a named owner (1), a resolver decision from the domain-scoping arc (3), and corpus expectations against a live model (5). "Awaiting rulings" was the status nobody had checked.
---

# The sixteen master reds, named

**Measured 2026-09-12 at `77d42e5`, fleet SETTLED (40 Running, 0 terminating, 0 non-running),
and controlled against master's own copies in the same venv against the same cluster.** Each one
below reproduces on master; the three non-deterministic ones are excluded and ruled separately
under R-031.

> **THE FINDING THAT MATTERS MORE THAN THE LIST.** These were carried as *"awaiting rulings"* for
> two days. **Not one of them is waiting on a ruling.** Seven are waiting on live graph state, one
> is a source defect with a named owner, three are a decision inside the domain-scoping arc, and
> five are corpus expectations against a live model. **"Awaiting a ruling" was a status nobody had
> checked** — and it is the most expensive possible label, because it parks a red somewhere no
> engineer looks and no decision-maker knows they hold.

## The partition

| # | test | what it actually says | waits on | owner |
|---|---|---|---|---|
| 1 | `adr0019_pipeline_integrity::test_D_phantom_scan_returns_zero` | phantom `OntologyClass` nodes in the sustainment namespaces (`pcn#Component`, `product#ApprovedSourceRelationship`, `product#PartUsage`, `qualification#QualificationStatus`, …) | **graph state** | unassigned |
| 2 | `b2_format_ingest_guards::test_g1_format_ingest_never_writes_ontology_class` | **1** `OntologyClass` with no canonical provenance: `(None, 'MAINTENANCE')` | **graph state** — a node the format-ingest path wrote | unassigned |
| 3 | `b2_ingest_sandboxrtx::test_pool_hold_kind_classes_have_no_verbs_yet` | four `mil:*` content-kind classes carry verb edges before B4 ships | **graph state + B0 §3** | unassigned |
| 4 | `b3a_ingest_helmet_40051::test_pool_hold_kind_classes_have_no_verbs_yet` | same four | **same** | unassigned |
| 5 | `v02_cutover_diff::test_every_aitool_edge_has_required_properties` | four `mesh:` verbs with `<no-tool_urn>`, missing `tool_urn` and `provider` | **graph state** | unassigned |
| 6 | `definitions_are_retrieval_input::test_no_new_sibling_name_bleed_in_definitions` | `safety_extension.ttl :: Orphaned Hazard Set -> names ['Hazard']` | **a SOURCE fix** | **`invincible-agent-28`** |
| 7–9 | `resolve_instance_probes` ×3 (`engine_e` Equipment ×2, WorkInstruction) | `instance_resolved=False`, `instance_match='not_specific'`, `instance_n=1`, `instance_rejected_n=1` | **a resolver decision** | **`invincible-agent-01`** |
| 10–15 | `classify_route::test_routing_decision` ×6 | routing expectations vs what the live router answers | **corpus decisions** | see below |
| 16 | `cost/test_the_refusal_carries_its_options::…[package_export]` | a verb 500s on a param it does not declare | **cost engine** | **`invincible-agent-81`** |

## Five of these are one defect, and it is graph state rather than code

**Rows 1–5 are all the same shape: the cluster's graph holds nodes and edges that the seals say
should not be there.** None of them is a code defect and none needs a decision — they need the
graph to be what the pipeline says it should be. Two specifics worth carrying:

* **Row 2 is a single node**, `(None, 'MAINTENANCE')`, and its own message names the rule it
  breaks: *the format-ingest pipeline must NEVER call `MERGE (:OntologyClass {uri: …})`.* One node
  is the whole failure, so this is a data fix, not an investigation.
* **Rows 3 and 4 are the same four classes** seen from two ingest fixtures, so they are one
  finding counted twice — `mil#DescriptiveDataModule`, `mil#FaultIsolationDataModule`,
  `mil#IllustratedPartsDataModule`, `mil#ProcedureDataModule`. The message already states the
  rule (*add the verb only when a real user question demands it*), so what it needs is someone to
  say whether those four questions now exist.

**These should be re-measured after the roll that is running now**, because a prime is exactly the
operation that would change them. Recording them here as PRE-ROLL state at `77d42e5` rather than
as a standing claim — *content freshness is not write recency, and a graph read before a prime is
a reading of the old graph.*

## Row 6 has an owner and is the cleanest fix on the list

`safety_extension.ttl`'s *Orphaned Hazard Set* definition names the sibling class `Hazard` outside
a hierarchy statement. The seal's own message explains why that matters: **it is how `idp:Pipeline`
won *"list the datasets in publog"* — by naming `idp:Dataset` in its definition.** A definition is
retrieval input, so naming a sibling hands that sibling's questions to you.

**This is `invincible-agent-28`'s file and a one-line edit.** It is also the second defect found in
that TTL this week — the first was `@prefix mesh: <http://internal/mesh#>` against the real
namespace, with nine citations on an invented predicate IRI.

## Rows 7–9 are MINE, and the probable cause is my own bare-digit fix

    probe:      AFP-2024-001  ->  expected mro:Equipment via engine_e
    provenance: instance_resolved=False  instance_match='not_specific'
                instance_n=1  instance_rejected_n=1

**`engine_e` returned exactly one candidate and it was rejected.** The domain scoping is working
as designed around it — `engine_o_sustainment` had 18 candidates and was correctly demoted as
out-of-domain for `MAINTENANCE`, which is R-0's rule doing its job.

**HYPOTHESIS, STATED AS ONE BECAUSE IT IS NOT YET VERIFIED.** The bare-digit fix added a
word-overlap requirement:

    words_n = {t for t in tokens_n if not t.isdigit()}
    if not word_overlap: continue

For `AFP-2024-001` the non-digit tokens are `{afp}`. If the candidate's label shares no word with
`afp` — which is likely, since `AFP` is an abbreviation of the label rather than a word in it —
the candidate is rejected **despite its identifier matching exactly**. That would be an
identifier-match losing to a label-overlap test, which is the opposite of what the fix intended.

**This is the fourth case of the instance-override arc and it may be the same rule**: an
identifier that IS the id should not need to share a word with the label. **Do not fix it from
this hypothesis** — the resolver must be probed directly, because a justification invented
downstream fits by construction.

## Rows 10–15 are corpus decisions and half are arguably correct behaviour

Three of the six are worth reading before anyone "fixes" the router:

| query | expected | got | reading |
|---|---|---|---|
| `Tell me about gold.sales.revenue_sumary` | subject containing `Table` | `idp#Column` @ 0.97 | **the router may be right** — the query names a field, and its reasoning says so |
| `Tell me about foo.bar.zzz_nope` | verb `UNKNOWN` | `mesh:describeAsset` @ 0.65 | **a real question**: should a verb be chosen when the SUBJECT did not resolve? |
| `What feeds gold.sales.revenue_summary.amount?` | verb `UNKNOWN` | `mesh:traceLineage` @ 0.96 | `traceLineage` on a Column is not obviously wrong |

**The second row is the only one that looks like a genuine rule question**, and it is a good one:
the router picked a verb while explicitly reasoning *"even though the subject could not be
resolved."* Whether that is correct is a decision, not a defect — **and it is the only item on
this entire list that plausibly deserved the "awaiting a ruling" label.** One of sixteen.

**The corpus rows must not be rewritten from what anyone expects the router to say.** That is the
rule `invincible-agent-22` established by refusing to seal exactly this shape: *a preferred answer
written into a baseline is a guess wearing a baseline's clothes.* Each row gets decided by whoever
owns that domain, and the corpus is written from their answer.

## What this list is for

**Fifteen reds nobody is looking at is how the twenty-day CI silence started.** The value here is
not the fixes; it is that every row now has a **kind** and, where it can be derived, an **owner** —
so no row can sit under a status that means "someone else's problem" while being nobody's.

**Definition of done:** every row above either closed, or carrying an owner who has acknowledged
it. A row that can be neither is a row that should be deleted with its reason, not left open.
