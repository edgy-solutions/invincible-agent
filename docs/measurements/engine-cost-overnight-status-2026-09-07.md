---
status: BLOCKED ON A LIVE DEFECT — engine-cost is UNREGISTERED in the running cluster
date: 2026-09-07
engine: engine-cost
---

# Overnight status — declared, resolves, and what question 3 should return

Written to be read cold. Every "resolves" row below is an answer from the **running cluster**,
not a grep of a file.

---

## THE HEADLINE, because it changes what the morning can do

**`engine-cost` is UNREGISTERED in the running mesh and has been for its whole 4h19m uptime.**
Its own log says so, in a named alarm:

> `❌ mesh registration: UNREGISTERED (mint failed: ServiceTokenError: ... Keycloak token
> endpoint unreachable ...)` — *"engine keeps serving but its verbs will NOT route until a
> successful re-registration."*

**Cause, and it is a race rather than a fault in anything:** `iagent-keycloak-0` has 4h24m
uptime, `iagent-engine-cost` has 4h19m. The engine came up roughly five minutes after Keycloak
and Keycloak was **not yet answering** — `[Errno 111] Connection refused` on all five mint
attempts. Registration is attempted **only at startup**, so the engine exhausted its retries and
has served unregistered ever since.

**Keycloak is reachable from the engine now.** Probed from inside the pod:
`http://iagent-keycloak:8080/realms/invincible-agent/.well-known/openid-configuration` answers.
So the state is recoverable by a **roll of `iagent-engine-cost` alone** — nothing else, no helm
upgrade, no prime.

**I did not perform the roll.** Tonight's rule is no deploys until the human is up, and while
engine-cost is a component this lane exclusively owns, a cluster mutation during a stated freeze
is the human's call — especially since the same startup race may have caught other engines, and
a coordinated roll is Lane 1's to sequence, not mine. The evidence also lives in the current
pod's log, which a roll discards.

**Consequence for tonight's ask: question 3 cannot be walked.** Not because the card is wrong —
because no cost verb routes at all. Any "no card" result read before that roll is evidence about
Keycloak's start order, not about bindings, producers, or archetypes.

---

## 1. DECLARED — committed, in the TTL and the code

