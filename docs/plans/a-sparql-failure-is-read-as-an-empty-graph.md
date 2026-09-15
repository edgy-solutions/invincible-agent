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

## RULED 2026-09-14 — PER-ROUTE, NOT BLANKET

The Weaviate pair took one refusal because they had one consumer shape. This one does not, and a
single rule applied to seven consumers would be wrong at two of them:

* **Where an empty result is a first-class ABSTAIN in a fan-out** — `/resolve_instance` — the
  return carries **three states: answered-empty, failed, unreachable**, and the CALLER decides.
  A refusal read as an abstention is worse than the defect it replaces.
* **Where an empty result is a DECISION INPUT** — `/instances_by_property`, feeding the
  disposition dashboard — a substrate failure is a **503**. A confident zero on a dashboard is the
  failure recorded where nobody reads it.
* **The cold-start fallback under `/resolve` is the double-failure case**, and it is the one that
  **must never answer "both asked, both found nothing."** Weaviate empty followed by a Jena failure
  is not a subject the mesh does not know; it is a question nobody managed to ask.

## The shape when it lands

1. `execute_sparql` stops conflating the two. The three-state result is the vehicle, not a raised
   exception at every site — see the ruling above.
2. **Each of the seven consumers gets its disposition recorded here before the change**, not
   discovered after. Three are ruled above; the remaining four (`/classes`,
   `/classify_legacy_table`, `_get_active_ontology_classes`, `_check_jena_populated`) follow the
   decision-input rule unless someone names a reason they should not.
3. The seal is behavioural, in `tests/test_predicate_hybrid_search.py`'s stub harness (the only one
   in the repo that imports `main.py`), plus the structural arm in
   `tests/test_a_substrate_failure_is_not_an_empty_result.py`, extended to name this function.
4. **THE SEAL RULE, ruled for all three packets:** *a fixture that exercises only the legitimate
   empty cannot tell the fix from the defect.* **Both empties in every fixture**, asserted to
   produce different returns. An empty graph must still answer empty — collapsing "the domain has
   no classes" into "Jena is down" turns every cold start into an outage.
5. **Lands with ca's `MeshOntology` return**, where the three-state result is the CONTRACT rather
   than three patches applied behind one signature.
