---
id:         a-sparql-failure-is-read-as-an-empty-graph
status:     open
owner:      invincible-agent-28 [5401d7] — ia-eo / lane/eo
blocked-on: the MeshOntology/MeshVectors contract — this changes what seven consumers see, and they change with it
trigger:
closed-by:
repo:       invincible-agent
summary:    engine-o's execute_sparql returns [] on any Jena failure, so five routes and two internal gates read "the substrate failed" as "the graph holds nothing". One of them is the cold-start fallback that exists to cover a Weaviate failure.
---

# A SPARQL failure is read as an empty graph

**RULED 2026-09-14** with its two siblings: *a mid-query exception returning an empty success is
forbidden everywhere ADR-0009 reaches.* The two Weaviate searches were fixed in `95725ef`. This is
the Jena one, held back for the stated reason — **it changes what every consumer sees**, so it
lands with the interface contract rather than ahead of it.

    agent_fleet/ontology_service/main.py   execute_sparql   except Exception -> return []

## The consumers, derived — seven call sites, five routes

| caller | what `[]` means to it TODAY | what it would see instead |
|---|---|---|
| `/resolve` (L2207) | **the cold-start fallback itself** — Weaviate returned nothing, so read the RDF graph. A Jena failure here empties the candidate pool with no path left | a 503 naming the substrate, instead of a subject it could not classify |
| `/classes` (L3538) | the domain has no classes | 503 |
| `/classify_legacy_table` (L2884) | nothing to classify against | 503 |
| `/resolve_instance` (L3752) | no SUSTAINMENT instances match — a first-class ABSTAIN in the resolver fan-out | 503, which the fan-out must tell apart from an abstention |
| `/instances_by_property` (L3926) | **`{parts: [], count: 0}` — "no parts are in this disposition state"** | 503 |
| `_get_active_ontology_classes` (L579) | an empty class list goes into a BAML prompt | the prompt is not built |
| `_check_jena_populated` (L603) | the store is unseeded | the startup gate says why |

**`/instances_by_property` IS THE ONE THAT REACHES A PERSON.** It is the disposition dashboard's
source — *"no dashboard store; the UI queries the same graph the policy lives in"*. A Jena blip
renders as **a confident zero on a dashboard somebody makes a decision from.** Not a missing
panel, not an error: a number, and the wrong one.

**`/resolve` IS THE ONE THAT REACHES A CONTRADICTION.** That call site is the cold-start fallback
— the thing that runs *because* Weaviate came back empty. If Jena is also failing, the route has
exhausted both substrates and still answers as though it had asked and found nothing.

## Why it is not fixed in the same commit as the Weaviate pair

The Weaviate change had one consumer shape and ADR-0009 already ruled it. This one has seven, and
two of them (`/resolve_instance`'s ABSTAIN, `_served_class_uris`' sibling degrade-open) are
protocols where an empty answer is a legitimate, load-bearing value. **A refusal that a fan-out
reads as an abstention is a worse defect than the one being fixed.**

## The shape when it lands

1. `execute_sparql` raises rather than returning `[]` — the same 503-with-cause the Weaviate pair
   now raises, so the two substrates refuse identically.
2. **Each of the seven consumers gets an explicit decision recorded here before the change**, not
   discovered after: refuse, or catch-and-abstain with the reason written down. `/resolve_instance`
   is the one to decide first, because the fan-out's contract says an empty list is an ABSTAIN.
3. The seal is behavioural, in `tests/test_predicate_hybrid_search.py`'s stub harness (the only
   one in the repo that imports `main.py`), plus the structural arm in
   `tests/test_a_substrate_failure_is_not_an_empty_result.py`, extended to name this function.
4. A control in the same breath: **an empty graph must still answer `[]`.** Collapsing "the domain
   has no classes" into "Jena is down" would turn every cold start into an outage.