| thing | where | state |
|---|---|---|
| `cost:ExportPackage` | `setup/ontologies/cost_extension.ttl` | `owl:Class`, `subClassOf mesh:Response`, with comment |
| `cost:DisclosureRecipient` | same | `owl:Class`, `subClassOf prov:Agent`, with comment |
| `mesh:StatefulSupportResponse` | `setup/ontologies/mesh_system.ttl` | declared (another lane's) |
| `mesh:StepLadder` | `setup/ontologies/mesh_system.ttl` (d2a7a89) | declared |
| `mesh:NamedHole` | same | declared |
| 7 cost binding rows | `presentation_agent/capabilities.py` (64e442d) | committed |
| `cost:` lookup prefix | same | committed (ba73c76) |
| `package_export` verb | `cost_agent/` (a070899) | committed, in all six verb tables |

## 2. RESOLVES — SPARQL against the deployed Fuseki (`/ds`, 15,570 triples)

| class | declared | resolves | parent correct | comment |
|---|---|---|---|---|
| `cost:ExportPackage` | yes | **yes** | yes (`mesh:Response`) | yes |
| `cost:DisclosureRecipient` | yes | **yes** | yes (`prov:Agent`) | yes |
| `mesh:StatefulSupportResponse` | yes | **yes** | yes (`mesh:Response`) | yes |
| `mesh:StepLadder` | yes | **NO** | — | — |
| `mesh:NamedHole` | yes | **NO** | — | — |

**The three prime declarations are in the graph.** All 15 `cost:` classes resolve in Fuseki, and
Neo4j reports the same 15 `OntologyClass` nodes, so the ontology sync agreed.

**`mesh:StepLadder` and `mesh:NamedHole` are declared and do not resolve** — they were committed
*after* the prime ran. This is the declared-vs-resolves gap, live, for exactly the two classes
added last.

**So I cannot bind `cost:PriceComposition` yet.** Contract D would refuse on the object end
against the deployed graph. cortex-ui-60's *"bind after the next prime window"* is right and the
window has not happened for `StepLadder`. Post-prime it is three steps in one pass: add the row,
add the conformance case, delete their exemption (their exemption text carries its own deletion
instruction).

**Verb registration is a different registry and is the headline above.** Fuseki holds ontology
only — the sole `mesh#` predicate present is `derivedFrom` — so class resolution says nothing
about whether a verb routes. The authoritative artifact was the engine's own log.

## 3. QUESTION 3 — what it should return

The six, numbered so the record is checkable. Phrasings are the CATALOGUE's own synonyms, so
they exercise the routing signal that actually shipped rather than ones invented for the test.

| # | question | verb | shape | archetype |
|---|---|---|---|---|
| 1 | "what did lot 4 cost" | `cost_lot_breakdown` | `cost:LotCostBreakdown` | CONTRIBUTION_RANKING |
| 2 | "is cost per unit falling" | `cost_unit_price_trend` | `cost:UnitPriceTrend` | MULTI_SERIES |
| **3** | **"where did the money go"** | **`cost_category_breakdown`** | **`cost:CategoryBreakdown`** | **CONTRIBUTION_RANKING** |
| 4 | "what is the labor split" | `cost_labor_composition` | `cost:LaborComposition` | CONTRIBUTION_RANKING |
| 5 | "how concentrated is purchasing" | `cost_supplier_concentration` | `cost:SupplierConcentration` | CONTRIBUTION_RANKING |
| 6 | "did the rates move" | `cost_rate_comparison` | `cost:RateComparison` | DELTA_SET |

### Question 3's card, named so it can be checked against what arrives

**A CONTRIBUTION_RANKING titled by `scope_label`, five rows, ordered largest contribution
first.** For lot 4 the producer emits exactly:

    envelope   value_label "Cost"   scope_label "Lot 4"   total "9885428.00"
               value_unit "USD"     compared_to_lot 3

    rank 1  Labor               7,919,908.00   share 0.8012   direction down
    rank 2  Material            1,475,520.00   share 0.1493   direction up
    rank 3  Contracted effort     346,000.00   share 0.0350   direction down
    rank 4  Other direct          100,800.00   share 0.0102   direction up
    rank 5  Warranty               43,200.00   share 0.0044   direction up

**What makes it right, in checkable terms:**

- **Five rows, not four.** Every category is ranked including the small ones; a truncated
  ranking whose shares sum to less than 1 is the failure the archetype's own contract warns
  about.
- **Shares sum to 1.0000** (0.8012 + 0.1493 + 0.0350 + 0.0102 + 0.0044).
- **`entity_name` is a label, `entity_id` is the engine's key.** The card shows "Contracted
  effort"; the payload still carries `category: "contracts"` beside it.
- **`direction` is movement against lot 3**, which is what makes this a different question from
  #1. If #1 and #3 render identically, the distinction the engine maintains has been lost in
  presentation.
- **The title comes from `scope_label`.** If it reads "Lot 4" the framing arrived; if it is
  blank or generic the passthrough dropped it.

### What a WRONG answer looks like, so the record can distinguish failures

| symptom | means |
|---|---|
| `KNOWLEDGE_DOCUMENT · No content available` | binding row not registered at page load, or the archetype not admitted |
| card draws, all rows blank | producer not emitting `entity_id`/`entity_name`/`contribution` |
| no card, no refusal, generalist prose | **the verb did not route — the UNREGISTERED state above** |
| routed to `fin:WBSElement` | instance preemption; Lane 1 says the post-preemption check is rolled, so this should now abstain instead |

---

## Also true tonight

- **147 cost seals green**, plus the full planning suite. Nothing in this repo is red from this
  lane.
- **`cost_price_composition` is deliberately unbound** with the refusal written beside the rows.
  Six cards should draw and this one should refuse — **that refusal is the designed state, not a
  defect**, and a record that scores it as a miss will be wrong.
- **Timings are not re-derived.** Per tonight's ruling I measured nothing against the old
  hardware calibration and changed no timeout.
