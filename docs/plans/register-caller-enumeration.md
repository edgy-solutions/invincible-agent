---
id:         registration-wiring
status:     closed
owner:      agent
blocked-on: 
closed-by:  9d93146
repo:       invincible-agent
summary:    Six engines mint on /v1/register under decode-witnessed identities. Witnessed at a clean log boundary: 0 new unverified, 6 verified (svc:engine-o 1, svc:engine-w 5 — multiplicities matching each engine's verb count).
---

# `/v1/register` caller enumeration — sizing the identity batch

**Taken 2026-08-08**, against invincible-agent `e18b5cf` / iagent-mesh-sdk `v0.2.2`, with the
gauge reading **22 unverified `/v1/register` calls, 0 verified**.

Ruling already made: **per-engine identities**, because registration *is* routing authority and
a shared credential makes the registrant name a self-asserted payload claim — the
`on_behalf_of` laundering shape at the routing plane. This document sizes that batch and
records two facts that change its shape.

## CORRECTION — the population is SIX services, not nine, and FOUR identities, not nine

Derived from source (`register_engine_to_mesh` importers), not from the gauge's line count:

| service | registers as (payload `name=`) | engine | identity | status |
|---|---|---|---|---|
| `restate_analyst` | `engine_a_lookup_ownership`, `engine_a_assess_impact` | A | `svc:engine-a` | **EXISTS** |
| `data_analyst` | `engine_da_data_analyst` | DA | `svc:data-analyst` | **EXISTS** |
| `datahub_wrapper` | `engine_d_resolve_instance` | D | `svc:engine-d` | **MISSING** |
| `neo4j_expert` | `engine_e_neo4j_expert` | E | `svc:engine-e` | **MISSING** |
| `ontology_service` | `engine_o_sustainment_resolve_instance` | O | `svc:engine-o` | **MISSING** |
| `weaviate_expert` | `engine_w_weaviate_expert` | W | `svc:engine-w` | **MISSING** |

Existing service identities in `policy/users.yaml`: `svc:engine-a`, `svc:data-analyst`,
`svc:supervisor`, `svc:review-starter`.

**So the batch is four new identities: `svc:engine-d`, `svc:engine-e`, `svc:engine-o`,
`svc:engine-w`** — matching the `svc:engine-a` precedent per the mint contract. Two of the six
callers are already covered, which is why the enumeration had to run before the batch was cut:
minting identities for A and DA would have created duplicates of subjects that already carry
grants.

`langgraph_support` (B), `swarms_scraper` (C), `presentation_agent` (F), `projector` and
`domain-broker` do **not** register and need no registration identity. B and C are not deployed
in this sandbox at all.

## The payload name is VERB-SCOPED, which sharpens the hijack argument

`name=` is not an engine name — it is a per-verb registration label, and one engine registers
several (`engine_a_lookup_ownership` *and* `engine_a_assess_impact`). So under a shared
credential the registrar receives a self-asserted string that is **finer-grained than any
identity it could check**, and "engine W registered this" is a claim assembled from a substring
convention. Binding verbs to an **authenticated registrant** replaces a naming convention with
a cryptographic fact, and makes the future gate expressible: *may this caller register or
overwrite THIS verb* is keyed on the identity, unanswerable under a shared credential.

## TWO IMPLEMENTATIONS — the mint-function story again, predicted and confirmed

| implementation | who uses it |
|---|---|
| `agent_fleet/utils/mesh_registration.py::register_engine_to_mesh` | the six platform engines above |
| `iagent_mesh/core.py:337` — `client.post(f"{registrar_url}/v1/register", …)` | SDK `MeshTool`, for externally scaffolded engines |

Two transcriptions of one call, exactly the divergence the one-implementation rule exists to
prevent — and the same shape as the two mints (`mint_service_token` reading
`REVIEW_STARTER_CLIENT_ID` while the SDK's read `MESH_CLIENT_ID`), which produced the
confused-deputy bug. **The mint must not be added twice.** Options, in preference order:

1. **Platform binds the SDK's** — `register_engine_to_mesh` becomes a thin binding over the
   SDK's registration, as `service_identity.py` became a binding over `mint_token`. One
   implementation, one place the Authorization header is attached.
2. Both call one shared registration function that mints internally. Acceptable but leaves two
   call sites to keep honest.

Do **not** paste `Authorization` into both. That is how the env-contract drift happened last
time, and it was invisible until a token was decoded.

## DEFINITION OF DONE for the mint change — retry is not a follow-up

Registration at boot **already has a race pedigree**: engines racing the registrar at first
deploy, `500`s, serving silently with unregistered verbs. Witnessed again during last night's
roll — `/v1/register` returned 500 while Neo4j was still booting, and recovered only because a
later restart retried by accident.

Minting adds **Keycloak** to that boot chain. Under OBSERVE a mint failure logs and proceeds.
Under REQUIRE it becomes the old bug with a new cause: **mint fails at boot → registration
denied → the engine serves with its verbs silently absent from routing.** Not an outage — a
silent degradation, which this project has spent a month establishing is the worse failure.

So the mint change ships with, as part of its definition of done:

1. **Retry-until-registered with backoff**, never capture-once-at-boot — the repair the
   cache-staleness ruling already established as superior for this class.
2. **A loud surface when registration remains unachieved** — the posture announcement line or a
   readiness gate, so an unregistered engine is *visible* rather than merely unrouted. An engine
   that is up, healthy, and invisible to routing is precisely the state no probe currently
   detects.

## Sequence

1. ~~enumeration~~ — done, this document. **Four identities, six callers, two implementations.**
2. identity batch: `svc:engine-d/e/o/w` scaffold stanzas, one PR, reconcile job converges,
   each decode-witnessed.
3. consolidate registration to one implementation, then mint at that one seam, with retry +
   loud-unregistered.
4. watch the gauge fall 22 → 0 on non-exempt paths.
5. the flip, whose precondition is then a zero someone witnessed arriving.
